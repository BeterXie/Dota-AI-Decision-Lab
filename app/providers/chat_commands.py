"""Shared inbound command and decision rendering for chat channels.

WeChat ClawBot and QQ Bot expose the same Dota AI commands (current matches,
current odds, latest BUY reasons, notification pause/resume).  Keeping the
query and rendering logic here means both channels use one implementation and
cannot drift.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.decision import target_probability
from app.domain.snapshot import DecisionSnapshot
from app.market.current import evaluate_current_market_pair, map_market_stages
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    MapResultRecord,
    OddsObservationRecord,
)
from app.time import ensure_utc


class NotificationPreferences(Protocol):
    def decision_notifications_enabled(self) -> bool: ...

    def set_decision_notifications(self, enabled: bool) -> None: ...


def render_decision_notification(
    snapshot: DecisionSnapshot,
    decisions: list[AiDecisionRecord],
    *,
    channel_label: str = "微信",
) -> str:
    """Render one immutable snapshot batch for a chat push.

    ``channel_label`` only changes the header; match facts and AI outputs are
    always rendered from the same snapshot/decision records.
    """
    identity = snapshot.identity or {}
    team_a = _team_name(identity.get("team_a"), "Team A")
    team_b = _team_name(identity.get("team_b"), "Team B")
    mode = snapshot.mode.value
    map_number = identity.get("map_number")
    market = snapshot.market or {}
    observations = market.get("observations") if isinstance(market, dict) else None
    price_a = _market_price(observations, _team_id(identity.get("team_a")))
    price_b = _market_price(observations, _team_id(identity.get("team_b")))
    lines = [
        f"🎯 Dota AI Decision Lab · {channel_label}",
        f"对阵: {team_a} vs {team_b}" + (f" · 第{map_number}局" if map_number else ""),
        f"分析阶段: {mode}",
        f"赔率: {team_a} {price_a or '—'} / {team_b} {price_b or '—'}",
        "",
    ]
    for decision in sorted(decisions, key=lambda item: (item.provider, item.model)):
        normalized = decision.normalized_response or {}
        action = normalized.get("action")
        label = {
            "BUY_A": f"支持 {team_a}",
            "BUY_B": f"支持 {team_b}",
            "NO_BUY": "暂不参与",
            "INSUFFICIENT_DATA": "数据不足",
        }.get(str(action), str(action or "未知"))
        confidence = normalized.get("confidence")
        probability = target_probability(
            str(action),
            normalized.get("fair_probability_a")
            if isinstance(normalized.get("fair_probability_a"), (int, float))
            else None,
        )
        lines.append(f"▪ {decision.provider.upper()} / {decision.model}: {label}")
        if isinstance(probability, (int, float)):
            lines.append(f"  AI胜率: {probability * 100:.1f}%")
        if isinstance(confidence, (int, float)):
            lines.append(f"  置信度: {confidence * 100:.1f}%")
        reasons = normalized.get("primary_reasons") or []
        if reasons:
            lines.append(f"  理由: {'; '.join(str(item) for item in reasons[:3])}")
    lines.extend(["", "快照: " + snapshot.snapshot_hash[:16]])
    return "\n".join(lines)


async def command_reply(
    session: AsyncSession,
    preferences: NotificationPreferences,
    text: str,
    *,
    channel_label: str,
    live_state_max_age_seconds: float = 120.0,
    live_market_max_age_seconds: float = 90.0,
    market_max_pair_skew_seconds: float = 5.0,
) -> str:
    normalized = text.strip().casefold()
    if not normalized:
        return help_text(channel_label)
    # Check the more specific odds command before the generic matches command.
    if "当前比赛赔率" in normalized:
        return await odds_reply(
            session,
            live_state_max_age_seconds=live_state_max_age_seconds,
            live_market_max_age_seconds=live_market_max_age_seconds,
            market_max_pair_skew_seconds=market_max_pair_skew_seconds,
        )
    if "当前比赛" in normalized or normalized in {"matches", "比赛"}:
        return await matches_reply(
            session,
            live_state_max_age_seconds=live_state_max_age_seconds,
        )
    if "暂停" in normalized and "通知" in normalized:
        preferences.set_decision_notifications(False)
        return f"✅ 已暂停 AI 决策{channel_label}通知。发送「恢复通知」重新开启。"
    if ("恢复" in normalized or "开启" in normalized) and "通知" in normalized:
        preferences.set_decision_notifications(True)
        return f"✅ 已恢复 AI 决策{channel_label}通知。"
    if "为什么" in normalized or "buy" in normalized:
        return await decision_reply(session, text)
    if normalized in {"帮助", "help", "?"}:
        return help_text(channel_label)
    return help_text(channel_label)


async def current_live_map_rows(
    session: AsyncSession,
    *,
    observed_at: datetime,
    live_state_max_age_seconds: float,
) -> list[
    tuple[CanonicalMap, CanonicalSeries, CanonicalTeam, CanonicalTeam, DltvLiveObservationRecord]
]:
    team_a_alias = aliased(CanonicalTeam)
    team_b_alias = aliased(CanonicalTeam)
    # One observation stream can emit many rows per map; keep only the latest
    # live observation per map (the same subquery pattern used by the web API),
    # then drop maps that already have a result or whose latest observation is
    # stale.  This prevents one active map from filling all five reply slots.
    latest_live = (
        select(
            DltvLiveObservationRecord.canonical_map_id,
            func.max(DltvLiveObservationRecord.received_at).label("latest_received_at"),
        )
        .where(DltvLiveObservationRecord.canonical_map_id.is_not(None))
        .group_by(DltvLiveObservationRecord.canonical_map_id)
        .subquery()
    )
    freshness_cutoff = observed_at - timedelta(seconds=live_state_max_age_seconds)
    return list(
        (
            await session.execute(
                select(
                    CanonicalMap,
                    CanonicalSeries,
                    team_a_alias,
                    team_b_alias,
                    DltvLiveObservationRecord,
                )
                .join(CanonicalSeries, CanonicalSeries.id == CanonicalMap.series_id)
                .join(team_a_alias, team_a_alias.id == CanonicalSeries.team_a_id)
                .join(team_b_alias, team_b_alias.id == CanonicalSeries.team_b_id)
                .join(latest_live, latest_live.c.canonical_map_id == CanonicalMap.id)
                .join(
                    DltvLiveObservationRecord,
                    and_(
                        DltvLiveObservationRecord.canonical_map_id
                        == latest_live.c.canonical_map_id,
                        DltvLiveObservationRecord.received_at == latest_live.c.latest_received_at,
                    ),
                )
                .outerjoin(MapResultRecord, MapResultRecord.canonical_map_id == CanonicalMap.id)
                .where(
                    CanonicalMap.valve_match_id.is_not(None),
                    MapResultRecord.id.is_(None),
                    DltvLiveObservationRecord.received_at >= freshness_cutoff,
                )
                .order_by(latest_live.c.latest_received_at.desc())
                .limit(5)
            )
        ).all()
    )


async def matches_reply(session: AsyncSession, *, live_state_max_age_seconds: float = 120.0) -> str:
    maps = await current_live_map_rows(
        session,
        observed_at=datetime.now(UTC),
        live_state_max_age_seconds=live_state_max_age_seconds,
    )
    if not maps:
        return "当前没有正在追踪的比赛。"
    lines = ["当前比赛:"]
    for map_record, _series, team_a, team_b, live in maps:
        lines.append(
            f"▪ {team_a.name} vs {team_b.name} · 第{map_record.map_number or '?'}局"
            f" · 击杀 {live.radiant_kills}-{live.dire_kills}"
        )
    return "\n".join(lines)


async def odds_reply(
    session: AsyncSession,
    *,
    live_state_max_age_seconds: float = 120.0,
    live_market_max_age_seconds: float = 90.0,
    market_max_pair_skew_seconds: float = 5.0,
    observed_at: datetime | None = None,
) -> str:
    observed_at = observed_at if observed_at is not None else datetime.now(UTC)
    maps = await current_live_map_rows(
        session,
        observed_at=observed_at,
        live_state_max_age_seconds=live_state_max_age_seconds,
    )
    if not maps:
        return "当前没有正在直播的比赛。"
    map_ids = [map_record.id for map_record, _series, _team_a, _team_b, _live in maps]
    series_ids = [series.id for _map_record, series, _team_a, _team_b, _live in maps]
    latest_market_times = (
        select(
            OddsObservationRecord.odds_id,
            func.max(OddsObservationRecord.received_at).label("latest_received_at"),
        )
        .where(
            OddsObservationRecord.market_type == "Winner",
            or_(
                OddsObservationRecord.canonical_map_id.in_(map_ids),
                OddsObservationRecord.canonical_series_id.in_(series_ids),
            ),
        )
        .group_by(OddsObservationRecord.odds_id)
        .subquery()
    )
    market_rows = list(
        (
            await session.scalars(
                select(OddsObservationRecord).join(
                    latest_market_times,
                    and_(
                        OddsObservationRecord.odds_id == latest_market_times.c.odds_id,
                        OddsObservationRecord.received_at
                        == latest_market_times.c.latest_received_at,
                    ),
                )
            )
        ).all()
    )
    lines = ["当前比赛赔率:"]
    for map_record, series, team_a, team_b, _live in maps:
        lines.append(f"▪ {team_a.name} vs {team_b.name} · 第{map_record.map_number or '?'}局")
        stages = map_market_stages(map_record.map_number, best_of=series.best_of)
        candidate_rows = [
            row
            for row in market_rows
            if row.match_stage in stages
            and (row.canonical_map_id == map_record.id or row.canonical_series_id == series.id)
        ]
        evaluated = evaluate_current_market_pair(
            candidate_rows,
            series=series,
            canonical_map_id=map_record.id,
            observed_at=observed_at,
            live_market_max_age_seconds=live_market_max_age_seconds,
            market_max_pair_skew_seconds=market_max_pair_skew_seconds,
        )
        if evaluated is None:
            lines.append("  赔率: 暂无可用赔率")
            continue
        (leg_a, leg_b), quality = evaluated
        status_note = "" if quality.eligible else " · ⚠️ 赔率未通过实时校验"
        lines.append(
            f"  赔率: {team_a.name} {leg_a.price:.2f}"
            f" / {team_b.name} {leg_b.price:.2f}{status_note}"
        )
        updated_at = ensure_utc(max(leg_a.received_at, leg_b.received_at))
        lines.append(f"  更新: {updated_at.strftime('%H:%M UTC')}")
    return "\n".join(lines)


async def decision_reply(session: AsyncSession, query: str) -> str:
    rows = list(
        (
            await session.scalars(
                select(AiDecisionRecord)
                .join(
                    DecisionSnapshotRecord,
                    DecisionSnapshotRecord.id == AiDecisionRecord.snapshot_id,
                )
                .where(AiDecisionRecord.parse_status == "SUCCESS")
                .order_by(AiDecisionRecord.request_started_at.desc())
                .limit(80)
            )
        ).all()
    )
    needle = query.casefold()
    matches = []
    for record in rows:
        snapshot = await session.get(DecisionSnapshotRecord, record.snapshot_id)
        if snapshot is None:
            continue
        identity = (snapshot.canonical_payload or {}).get("identity") or {}
        team_a = _team_name(identity.get("team_a"), "Team A")
        team_b = _team_name(identity.get("team_b"), "Team B")
        haystack = f"{team_a} {team_b} {record.provider} {record.model}".casefold()
        if needle not in haystack and not any(
            token in haystack for token in needle.split() if len(token) >= 2
        ):
            continue
        action = (record.normalized_response or {}).get("action")
        if action not in {"BUY_A", "BUY_B"}:
            continue
        matches.append(
            {
                "team_a": team_a,
                "team_b": team_b,
                "provider": record.provider,
                "model": record.model,
                "action": action,
                "normalized": record.normalized_response or {},
                "decision_at": snapshot.decision_at,
            }
        )
        if len(matches) >= 3:
            break
    if not matches:
        return f"没有找到与「{query.strip()}」相关的 BUY 决策。"
    lines = ["最近的买入决策:"]
    for item in matches:
        target = item["team_a"] if item["action"] == "BUY_A" else item["team_b"]
        normalized = item["normalized"]
        fair_probability_a = normalized.get("fair_probability_a")
        probability = target_probability(
            str(item["action"]),
            fair_probability_a if isinstance(fair_probability_a, (int, float)) else None,
        )
        confidence = normalized.get("confidence")
        reasons = normalized.get("primary_reasons") or []
        lines.append(
            f"▪ {item['provider'].upper()} / {item['model']} 支持 {target}"
            f" · AI胜率 {probability * 100:.1f}%"
            if isinstance(probability, (int, float))
            else f"▪ {item['provider'].upper()} / {item['model']} 支持 {target}"
        )
        if isinstance(confidence, (int, float)):
            lines.append(f"  置信度: {confidence * 100:.1f}%")
        if reasons:
            lines.append(f"  理由: {'; '.join(str(reason) for reason in reasons[:3])}")
        lines.append(f"  决策时间: {ensure_utc(item['decision_at']).strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def help_text(channel_label: str = "微信") -> str:
    return "\n".join(
        [
            f"Dota AI Decision Lab {channel_label}指令:",
            "▪ 当前比赛 — 查看正在追踪的比赛",
            "▪ 当前比赛赔率 — 查看当前直播比赛双方赔率",
            "▪ 为什么买 <队伍> — 查询最近 BUY 决策理由",
            "▪ 暂停通知 / 恢复通知 — 开关 AI 决策推送",
        ]
    )


def _team_name(value: object, fallback: str) -> str:
    if isinstance(value, dict) and isinstance(value.get("name"), str) and value["name"]:
        return value["name"]
    return fallback


def _team_id(value: object) -> str | None:
    return value.get("id") if isinstance(value, dict) and isinstance(value.get("id"), str) else None


def _market_price(observations: object, team_id: str | None) -> str | None:
    if not isinstance(observations, list) or team_id is None:
        return None
    for item in observations:
        if not isinstance(item, dict) or item.get("selection_team_id") != team_id:
            continue
        price = item.get("price")
        return str(price) if price is not None else None
    return None
