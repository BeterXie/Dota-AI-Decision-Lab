from collections import defaultdict
from datetime import datetime, timedelta
from math import sqrt
from statistics import mean, median
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history.scoring import (
    beta_adjusted_win_rate,
    combine_supported,
    player_form_confidence,
    player_hero_confidence,
    position_fit,
    recent_player_form,
    role_metric_z,
    roster_stability,
    update_elo,
    weighted_metric_score,
    weighted_recent_win_form,
)
from app.history.weights import MODEL_VERSION, POSITION_METRIC_WEIGHTS
from app.models import (
    CanonicalMap,
    HistoricalMapRecord,
    HistoricalPlayerMapRecord,
    PlayerFormSnapshotRecord,
    PlayerHeroSnapshotRecord,
    PlayerPerformanceMapRecord,
    RoleMetricBaselineRecord,
    TeamFormSnapshotRecord,
    TeamRatingSnapshotRecord,
)

TEAM_ELO_VERSION = "team-elo-v1"
TEAM_FORM_VERSION = "team-form-v1"
PLAYER_HERO_VERSION = "player-hero-v1"


class HistoricalFeatureBuilder:
    def __init__(self, *, initial_elo: float, elo_k: float) -> None:
        self._initial_elo = initial_elo
        self._elo_k = elo_k

    async def build_team_ratings(self, session: AsyncSession, *, as_of: datetime) -> int:
        facts = list(
            (
                await session.scalars(
                    select(HistoricalMapRecord).where(
                        HistoricalMapRecord.first_usable_at <= as_of,
                        HistoricalMapRecord.canonical_map_id.is_not(None),
                        HistoricalMapRecord.radiant_team_id.is_not(None),
                        HistoricalMapRecord.dire_team_id.is_not(None),
                        HistoricalMapRecord.winner_team_id.is_not(None),
                        HistoricalMapRecord.sync_status != "DATA_CONFLICT",
                    )
                )
            ).all()
        )
        preferred = _preferred_map_facts(facts)
        processed = set(
            (
                await session.scalars(
                    select(HistoricalMapRecord.provider_match_id)
                    .join(
                        TeamRatingSnapshotRecord,
                        TeamRatingSnapshotRecord.source_map_id == HistoricalMapRecord.id,
                    )
                    .where(TeamRatingSnapshotRecord.model_version == TEAM_ELO_VERSION)
                )
            ).all()
        )
        latest_ratings: dict[UUID, float] = {}
        snapshots = list(
            (
                await session.scalars(
                    select(TeamRatingSnapshotRecord)
                    .where(TeamRatingSnapshotRecord.knowledge_cutoff <= as_of)
                    .order_by(TeamRatingSnapshotRecord.knowledge_cutoff.desc())
                )
            ).all()
        )
        for snapshot in snapshots:
            latest_ratings.setdefault(snapshot.canonical_team_id, snapshot.rating)

        created = 0
        for fact in sorted(
            preferred,
            key=lambda item: (item.first_usable_at, item.started_at, item.provider_match_id),
        ):
            if fact.provider_match_id in processed:
                continue
            radiant_id = fact.radiant_team_id
            dire_id = fact.dire_team_id
            if radiant_id is None or dire_id is None or fact.winner_team_id is None:
                continue
            radiant_before = latest_ratings.get(radiant_id, self._initial_elo)
            dire_before = latest_ratings.get(dire_id, self._initial_elo)
            winner = "A" if fact.winner_team_id == radiant_id else "B"
            update = update_elo(radiant_before, dire_before, winner, k=self._elo_k)
            session.add_all(
                [
                    TeamRatingSnapshotRecord(
                        canonical_team_id=radiant_id,
                        rating=update.rating_a,
                        rating_before=radiant_before,
                        opponent_rating_before=dire_before,
                        expected_probability=update.expected_a,
                        result=1.0 if winner == "A" else 0.0,
                        source_map_id=fact.id,
                        knowledge_cutoff=fact.first_usable_at,
                        model_version=TEAM_ELO_VERSION,
                    ),
                    TeamRatingSnapshotRecord(
                        canonical_team_id=dire_id,
                        rating=update.rating_b,
                        rating_before=dire_before,
                        opponent_rating_before=radiant_before,
                        expected_probability=update.expected_b,
                        result=1.0 if winner == "B" else 0.0,
                        source_map_id=fact.id,
                        knowledge_cutoff=fact.first_usable_at,
                        model_version=TEAM_ELO_VERSION,
                    ),
                ]
            )
            latest_ratings[radiant_id] = update.rating_a
            latest_ratings[dire_id] = update.rating_b
            processed.add(fact.provider_match_id)
            created += 2
        return created

    async def build_team_form(
        self,
        session: AsyncSession,
        *,
        canonical_team_id: UUID,
        roster_player_ids: list[UUID],
        as_of: datetime,
    ) -> TeamFormSnapshotRecord | None:
        facts = list(
            (
                await session.scalars(
                    select(HistoricalMapRecord).where(
                        or_(
                            HistoricalMapRecord.radiant_team_id == canonical_team_id,
                            HistoricalMapRecord.dire_team_id == canonical_team_id,
                        ),
                        HistoricalMapRecord.first_usable_at <= as_of,
                        HistoricalMapRecord.winner_team_id.is_not(None),
                        HistoricalMapRecord.sync_status != "DATA_CONFLICT",
                    )
                )
            ).all()
        )
        preferred = sorted(
            _preferred_map_facts(facts), key=lambda item: item.started_at, reverse=True
        )[:20]
        if not preferred:
            return None
        results = [fact.winner_team_id == canonical_team_id for fact in preferred]
        exact_roster_maps = 0
        expected_roster = set(roster_player_ids)
        if len(expected_roster) == 5:
            for fact in preferred:
                players = set(
                    (
                        await session.scalars(
                            select(HistoricalPlayerMapRecord.canonical_player_id).where(
                                HistoricalPlayerMapRecord.historical_map_id == fact.id,
                                HistoricalPlayerMapRecord.canonical_team_id == canonical_team_id,
                                HistoricalPlayerMapRecord.canonical_player_id.is_not(None),
                            )
                        )
                    ).all()
                )
                exact_roster_maps += int(players == expected_roster)
        knowledge_cutoff = max(fact.first_usable_at for fact in preferred)
        existing = await session.scalar(
            select(TeamFormSnapshotRecord).where(
                TeamFormSnapshotRecord.canonical_team_id == canonical_team_id,
                TeamFormSnapshotRecord.knowledge_cutoff == knowledge_cutoff,
                TeamFormSnapshotRecord.model_version == TEAM_FORM_VERSION,
            )
        )
        if existing is not None:
            return existing
        snapshot = TeamFormSnapshotRecord(
            canonical_team_id=canonical_team_id,
            last_5_maps=min(len(results), 5),
            last_5_wins=sum(results[:5]),
            last_10_maps=min(len(results), 10),
            last_10_wins=sum(results[:10]),
            last_20_maps=len(results),
            last_20_wins=sum(results),
            recent_form=weighted_recent_win_form(results),
            exact_roster_maps=exact_roster_maps,
            roster_stability=roster_stability(exact_roster_maps),
            knowledge_cutoff=knowledge_cutoff,
            model_version=TEAM_FORM_VERSION,
        )
        session.add(snapshot)
        await session.flush()
        return snapshot

    async def build_role_baselines(self, session: AsyncSession, *, as_of: datetime) -> int:
        rows = await self._eligible_player_rows(session, as_of=as_of)
        grouped: dict[tuple[str, int, str], list[float]] = defaultdict(list)
        for player, fact in rows:
            if player.position is None or fact.patch_id is None:
                continue
            for metric, value in _metrics(player, fact).items():
                if value is not None:
                    grouped[(fact.patch_id, player.position, metric)].append(value)
        created = 0
        for (patch_id, position, metric), values in grouped.items():
            existing = await session.scalar(
                select(RoleMetricBaselineRecord.id).where(
                    RoleMetricBaselineRecord.patch_id == patch_id,
                    RoleMetricBaselineRecord.position == position,
                    RoleMetricBaselineRecord.metric == metric,
                    RoleMetricBaselineRecord.knowledge_cutoff == as_of,
                )
            )
            if existing is not None:
                continue
            session.add(
                RoleMetricBaselineRecord(
                    patch_id=patch_id,
                    position=position,
                    metric=metric,
                    sample_size=len(values),
                    mean=mean(values),
                    std=_population_std(values),
                    median=median(values),
                    p25=_nearest_rank(values, 0.25),
                    p75=_nearest_rank(values, 0.75),
                    knowledge_cutoff=as_of,
                )
            )
            created += 1
        return created

    async def build_player_form(
        self,
        session: AsyncSession,
        *,
        canonical_player_id: UUID,
        position: int,
        as_of: datetime,
    ) -> PlayerFormSnapshotRecord | None:
        rows = [
            row
            for row in await self._eligible_player_rows(
                session, as_of=as_of, canonical_player_id=canonical_player_id
            )
            if row[0].position == position and row[1].canonical_map_id is not None
        ]
        rows = _preferred_player_rows(rows)[:100]
        if not rows:
            return None
        baselines = await self._baseline_lookup(session, position=position, as_of=as_of)
        scored: list[tuple[float, CanonicalMap]] = []
        for player, fact in rows:
            canonical_map = await session.get(CanonicalMap, fact.canonical_map_id)
            if canonical_map is None or fact.patch_id is None:
                continue
            raw_metrics = _metrics(player, fact)
            metric_z = {
                name: role_metric_z(
                    value,
                    baselines.get((fact.patch_id, name), (None, None))[0],
                    baselines.get((fact.patch_id, name), (None, None))[1],
                )
                for name, value in raw_metrics.items()
            }
            score = weighted_metric_score(metric_z, POSITION_METRIC_WEIGHTS[position])
            if score is None:
                continue
            existing = await session.scalar(
                select(PlayerPerformanceMapRecord.id).where(
                    PlayerPerformanceMapRecord.canonical_player_id == canonical_player_id,
                    PlayerPerformanceMapRecord.canonical_map_id == canonical_map.id,
                    PlayerPerformanceMapRecord.knowledge_cutoff == as_of,
                    PlayerPerformanceMapRecord.model_version == MODEL_VERSION,
                )
            )
            if existing is None:
                session.add(
                    PlayerPerformanceMapRecord(
                        canonical_player_id=canonical_player_id,
                        canonical_map_id=canonical_map.id,
                        source_historical_player_map_id=player.id,
                        position=position,
                        metric_payload={"raw": raw_metrics, "z": metric_z},
                        role_adjusted_score=score,
                        knowledge_cutoff=as_of,
                        model_version=MODEL_VERSION,
                    )
                )
            scored.append((score, canonical_map))
        if not scored:
            return None
        scores = [score for score, _ in scored]
        existing_snapshot = await session.scalar(
            select(PlayerFormSnapshotRecord).where(
                PlayerFormSnapshotRecord.canonical_player_id == canonical_player_id,
                PlayerFormSnapshotRecord.position == position,
                PlayerFormSnapshotRecord.knowledge_cutoff == as_of,
                PlayerFormSnapshotRecord.model_version == MODEL_VERSION,
            )
        )
        if existing_snapshot is not None:
            return existing_snapshot
        snapshot = PlayerFormSnapshotRecord(
            canonical_player_id=canonical_player_id,
            position=position,
            base_strength=mean(scores),
            recent_5=mean(scores[:5]),
            recent_10=mean(scores[:10]),
            recent_20=mean(scores[:20]),
            recent_form=recent_player_form(scores),
            sample_size=len(scores),
            confidence=player_form_confidence(
                len(scores),
                data_completeness=len(scores) / len(rows),
                role_identity_confidence=1.0,
            ),
            last_included_map_id=scored[0][1].id,
            knowledge_cutoff=as_of,
            model_version=MODEL_VERSION,
        )
        session.add(snapshot)
        await session.flush()
        return snapshot

    async def build_player_hero(
        self,
        session: AsyncSession,
        *,
        canonical_player_id: UUID,
        hero_id: int,
        position: int,
        as_of: datetime,
    ) -> PlayerHeroSnapshotRecord | None:
        all_rows = await self._eligible_player_rows(
            session,
            as_of=as_of,
            canonical_player_id=canonical_player_id,
            require_advanced=False,
        )
        hero_rows = _preferred_player_rows([row for row in all_rows if row[0].hero_id == hero_id])
        if not hero_rows:
            return None
        current_position = [row for row in hero_rows if row[0].position == position]
        recent_cutoff = as_of - timedelta(days=180)
        recent_all = [row for row in hero_rows if row[1].started_at >= recent_cutoff]
        recent = [row for row in current_position if row[1].started_at >= recent_cutoff]
        current_patch = next(
            (fact.patch_id for _, fact in hero_rows if fact.patch_id is not None), None
        )
        patch_rows = (
            [row for row in current_position if row[1].patch_id == current_patch]
            if current_patch is not None
            else []
        )
        performance = await self._performance_lookup(
            session, canonical_player_id=canonical_player_id, as_of=as_of
        )
        historical_performance = _performance_mean(current_position, performance)
        recent_performance = _performance_mean(recent, performance)
        patch_performance = _performance_mean(patch_rows, performance)
        historical_rate = _raw_win_rate(current_position)
        recent_rate = _raw_win_rate(recent)
        patch_rate = _raw_win_rate(patch_rows)
        raw_strength = combine_supported(
            [
                (_window_strength(historical_rate, historical_performance), 0.30),
                (_window_strength(recent_rate, recent_performance), 0.40),
                (_window_strength(patch_rate, patch_performance), 0.30),
            ]
        )
        adjusted_strength = combine_supported(
            [
                (
                    _window_strength(_shrunk_win_rate(current_position), historical_performance),
                    0.30,
                ),
                (
                    _window_strength(_shrunk_win_rate(recent), recent_performance),
                    0.40,
                ),
                (
                    _window_strength(_shrunk_win_rate(patch_rows), patch_performance),
                    0.30,
                ),
            ]
        )
        fit = position_fit(len(recent), len(recent_all))
        if adjusted_strength is not None and fit is not None:
            adjusted_strength *= 0.5 + 0.5 * fit
        existing = await session.scalar(
            select(PlayerHeroSnapshotRecord).where(
                PlayerHeroSnapshotRecord.canonical_player_id == canonical_player_id,
                PlayerHeroSnapshotRecord.hero_id == hero_id,
                PlayerHeroSnapshotRecord.position == position,
                PlayerHeroSnapshotRecord.knowledge_cutoff == as_of,
                PlayerHeroSnapshotRecord.model_version == PLAYER_HERO_VERSION,
            )
        )
        if existing is not None:
            return existing
        snapshot = PlayerHeroSnapshotRecord(
            canonical_player_id=canonical_player_id,
            hero_id=hero_id,
            position=position,
            historical_maps=len(current_position),
            historical_win_rate=historical_rate,
            historical_performance=historical_performance,
            recent_180d_maps=len(recent),
            recent_180d_win_rate=recent_rate,
            recent_180d_performance=recent_performance,
            current_patch_maps=len(patch_rows),
            current_patch_win_rate=patch_rate,
            current_patch_performance=patch_performance,
            position_fit=fit,
            raw_strength=raw_strength,
            adjusted_strength=adjusted_strength,
            confidence=player_hero_confidence(
                len(current_position), len(recent), len(patch_rows), 1.0
            ),
            last_included_map_id=hero_rows[0][1].canonical_map_id,
            knowledge_cutoff=as_of,
            model_version=PLAYER_HERO_VERSION,
        )
        session.add(snapshot)
        await session.flush()
        return snapshot

    async def _eligible_player_rows(
        self,
        session: AsyncSession,
        *,
        as_of: datetime,
        canonical_player_id: UUID | None = None,
        require_advanced: bool = True,
    ) -> list[tuple[HistoricalPlayerMapRecord, HistoricalMapRecord]]:
        statement = (
            select(HistoricalPlayerMapRecord, HistoricalMapRecord)
            .join(
                HistoricalMapRecord,
                HistoricalMapRecord.id == HistoricalPlayerMapRecord.historical_map_id,
            )
            .where(
                HistoricalMapRecord.first_usable_at <= as_of,
                HistoricalMapRecord.sync_status != "DATA_CONFLICT",
                HistoricalMapRecord.canonical_map_id.is_not(None),
            )
            .order_by(HistoricalMapRecord.started_at.desc())
        )
        if require_advanced:
            statement = statement.where(
                HistoricalPlayerMapRecord.advanced_first_usable_at.is_not(None),
                HistoricalPlayerMapRecord.advanced_first_usable_at <= as_of,
            )
        else:
            statement = statement.where(HistoricalPlayerMapRecord.basic_first_usable_at <= as_of)
        if canonical_player_id is not None:
            statement = statement.where(
                HistoricalPlayerMapRecord.canonical_player_id == canonical_player_id
            )
        return [(player, fact) for player, fact in (await session.execute(statement)).all()]

    async def _baseline_lookup(
        self, session: AsyncSession, *, position: int, as_of: datetime
    ) -> dict[tuple[str, str], tuple[float | None, float | None]]:
        records = list(
            (
                await session.scalars(
                    select(RoleMetricBaselineRecord)
                    .where(
                        RoleMetricBaselineRecord.position == position,
                        RoleMetricBaselineRecord.knowledge_cutoff <= as_of,
                    )
                    .order_by(RoleMetricBaselineRecord.knowledge_cutoff.desc())
                )
            ).all()
        )
        result: dict[tuple[str, str], tuple[float | None, float | None]] = {}
        for record in records:
            result.setdefault((record.patch_id, record.metric), (record.mean, record.std))
        return result

    async def _performance_lookup(
        self,
        session: AsyncSession,
        *,
        canonical_player_id: UUID,
        as_of: datetime,
    ) -> dict[UUID, float]:
        records = list(
            (
                await session.scalars(
                    select(PlayerPerformanceMapRecord)
                    .where(
                        PlayerPerformanceMapRecord.canonical_player_id == canonical_player_id,
                        PlayerPerformanceMapRecord.knowledge_cutoff <= as_of,
                        PlayerPerformanceMapRecord.role_adjusted_score.is_not(None),
                    )
                    .order_by(PlayerPerformanceMapRecord.knowledge_cutoff.desc())
                )
            ).all()
        )
        result: dict[UUID, float] = {}
        for record in records:
            if record.role_adjusted_score is not None:
                result.setdefault(record.canonical_map_id, record.role_adjusted_score)
        return result


def _preferred_map_facts(facts: list[HistoricalMapRecord]) -> list[HistoricalMapRecord]:
    grouped: dict[str, HistoricalMapRecord] = {}
    for fact in facts:
        current = grouped.get(fact.provider_match_id)
        if current is None or (fact.provider == "stratz" and current.provider != "stratz"):
            grouped[fact.provider_match_id] = fact
    return list(grouped.values())


def _preferred_player_rows(
    rows: list[tuple[HistoricalPlayerMapRecord, HistoricalMapRecord]],
) -> list[tuple[HistoricalPlayerMapRecord, HistoricalMapRecord]]:
    grouped: dict[UUID, tuple[HistoricalPlayerMapRecord, HistoricalMapRecord]] = {}
    for row in rows:
        canonical_map_id = row[1].canonical_map_id
        if canonical_map_id is None:
            continue
        current = grouped.get(canonical_map_id)
        if current is None or (row[1].provider == "stratz" and current[1].provider != "stratz"):
            grouped[canonical_map_id] = row
    return sorted(grouped.values(), key=lambda row: row[1].started_at, reverse=True)


def _metrics(
    player: HistoricalPlayerMapRecord, fact: HistoricalMapRecord
) -> dict[str, float | None]:
    duration_minutes = (
        (fact.ended_at - fact.started_at).total_seconds() / 60.0
        if fact.ended_at is not None
        else None
    )
    kda = (
        (player.kills + player.assists) / max(player.deaths, 1)
        if player.kills is not None and player.assists is not None and player.deaths is not None
        else None
    )
    return {
        "gpm": player.gpm,
        "xpm": player.xpm,
        "kda": kda,
        "networth": player.networth,
        "hero_damage": player.hero_damage,
        "tower_damage": player.tower_damage,
        "last_hits": float(player.last_hits) if player.last_hits is not None else None,
        "assists": float(player.assists) if player.assists is not None else None,
        "death_rate": (
            player.deaths / duration_minutes
            if player.deaths is not None and duration_minutes is not None and duration_minutes > 0
            else None
        ),
        "impact": player.impact,
    }


def _population_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    average = mean(values)
    return sqrt(sum((value - average) ** 2 for value in values) / len(values))


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(max(round((len(ordered) - 1) * percentile), 0), len(ordered) - 1)
    return ordered[index]


def _raw_win_rate(
    rows: list[tuple[HistoricalPlayerMapRecord, HistoricalMapRecord]],
) -> float | None:
    return mean([1.0 if player.won else 0.0 for player, _ in rows]) if rows else None


def _shrunk_win_rate(
    rows: list[tuple[HistoricalPlayerMapRecord, HistoricalMapRecord]],
) -> float | None:
    return beta_adjusted_win_rate(
        sum(player.won for player, _ in rows), len(rows), prior_mean=0.5, prior_strength=12
    )


def _performance_mean(
    rows: list[tuple[HistoricalPlayerMapRecord, HistoricalMapRecord]],
    performance: dict[UUID, float],
) -> float | None:
    values = [
        performance[fact.canonical_map_id]
        for _, fact in rows
        if fact.canonical_map_id in performance
    ]
    return mean(values) if values else None


def _window_strength(win_rate: float | None, performance: float | None) -> float | None:
    values: list[float] = []
    if win_rate is not None:
        values.append((win_rate - 0.5) * 2.0)
    if performance is not None:
        values.append(min(max(performance / 3.0, -1.0), 1.0))
    return mean(values) if values else None
