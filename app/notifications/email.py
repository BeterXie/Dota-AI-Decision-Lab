from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.jobs import JobType
from app.domain.snapshot import DecisionSnapshot
from app.jobs.repository import JobRepository
from app.models import AiDecisionRecord, DecisionEmailNotificationRecord
from app.providers.common import create_system_ssl_context
from app.snapshots.repository import SnapshotRepository

EMAIL_TEMPLATE_VERSION = "decision-email-v2"


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    sender: str
    recipients: tuple[str, ...]
    subject: str
    text_body: str
    html_body: str
    idempotency_key: str


class EmailSender(Protocol):
    async def send(self, message: OutgoingEmail) -> str: ...

    async def close(self) -> None: ...


class ResendEmailSender:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Dota-AI-Decision-Lab",
            },
        )

    async def send(self, message: OutgoingEmail) -> str:
        response = await self._client.post(
            "/emails",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Idempotency-Key": message.idempotency_key,
            },
            json={
                "from": message.sender,
                "to": list(message.recipients),
                "subject": message.subject,
                "text": message.text_body,
                "html": message.html_body,
            },
        )
        response.raise_for_status()
        payload = response.json()
        provider_message_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(provider_message_id, str) or not provider_message_id:
            raise ValueError("Resend response is missing the email id")
        return provider_message_id

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class DecisionEmailNotificationService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        jobs: JobRepository,
        sender: EmailSender,
        sender_from: str,
        recipients: tuple[str, ...],
        subject_prefix: str,
        max_decision_age_seconds: float = 600.0,
    ) -> None:
        self._session_factory = session_factory
        self._jobs = jobs
        self._sender = sender
        self._sender_from = sender_from
        self._recipients = recipients
        self._subject_prefix = subject_prefix
        self._max_decision_age_seconds = max_decision_age_seconds

    async def prepare(
        self,
        session: AsyncSession,
        *,
        snapshot: DecisionSnapshot,
        decisions: list[AiDecisionRecord],
    ) -> UUID | None:
        age = (datetime.now(UTC) - _as_utc(snapshot.decision_at)).total_seconds()
        if age > self._max_decision_age_seconds:
            return None

        decision_batch_key = _decision_batch_key(decisions)
        existing = await session.scalar(
            select(DecisionEmailNotificationRecord).where(
                DecisionEmailNotificationRecord.snapshot_id == snapshot.snapshot_id,
                DecisionEmailNotificationRecord.decision_batch_key == decision_batch_key,
            )
        )
        if existing is not None:
            notification = existing
        else:
            notification_id = uuid4()
            subject, text_body, html_body = render_decision_email(
                snapshot,
                decisions,
                subject_prefix=self._subject_prefix,
            )
            notification = DecisionEmailNotificationRecord(
                id=notification_id,
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                decision_batch_key=decision_batch_key,
                sender=self._sender_from,
                recipients=list(self._recipients),
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                template_version=EMAIL_TEMPLATE_VERSION,
                idempotency_key=f"decision-email/{notification_id}",
                translation_status="DISABLED",
                status="PENDING",
            )
            session.add(notification)
            await session.flush()
        if notification.status != "SENT" and notification.status != "EXPIRED":
            await self._jobs.enqueue(
                session,
                job_type=JobType.SEND_DECISION_EMAIL,
                dedupe_key=f"decision-email:{notification.id}",
                payload={"notification_id": str(notification.id)},
            )
        return notification.id

    async def deliver(self, notification_id: UUID) -> DecisionEmailNotificationRecord:
        async with self._session_factory() as session:
            notification = await session.get(DecisionEmailNotificationRecord, notification_id)
            if notification is None:
                raise ValueError("decision email notification does not exist")
            if notification.status in {"SENT", "EXPIRED"}:
                return notification
            snapshot = await SnapshotRepository().get(session, notification.snapshot_id)
            if snapshot is not None:
                age = (datetime.now(UTC) - _as_utc(snapshot.decision_at)).total_seconds()
                if age > self._max_decision_age_seconds:
                    async with self._session_factory() as update_session, update_session.begin():
                        record = await update_session.get(
                            DecisionEmailNotificationRecord, notification_id
                        )
                        if record is not None:
                            record.status = "EXPIRED"
                            record.last_error = (
                                f"Decision snapshot is stale "
                                f"({age:.0f}s > {self._max_decision_age_seconds:.0f}s)"
                            )
                            return record

        async with self._session_factory() as session, session.begin():
            notification = await session.get(DecisionEmailNotificationRecord, notification_id)
            if notification is None:
                raise ValueError("decision email notification does not exist")
            if notification.status in {"SENT", "EXPIRED"}:
                return notification
            notification.status = "SENDING"
            notification.attempt_count += 1
            notification.last_attempt_at = datetime.now(UTC)
            notification.last_error = None
            message = OutgoingEmail(
                sender=notification.sender,
                recipients=tuple(notification.recipients),
                subject=notification.subject,
                text_body=notification.text_body,
                html_body=notification.html_body,
                idempotency_key=notification.idempotency_key,
            )
        try:
            provider_message_id = await self._sender.send(message)
        except Exception as exc:
            async with self._session_factory() as session, session.begin():
                failed = await session.get(DecisionEmailNotificationRecord, notification_id)
                if failed is not None:
                    failed.status = "FAILED"
                    failed.last_error = f"{type(exc).__name__}: {exc}"
            raise
        async with self._session_factory() as session, session.begin():
            sent = await session.get(DecisionEmailNotificationRecord, notification_id)
            if sent is None:
                raise ValueError("decision email notification disappeared after send")
            sent.status = "SENT"
            sent.sent_at = datetime.now(UTC)
            sent.provider_message_id = provider_message_id
            sent.last_error = None
            return sent

    async def close(self) -> None:
        await self._sender.close()


def render_decision_email(
    snapshot: DecisionSnapshot,
    decisions: list[AiDecisionRecord],
    *,
    subject_prefix: str,
    translations: dict[str, dict] | None = None,
    translation_status: str = "DISABLED",
) -> tuple[str, str, str]:
    identity = snapshot.identity
    team_a = _team_name(identity.get("team_a"), "Team A")
    team_b = _team_name(identity.get("team_b"), "Team B")
    conclusions = _email_conclusions(decisions, team_a=team_a, team_b=team_b)
    subject = (
        f"{subject_prefix} {conclusions} | "
        f"{team_a} vs {team_b} | {_mode_label(snapshot.mode.value)}"
    )
    market = snapshot.market
    live = snapshot.live
    quality = snapshot.quality
    draft = snapshot.draft
    history = snapshot.history
    observations = market.get("observations") if isinstance(market, dict) else None
    observation_rows = observations if isinstance(observations, list) else []
    price_by_team = {
        item.get("selection_team_id"): item for item in observation_rows if isinstance(item, dict)
    }
    team_a_id = _team_id(identity.get("team_a"))
    team_b_id = _team_id(identity.get("team_b"))
    price_a = price_by_team.get(team_a_id)
    price_b = price_by_team.get(team_b_id)

    text_lines = [
        "Dota AI Decision Lab - 比赛决策通知",
        "",
        f"对阵：{team_a} vs {team_b}",
        f"局数：第 {_display(identity.get('map_number'))} 局",
        f"分析阶段：{_mode_label(snapshot.mode.value)}",
        f"分析时间：{_format_datetime(snapshot.decision_at)}",
        "",
        "当前赔率",
        f"- {team_a}: {_market_line(price_a)}",
        f"- {team_b}: {_market_line(price_b)}",
        "",
        "实时赛况",
        f"- 比赛时间：{_game_time(_value(live, 'game_time_seconds'))}",
        f"- 击杀比分（天辉-夜魇）：{_score(live)}",
        f"- 经济情况：{_networth_lead(_value(live, 'radiant_nw_lead'))}",
        f"- 一血：{_side_label(_value(live, 'first_blood'))}",
        "",
        "双方阵容",
        f"- {_draft_lineup(draft)}",
        f"- 阵容强势期：{_draft_curve_summary(draft)}",
        "",
        "历史表现参考",
        f"- {team_a}：{_team_history_summary(_value(history, 'team_a'))}",
        f"- {team_b}：{_team_history_summary(_value(history, 'team_b'))}",
        f"- 数据覆盖：{_history_coverage(_value(history, 'coverage'))}",
        "",
        "数据可靠性",
        f"- 无法判断的原因：{_quality_list(quality.get('blockers'))}",
        f"- 需要注意：{_quality_list(quality.get('warnings'))}",
        f"- 赔率与比赛画面同步状态：{_sync_label(_value(quality.get('live_sync'), 'status'))}",
        "",
        "各 AI 的判断",
    ]
    for decision in sorted(decisions, key=lambda item: (item.provider, item.model)):
        normalized = decision.normalized_response or {}
        translated = (translations or {}).get(str(decision.id), {})
        text_lines.extend(
            [
                "",
                f"[{decision.provider.upper()} / {decision.model}]",
                f"结论：{_action_label(normalized.get('action'), team_a, team_b)}",
                f"AI估计 {team_a} 胜率：{_percent(normalized.get('fair_probability_a'))}",
                f"信心：{_percent(normalized.get('confidence'))}",
                f"对当前赔率的看法：{_assessment_label(normalized.get('market_assessment'))}",
                f"认为 {team_a} 至少需要达到的赔率："
                f"{_display(normalized.get('minimum_acceptable_odds_a'))}",
                f"虚拟下注：{_display(normalized.get('stake'))}",
                f"可用虚拟资金：{_display(decision.bankroll_before)}",
                f"主要理由：{_translated_list(translated, normalized, 'primary_reasons')}",
                f"无法给出结论的原因：{_translated_list(translated, normalized, 'blockers')}",
                f"模型状态：{_parse_status_label(decision.parse_status)}",
            ]
        )
    if translation_status == "FAILED":
        text_lines.extend(["", "说明：中文翻译暂时不可用，AI理由保留原文。"])
    text_lines.extend(
        [
            "",
            "技术信息",
            f"- Valve 比赛 ID：{_display(identity.get('valve_match_id'))}",
            f"- 决策快照：{snapshot.snapshot_hash}",
        ]
    )
    text_body = "\n".join(text_lines)

    market_rows = "".join(
        _html_row(name, _market_line(item)) for name, item in ((team_a, price_a), (team_b, price_b))
    )
    decision_sections = "".join(
        _decision_html(
            item,
            team_a=team_a,
            team_b=team_b,
            translated=(translations or {}).get(str(item.id), {}),
        )
        for item in decisions
    )
    translation_notice = (
        '<p style="color:#8a3b12">中文翻译暂时不可用，AI理由保留原文。</p>'
        if translation_status == "FAILED"
        else ""
    )
    header_meta = (
        f"{escape(_mode_label(snapshot.mode.value))} · "
        f"{escape(_format_datetime(snapshot.decision_at))}"
    )
    html_body = f"""<!doctype html>
<html lang="zh-CN">
<body style="margin:0;background:#f4f4f4;color:#161616;font-family:Arial,sans-serif">
<div style="max-width:760px;margin:0 auto;background:#ffffff">
<div style="padding:24px;background:#161616;color:#ffffff">
<div style="font-size:13px;color:#a8a8a8">Dota AI Decision Lab · 比赛决策通知</div>
<h1 style="margin:8px 0 4px;font-size:24px">{escape(team_a)} vs {escape(team_b)}</h1>
<div>{header_meta}</div>
</div>
<div style="padding:24px">
<h2 style="font-size:18px">比赛信息</h2>
<table style="width:100%;border-collapse:collapse">
{_html_row("局数", f"第 {_display(identity.get('map_number'))} 局")}
{_html_row("分析阶段", _mode_label(snapshot.mode.value))}
{_html_row("分析时间", _format_datetime(snapshot.decision_at))}
</table>
<h2 style="font-size:18px;margin-top:28px">当前赔率</h2>
<table style="width:100%;border-collapse:collapse">{market_rows}</table>
<h2 style="font-size:18px;margin-top:28px">实时赛况</h2>
<table style="width:100%;border-collapse:collapse">
{_html_row("比赛时间", _game_time(_value(live, "game_time_seconds")))}
{_html_row("击杀比分（天辉-夜魇）", _score(live))}
{_html_row("经济情况", _networth_lead(_value(live, "radiant_nw_lead")))}
{_html_row("一血", _side_label(_value(live, "first_blood")))}
</table>
<h2 style="font-size:18px;margin-top:28px">双方阵容</h2>
<table style="width:100%;border-collapse:collapse">
{_html_row("选手与英雄", _draft_lineup(draft))}
{_html_row("阵容强势期", _draft_curve_summary(draft))}
</table>
<h2 style="font-size:18px;margin-top:28px">历史表现参考</h2>
<table style="width:100%;border-collapse:collapse">
{_html_row(team_a, _team_history_summary(_value(history, "team_a")))}
{_html_row(team_b, _team_history_summary(_value(history, "team_b")))}
{_html_row("数据覆盖", _history_coverage(_value(history, "coverage")))}
</table>
<h2 style="font-size:18px;margin-top:28px">数据可靠性</h2>
<table style="width:100%;border-collapse:collapse">
{_html_row("无法判断的原因", _quality_list(quality.get("blockers")))}
{_html_row("需要注意", _quality_list(quality.get("warnings")))}
{_html_row("赔率与赛况同步", _sync_label(_value(quality.get("live_sync"), "status")))}
</table>
<h2 style="font-size:18px;margin-top:28px">各 AI 的判断</h2>
{decision_sections}
{translation_notice}
<h2 style="font-size:16px;margin-top:28px;color:#525252">技术信息</h2>
<table style="width:100%;border-collapse:collapse">
{_html_row("Valve 比赛 ID", _display(identity.get("valve_match_id")))}
{_html_row("决策快照", snapshot.snapshot_hash)}
</table>
</div></div></body></html>"""
    return subject, text_body, html_body


def _decision_html(
    record: AiDecisionRecord,
    *,
    team_a: str,
    team_b: str,
    translated: dict,
) -> str:
    value = record.normalized_response or {}
    rows = (
        ("结论", _action_label(value.get("action"), team_a, team_b)),
        (f"AI估计 {team_a} 胜率", _percent(value.get("fair_probability_a"))),
        ("信心", _percent(value.get("confidence"))),
        ("对当前赔率的看法", _assessment_label(value.get("market_assessment"))),
        (f"{team_a} 最低可接受赔率", _display(value.get("minimum_acceptable_odds_a"))),
        ("虚拟下注", _display(value.get("stake"))),
        ("可用虚拟资金", _display(record.bankroll_before)),
        ("主要理由", _translated_list(translated, value, "primary_reasons")),
        ("无法给出结论的原因", _translated_list(translated, value, "blockers")),
        ("模型状态", _parse_status_label(record.parse_status)),
    )
    return (
        '<section style="border-top:3px solid #0f62fe;margin:16px 0 24px">'
        f'<h3 style="margin:12px 0">{escape(record.provider.upper())} · '
        f"{escape(record.model)}</h3>"
        '<table style="width:100%;border-collapse:collapse">'
        + "".join(_html_row(label, value) for label, value in rows)
        + "</table></section>"
    )


def _decision_batch_key(decisions: list[AiDecisionRecord]) -> str:
    return ",".join(sorted(str(item.id) for item in decisions))


def _email_conclusions(decisions: list[AiDecisionRecord], *, team_a: str, team_b: str) -> str:
    labels = []
    for decision in sorted(decisions, key=lambda item: (item.provider, item.model)):
        normalized = decision.normalized_response if decision.parse_status == "SUCCESS" else None
        action = normalized.get("action") if isinstance(normalized, dict) else None
        label = {
            "BUY_A": f"BUY {team_a}",
            "BUY_B": f"BUY {team_b}",
            "NO_BUY": "NO BUY",
            "INSUFFICIENT_DATA": "INSUFFICIENT DATA",
        }.get(str(action), "AI ERROR")
        if label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else "AI ERROR"


def _team_name(value: object, fallback: str) -> str:
    if isinstance(value, dict) and isinstance(value.get("name"), str) and value["name"]:
        return value["name"]
    return fallback


def _team_id(value: object) -> str | None:
    return value.get("id") if isinstance(value, dict) and isinstance(value.get("id"), str) else None


def _value(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, dict) else None


def _display(value: object) -> str:
    return "暂无可靠数据" if value is None or value == "" else str(value)


def _market_line(value: object) -> str:
    if not isinstance(value, dict):
        return "暂无可靠赔率"
    return (
        f"赔率 {_display(value.get('price'))}；"
        f"去除水位后的参考胜率 {_percent(value.get('fair_probability'))}；"
        f"更新时间 {_display(value.get('received_at'))}"
    )


def _score(live: object) -> str:
    radiant = _value(live, "radiant_kills")
    dire = _value(live, "dire_kills")
    return f"{radiant}-{dire}" if radiant is not None and dire is not None else "暂无可靠数据"


def _draft_lineup(draft: object) -> str:
    slots = _value(draft, "slots")
    if not isinstance(slots, list) or not slots:
        return "阵容尚未完整获取"
    values = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        player = slot.get("player_name") or slot.get("account_id")
        hero = slot.get("hero_name") or slot.get("hero_id")
        values.append(
            f"{_side_label(slot.get('side'))} {slot.get('position')}号位："
            f"{_display(player)} / {_display(hero)}"
        )
    return "；".join(values) if values else "阵容尚未完整获取"


def _draft_curve_summary(draft: object) -> str:
    curve = _value(draft, "curve")
    derived = _value(curve, "derived_features")
    if not isinstance(derived, dict):
        return "阵容曲线尚不可用"
    labels = {
        "current_minute_edge": "当前时间优势",
        "next_5m_average": "未来5分钟平均优势",
        "next_10m_average": "未来10分钟平均优势",
        "peak_minute": "最强势时间",
        "peak_edge": "最大优势",
        "cross_over_minute": "阵容强弱转换时间",
    }
    return "；".join(f"{labels.get(key, key)}：{_display(value)}" for key, value in derived.items())


def _team_history_summary(team: object) -> str:
    if not isinstance(team, dict):
        return "暂无可靠历史数据"
    fields = {
        "base_rating": "队伍基础评分",
        "recent_form": "近期状态",
        "recent_form_confidence": "近期状态可信度",
        "current_roster_strength": "当前阵容实力",
        "roster_stability": "阵容稳定度",
    }
    return "；".join(f"{label}：{_display(team.get(key))}" for key, label in fields.items())


def _history_coverage(coverage: object) -> str:
    if not isinstance(coverage, dict):
        return "暂无可靠历史数据"
    labels = {
        "team_strength_ready_count": "有队伍实力数据",
        "roster_player_count": "已识别选手",
        "player_form_ready_count": "有近期状态的选手",
        "player_hero_ready_count": "有当前英雄经验的选手",
    }
    return "；".join(
        f"{labels.get(key, key)}：{_display(value)}" for key, value in coverage.items()
    )


def _game_time(value: object) -> str:
    if not isinstance(value, int):
        return "暂无可靠数据"
    return f"{value // 60:02d}:{value % 60:02d}"


def _signed(value: object) -> str:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return "暂无可靠数据"
    return f"{value:+}"


def _percent(value: object) -> str:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return "暂无可靠数据"
    return f"{float(value) * 100:.1f}%"


def _list_text(value: object) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        return "无"
    return "；".join(str(item) for item in value)


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _format_datetime(value: datetime) -> str:
    return value.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S (北京时间)")


def _mode_label(value: str) -> str:
    return {
        "PREMATCH": "赛前分析",
        "POST_DRAFT": "阵容确定后分析",
        "LIVE_BASIC": "比赛中实时分析",
        "LIVE_FULL": "比赛中完整实时分析",
    }.get(value, value)


def _action_label(value: object, team_a: str, team_b: str) -> str:
    return {
        "BUY_A": f"支持 {team_a}",
        "BUY_B": f"支持 {team_b}",
        "NO_BUY": "暂不参与",
        "INSUFFICIENT_DATA": "数据不足，无法判断",
    }.get(str(value), "模型未给出有效结论")


def _assessment_label(value: object) -> str:
    return {
        "UNDERPRICED": "赔率偏高，可能有价值",
        "FAIR": "赔率基本合理",
        "OVERPRICED": "赔率偏低，价值不足",
        "UNKNOWN": "暂时无法判断",
    }.get(str(value), "暂时无法判断")


def _parse_status_label(value: str) -> str:
    return {
        "SUCCESS": "回答有效",
        "PARSE_FAILED": "回答格式异常",
        "FAILED": "模型调用失败",
        "REFUSED": "模型拒绝回答",
    }.get(value, value)


def _side_label(value: object) -> str:
    return {
        "radiant": "天辉",
        "dire": "夜魇",
        "Radiant": "天辉",
        "Dire": "夜魇",
    }.get(str(value), _display(value))


def _networth_lead(value: object) -> str:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return "暂无可靠数据"
    if value == 0:
        return "双方经济持平"
    side = "天辉" if value > 0 else "夜魇"
    return f"{side} 领先 {abs(value):,.0f} 金币"


def _sync_label(value: object) -> str:
    return {
        "SAFE": "同步良好，可用于实时判断",
        "CAUTION": "可能存在时间差，需要谨慎",
        "UNSAFE": "时间差过大，不用于实时判断",
        "CALIBRATING": "正在校准时间差",
        "UNKNOWN": "样本不足，暂时无法确认",
    }.get(str(value), "样本不足，暂时无法确认")


def _quality_list(value: object) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        return "无"
    return "；".join(_quality_label(str(item)) for item in value)


def _quality_label(value: str) -> str:
    labels = {
        "MARKET_MISSING": "缺少可用赔率",
        "MARKET_STALE": "赔率更新时间过旧",
        "MARKET_STATUS_UNKNOWN": "盘口状态尚未确认",
        "DRAFT_PARTIAL": "双方英雄阵容尚未完整获取",
        "LIVE_PARTIAL": "实时比赛数据不完整",
        "LIVE_STALE": "实时比赛数据已过期",
        "LIVE_SYNC_UNKNOWN": "赔率与比赛数据的时间差尚未确认",
        "LIVE_DATA_DESYNC": "赔率与比赛数据不同步",
        "LIVE_SYNC_CAUTION": "赔率与比赛数据可能存在时间差",
        "HISTORICAL_TEAM_STRENGTH_MISSING": "缺少队伍历史实力数据",
        "ROSTER_IDENTITY_AMBIGUOUS": "当前上场选手身份无法确认",
    }
    return f"{labels.get(value, value)}（{value}）"


def _translated_list(translated: dict, original: dict, key: str) -> str:
    value = translated.get(key)
    if not isinstance(value, list):
        value = original.get(key)
    return _list_text(value)


def _html_row(label: str, value: object) -> str:
    return (
        '<tr><th style="text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid '
        f'#e0e0e0;width:34%">{escape(label)}</th><td style="padding:8px;border-bottom:1px '
        f'solid #e0e0e0">{escape(str(value))}</td></tr>'
    )
