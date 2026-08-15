import asyncio
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.domain.jobs import JobType
from app.domain.snapshot import DecisionSnapshot
from app.jobs.repository import JobRepository
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
)
from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.models import (
    MESSAGE_TYPE_USER,
    WeChatAccount,
    WeChatInboundMessage,
)
from app.providers.wechat_clawbot.storage import WeChatClawBotStore
from app.runtime.health import HealthRegistry

logger = structlog.get_logger()


class WeChatClawBotService:
    """Official WeChat ClawBot channel wired directly into the harness.

    No OpenClaw runtime is involved: the service talks to Tencent's iLink bot
    HTTP API, persists the QR-confirmed credentials locally, long-polls inbound
    direct chats, and pushes decision notifications.
    """

    def __init__(
        self,
        *,
        client: WeChatClawBotClient,
        store: WeChatClawBotStore,
        session_factory: async_sessionmaker[AsyncSession],
        jobs: JobRepository,
        health: HealthRegistry | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._session_factory = session_factory
        self._jobs = jobs
        self._health = health
        self._stop = asyncio.Event()
        self._inbound_task: asyncio.Task | None = None
        self._closed = False

    @property
    def client(self) -> WeChatClawBotClient:
        return self._client

    @property
    def store(self) -> WeChatClawBotStore:
        return self._store

    async def prepare_decision_notification(
        self,
        session: AsyncSession,
        *,
        snapshot: DecisionSnapshot,
        decisions: list[AiDecisionRecord],
    ) -> None:
        if not self._store.accounts():
            return
        decision_ids = ",".join(sorted(str(item.id) for item in decisions))
        await self._jobs.enqueue(
            session,
            job_type=JobType.SEND_WECHAT_DECISION,
            dedupe_key=f"wechat-decision:{snapshot.snapshot_id}:{decision_ids}",
            payload={
                "snapshot_id": str(snapshot.snapshot_id),
                "decision_ids": [str(item.id) for item in decisions],
            },
            priority=50,
            max_attempts=6,
        )

    async def send_decision_notification(
        self,
        *,
        snapshot: DecisionSnapshot,
        decisions: list[AiDecisionRecord],
    ) -> int:
        if not self._store.decision_notifications_enabled():
            return 0
        accounts = list(self._store.accounts())
        if not accounts:
            return 0
        text = _render_decision_notification(snapshot, decisions)
        sent = 0
        for account in accounts:
            if not account.user_id:
                continue
            await self._client.send_text(
                account,
                to_user_id=account.user_id,
                text=text,
                context_token=account.context_token,
            )
            sent += 1
        return sent

    async def send_to_account(self, account: WeChatAccount, text: str) -> str:
        if not account.user_id:
            raise ValueError("WeChat account has no bound user id yet")
        return await self._client.send_text(
            account,
            to_user_id=account.user_id,
            text=text,
            context_token=account.context_token,
        )

    async def run_inbound(self) -> None:
        self._stop.clear()
        backoff = 1.0
        while not self._stop.is_set():
            accounts = list(self._store.accounts())
            if not accounts:
                await self._update_health(
                    "ACTION_REQUIRED", message="no bound WeChat ClawBot account"
                )
                await self._sleep(15)
                continue
            for account in accounts:
                if self._stop.is_set():
                    break
                try:
                    cursor = self._store.cursor(account.account_id)
                    batch = await self._client.get_updates(account, cursor)
                    logger.debug(
                        "wechat_clawbot_poll",
                        account_id=account.account_id,
                        cursor_len=len(cursor),
                        messages=len(batch.messages),
                        error_code=batch.error_code,
                    )
                    if batch.error_code in {None, 0}:
                        if batch.cursor:
                            self._store.save_cursor(account.account_id, batch.cursor)
                        async with self._session_factory() as session, session.begin():
                            for message in batch.messages:
                                if message.message_type != MESSAGE_TYPE_USER:
                                    continue
                                await self._handle_message(session, account, message)
                    await self._update_health(
                        "READY",
                        messages=len(batch.messages),
                        account_id=account.account_id,
                    )
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self._update_health("DEGRADED", message=f"{type(exc).__name__}: {exc}")
                    await self._sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    if self._stop.is_set():
                        break
            await self._sleep(0.5)

    def start_inbound(self) -> asyncio.Task:
        if self._inbound_task is None or self._inbound_task.done():
            self._inbound_task = asyncio.create_task(self.run_inbound())
        return self._inbound_task

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._inbound_task is not None:
            self._inbound_task.cancel()
            try:
                await self._inbound_task
            except asyncio.CancelledError:
                pass
        await self._client.close()

    async def _handle_message(
        self,
        session: AsyncSession,
        account: WeChatAccount,
        message: WeChatInboundMessage,
    ) -> None:
        if not message.from_user_id:
            return
        reply = await _command_reply(session, self._store, message.text)
        await self._client.send_text(
            account,
            to_user_id=message.from_user_id,
            text=reply,
            context_token=message.context_token,
            run_id=message.run_id,
        )
        updates: dict[str, object] = {}
        if not account.user_id:
            updates["user_id"] = message.from_user_id
        if message.context_token and message.context_token != account.context_token:
            updates["context_token"] = message.context_token
        if updates:
            self._store.save_account(account.model_copy(update=updates))

    async def _update_health(
        self, status: str, *, message: str | None = None, **metadata: Any
    ) -> None:
        if self._health is None:
            return
        await self._health.dependency("WECHAT", status, message=message, **metadata)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            pass


def _render_decision_notification(
    snapshot: DecisionSnapshot, decisions: list[AiDecisionRecord]
) -> str:
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
        "🎯 Dota AI Decision Lab",
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
        probability = normalized.get("fair_probability_a")
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


async def _command_reply(
    session: AsyncSession,
    store: WeChatClawBotStore,
    text: str,
) -> str:
    normalized = text.strip().casefold()
    if not normalized:
        return _help()
    if "当前比赛" in normalized or normalized in {"matches", "比赛"}:
        return await _matches_reply(session)
    if "暂停" in normalized and "通知" in normalized:
        store.set_decision_notifications(False)
        return "✅ 已暂停 AI 决策微信通知。发送「恢复通知」重新开启。"
    if ("恢复" in normalized or "开启" in normalized) and "通知" in normalized:
        store.set_decision_notifications(True)
        return "✅ 已恢复 AI 决策微信通知。"
    if "为什么" in normalized or "buy" in normalized:
        return await _decision_reply(session, text)
    if normalized in {"帮助", "help", "?"}:
        return _help()
    return _help()


async def _matches_reply(session: AsyncSession) -> str:
    team_a_alias = aliased(CanonicalTeam)
    team_b_alias = aliased(CanonicalTeam)
    maps = list(
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
                .join(
                    DltvLiveObservationRecord,
                    DltvLiveObservationRecord.canonical_map_id == CanonicalMap.id,
                )
                .where(CanonicalMap.valve_match_id.is_not(None))
                .order_by(DltvLiveObservationRecord.received_at.desc())
                .limit(5)
            )
        ).all()
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


async def _decision_reply(session: AsyncSession, query: str) -> str:
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
        probability = normalized.get("fair_probability_a")
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
        lines.append(f"  决策时间: {item['decision_at'].astimezone().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def _help() -> str:
    return "\n".join(
        [
            "Dota AI Decision Lab 微信指令:",
            "▪ 当前比赛 — 查看正在追踪的比赛",
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
