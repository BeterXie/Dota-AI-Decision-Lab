import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DltvLiveObservationRecord,
    DurableJobRecord,
    MapResultRecord,
    OddsObservationRecord,
)
from app.providers.chat_commands import (
    command_reply,
    decision_reply,
    help_text,
    matches_reply,
    odds_reply,
    render_decision_notification,
)
from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.models import WeChatAccount
from app.providers.wechat_clawbot.service import WeChatClawBotService
from app.providers.wechat_clawbot.storage import WeChatClawBotStore
from app.snapshots.repository import SnapshotRepository


def _account(tmp_path: Path, *, user_id: str = "wechat-user-1") -> WeChatAccount:
    return WeChatAccount(
        account_id="bot-1@im.bot",
        token="bot-token",
        base_url="https://ilinkai.weixin.qq.com",
        user_id=user_id,
        created_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_client_send_text_matches_official_protocol() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ret": 0, "errmsg": ""})

    client = WeChatClawBotClient(
        client=httpx.AsyncClient(
            base_url="https://ilinkai.weixin.qq.com",
            transport=httpx.MockTransport(handler),
        ),
        bot_agent="Dota-AI-Decision-Lab/0.1.0",
    )
    account = _account(Path("unused"))

    message_id = await client.send_text(account, to_user_id="wechat-user-1", text="hi")

    assert message_id.startswith("dota-ai-")
    assert captured["url"] == "https://ilinkai.weixin.qq.com/ilink/bot/sendmessage"
    headers = {key.casefold(): value for key, value in captured["headers"].items()}
    assert headers["authorizationtype"] == "ilink_bot_token"
    assert headers["authorization"] == "Bearer bot-token"
    assert headers["ilink-app-id"] == "bot"
    assert captured["body"]["msg"]["to_user_id"] == "wechat-user-1"
    assert captured["body"]["msg"]["message_type"] == 2
    assert captured["body"]["msg"]["item_list"][0]["text_item"]["text"] == "hi"
    assert captured["body"]["base_info"]["bot_agent"] == "Dota-AI-Decision-Lab/0.1.0"
    await client.close()


@pytest.mark.asyncio
async def test_client_get_updates_parses_text_and_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/notifystart"):
            return httpx.Response(200, json={"ret": 0})
        body = json.loads(request.content)
        assert body["get_updates_buf"] == "cursor-a"
        return httpx.Response(
            200,
            json={
                "ret": 0,
                "msgs": [
                    {
                        "message_type": 1,
                        "from_user_id": "wechat-user-1",
                        "context_token": "ctx-1",
                        "item_list": [
                            {"type": 1, "text_item": {"text": "当前比赛"}},
                            {"type": 2, "text_item": {"text": "ignored bot echo"}},
                        ],
                    }
                ],
                "get_updates_buf": "cursor-b",
            },
        )

    client = WeChatClawBotClient(
        client=httpx.AsyncClient(
            base_url="https://ilinkai.weixin.qq.com",
            transport=httpx.MockTransport(handler),
        )
    )
    batch = await client.get_updates(_account(Path("unused")), "cursor-a")

    assert batch.cursor == "cursor-b"
    assert len(batch.messages) == 1
    assert batch.messages[0].text == "当前比赛"
    assert batch.messages[0].from_user_id == "wechat-user-1"
    await client.close()


def test_store_persists_account_cursor_and_preferences(tmp_path: Path) -> None:
    store = WeChatClawBotStore(tmp_path)
    account = _account(tmp_path)

    store.save_account(account)
    assert store.account_count() == 1
    assert store.accounts()[0].token == "bot-token"
    assert store.cursor(account.account_id) == ""

    store.save_cursor(account.account_id, "cursor-1")
    assert store.cursor(account.account_id) == "cursor-1"

    store.set_decision_notifications(False)
    assert store.decision_notifications_enabled() is False

    store.remove_account(account.account_id)
    assert store.account_count() == 0
    assert store.cursor(account.account_id) == ""


@pytest.mark.asyncio
async def test_service_prepare_notification_is_idempotent(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    store = WeChatClawBotStore(tmp_path)
    store.save_account(_account(tmp_path))
    client = WeChatClawBotClient(
        client=httpx.AsyncClient(
            base_url="https://ilinkai.weixin.qq.com",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ret": 0})),
        )
    )
    service = WeChatClawBotService(
        client=client,
        store=store,
        session_factory=factory,
        jobs=jobs,
        max_decision_age_seconds=10**9,
    )
    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "OG"},
                "team_b": {"id": "team-b", "name": "HULIGANI"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        decision = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="ai-view-v2",
            request_started_at=snapshot.decision_at,
            response_received_at=snapshot.decision_at,
            latency_seconds=1.0,
            raw_response={},
            normalized_response={
                "action": "BUY_A",
                "fair_probability_a": 0.61,
                "market_assessment": "UNDERPRICED",
                "minimum_acceptable_odds_a": 1.75,
                "primary_reasons": ["阵容优势"],
                "counter_arguments": [],
                "data_quality_concerns": [],
                "blockers": [],
            },
            parse_status="SUCCESS",
        )
        session.add(decision)
        await session.flush()
        await service.prepare_decision_notification(
            session,
            snapshot=snapshot,
            decisions=[decision],
        )
        await service.prepare_decision_notification(
            session,
            snapshot=snapshot,
            decisions=[decision],
        )

    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SEND_WECHAT_DECISION.value)
        )
    assert count == 1
    await service.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_renders_and_sends_decision_notification(tmp_path: Path) -> None:
    store = WeChatClawBotStore(tmp_path)
    account = _account(tmp_path)
    store.save_account(account)

    sent: list[tuple[str, str]] = []

    class RecordingClient:
        async def send_text(
            self,
            account: WeChatAccount,
            *,
            to_user_id: str,
            text: str,
            context_token: str | None = None,
            run_id: str | None = None,
            idempotency_key: str | None = None,
        ) -> str:

            sent.append((to_user_id, text))
            return "client-id"

        async def close(self) -> None:
            return None

    service = WeChatClawBotService(
        client=RecordingClient(),
        store=store,
        session_factory=None,
        jobs=JobRepository(),
        max_decision_age_seconds=10**9,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "OG"},
                "team_b": {"id": "team-b", "name": "HULIGANI"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        decision = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="ai-view-v2",
            request_started_at=snapshot.decision_at,
            response_received_at=snapshot.decision_at,
            latency_seconds=1.0,
            raw_response={},
            normalized_response={
                "action": "BUY_B",
                "fair_probability_a": 0.35,
                "market_assessment": "UNDERPRICED",
                "minimum_acceptable_odds_a": 1.75,
                "primary_reasons": ["阵容优势"],
                "counter_arguments": [],
                "data_quality_concerns": [],
                "blockers": [],
            },
            parse_status="SUCCESS",
        )
        count = await service.send_decision_notification(snapshot=snapshot, decisions=[decision])
        assert count == 1
        assert sent[0][0] == "wechat-user-1"
        assert "OG" in sent[0][1]
        assert "支持 HULIGANI" in sent[0][1]
        # assert "AI胜率: 65.0%" in sent[0][1]
        assert "阵容优势" in sent[0][1]
    await engine.dispose()


@pytest.mark.asyncio
async def test_command_pause_resume_toggles_notifications(tmp_path: Path) -> None:
    store = WeChatClawBotStore(tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        reply = await command_reply(session, store, "暂停通知", channel_label="微信")
        assert "已暂停" in reply
        assert store.decision_notifications_enabled() is False
        reply = await command_reply(session, store, "恢复通知", channel_label="微信")
        assert "已恢复" in reply
        assert store.decision_notifications_enabled() is True
    await engine.dispose()


def test_decision_notification_render_uses_target_probability_for_buy_b() -> None:
    from app.domain.snapshot import DecisionMode, DecisionSnapshot

    snapshot = DecisionSnapshot(
        snapshot_id=uuid4(),
        decision_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        mode=DecisionMode.LIVE_BASIC,
        identity={
            "team_a": {"id": "team-a", "name": "OG"},
            "team_b": {"id": "team-b", "name": "HULIGANI"},
        },
        market={},
        draft=None,
        history={},
        live=None,
        quality={},
        snapshot_hash="fixture-hash",
    )
    decision = AiDecisionRecord(
        id=uuid4(),
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        provider="openai",
        model="gpt-test",
        model_version="gpt-test",
        prompt_version="prompt-v1",
        decision_policy_version="policy-v1",
        ai_view_version="ai-view-v2",
        request_started_at=snapshot.decision_at,
        parse_status="SUCCESS",
        normalized_response={
            "action": "BUY_B",
            "fair_probability_a": 0.35,
            "market_assessment": "UNDERPRICED",
            "minimum_acceptable_odds_a": None,
            "primary_reasons": ["阵容优势"],
            "counter_arguments": [],
            "data_quality_concerns": [],
            "blockers": [],
        },
    )

    text = render_decision_notification(snapshot, [decision])

    assert "支持 HULIGANI" in text
    assert "AI胜率: 65.0%" in text
    assert "AI胜率: 35.0%" not in text


@pytest.mark.asyncio
async def test_client_id_is_stable_when_idempotency_key_is_provided() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"ret": 0, "errmsg": ""})

    client = WeChatClawBotClient(
        client=httpx.AsyncClient(
            base_url="https://ilinkai.weixin.qq.com",
            transport=httpx.MockTransport(handler),
        )
    )
    account = _account(Path("unused"))

    first = await client.send_text(
        account,
        to_user_id=account.user_id or "",
        text="stable",
        idempotency_key="wechat-decision:snapshot:batch:bot-1@im.bot",
    )
    second = await client.send_text(
        account,
        to_user_id=account.user_id or "",
        text="stable",
        idempotency_key="wechat-decision:snapshot:batch:bot-1@im.bot",
    )

    assert first == second
    assert first.startswith("dota-ai-")
    assert captured[0]["msg"]["client_id"] == first
    assert captured[1]["msg"]["client_id"] == first
    await client.close()


@pytest.mark.asyncio
async def test_decision_reply_uses_target_probability_for_buy_b() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "OG"},
                "team_b": {"id": "team-b", "name": "HULIGANI"},
            },
            market={},
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        session.add(
            AiDecisionRecord(
                id=uuid4(),
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                provider="openai",
                model="gpt-test",
                model_version="gpt-test",
                prompt_version="prompt-v1",
                decision_policy_version="policy-v1",
                ai_view_version="ai-view-v2",
                request_started_at=now,
                parse_status="SUCCESS",
                normalized_response={
                    "action": "BUY_B",
                    "fair_probability_a": 0.35,
                    "market_assessment": "UNDERPRICED",
                    "minimum_acceptable_odds_a": None,
                    "primary_reasons": ["下路优势"],
                    "counter_arguments": [],
                    "data_quality_concerns": [],
                    "blockers": [],
                },
            )
        )
        reply = await decision_reply(session, "为什么买 HULIGANI")

    assert "支持 HULIGANI" in reply
    assert "AI胜率 65.0%" in reply
    assert "AI胜率 35.0%" not in reply
    await engine.dispose()


@pytest.mark.asyncio
async def test_matches_reply_deduplicates_by_map_and_filters_result_and_stale() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="OG")
        team_b = CanonicalTeam(name="HULIGANI")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()

        active = CanonicalMap(series_id=series.id, map_number=1, valve_match_id=101)
        finished = CanonicalMap(series_id=series.id, map_number=2, valve_match_id=102)
        stale = CanonicalMap(series_id=series.id, map_number=3, valve_match_id=103)
        session.add_all((active, finished, stale))
        await session.flush()

        def live_row(canonical_map_id, received_at, kills):
            return DltvLiveObservationRecord(
                canonical_map_id=canonical_map_id,
                valve_match_id=101,
                game_time_seconds=600,
                radiant_kills=kills,
                dire_kills=kills - 1,
                received_at=received_at,
                payload_hash=f"live-{canonical_map_id}-{received_at.isoformat()}",
                last_message_received_at=received_at,
                last_state_change_received_at=received_at,
                raw_event_id=uuid4(),
            )

        for offset, kills in ((3, 10), (2, 11), (1, 12)):
            session.add(live_row(active.id, now - timedelta(seconds=offset), kills))
        for offset in (5, 4):
            session.add(live_row(finished.id, now - timedelta(seconds=offset), 5))
        session.add(live_row(stale.id, now - timedelta(minutes=10), 3))
        session.add(
            MapResultRecord(
                canonical_map_id=finished.id,
                winner_team_id=team_a.id,
                basic_first_usable_at=now,
                settled_at=now,
            )
        )

        reply = await matches_reply(session, live_state_max_age_seconds=120.0)

    assert "第1局" in reply
    assert "第2局" not in reply
    assert "第3局" not in reply
    assert reply.count("OG vs HULIGANI") == 1
    assert "击杀 12-11" in reply
    await engine.dispose()


@pytest.mark.asyncio
async def test_odds_reply_reports_both_sides_for_current_live_map() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="OG")
        team_b = CanonicalTeam(name="HULIGANI")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()

        active = CanonicalMap(series_id=series.id, map_number=1, valve_match_id=101)
        finished = CanonicalMap(series_id=series.id, map_number=2, valve_match_id=102)
        incomplete = CanonicalMap(series_id=series.id, map_number=3, valve_match_id=103)
        session.add_all((active, finished, incomplete))
        await session.flush()

        def live_row(canonical_map_id, valve_match_id, received_at):
            return DltvLiveObservationRecord(
                canonical_map_id=canonical_map_id,
                valve_match_id=valve_match_id,
                game_time_seconds=600,
                radiant_kills=10,
                dire_kills=8,
                received_at=received_at,
                payload_hash=f"live-{canonical_map_id}-{received_at.isoformat()}",
                last_message_received_at=received_at,
                last_state_change_received_at=received_at,
                raw_event_id=uuid4(),
            )

        session.add_all(
            (
                live_row(active.id, 101, now - timedelta(seconds=5)),
                live_row(finished.id, 102, now - timedelta(seconds=5)),
                live_row(incomplete.id, 103, now - timedelta(seconds=5)),
            )
        )
        session.add(
            MapResultRecord(
                canonical_map_id=finished.id,
                winner_team_id=team_a.id,
                basic_first_usable_at=now,
                settled_at=now,
            )
        )

        def odds_row(odds_id, selection_team_id, price, received_at):
            return OddsObservationRecord(
                provider="raybet",
                provider_match_id=777,
                odds_id=odds_id,
                canonical_series_id=series.id,
                canonical_map_id=active.id,
                market_type="Winner",
                match_stage="r1",
                selection_team_id=selection_team_id,
                price=price,
                implied_probability=float(1 / price),
                raw_status=1,
                normalized_status="OPEN_CONFIRMED",
                metadata_version="raybet-v1",
                provider_updated_at=received_at,
                received_at=received_at,
                raw_event_id=uuid4(),
            )

        session.add_all(
            (
                odds_row(101, team_a.id, Decimal("1.80"), now - timedelta(seconds=5)),
                odds_row(102, team_b.id, Decimal("2.05"), now - timedelta(seconds=5)),
            )
        )
        await session.flush()

        # A map with only one leg must degrade to "no odds" instead of
        # showing a single-sided price as if it were a valid pair.
        incomplete_odds = OddsObservationRecord(
            provider="raybet",
            provider_match_id=778,
            odds_id=301,
            canonical_series_id=series.id,
            canonical_map_id=incomplete.id,
            market_type="Winner",
            match_stage="r3",
            selection_team_id=team_a.id,
            price=Decimal("1.75"),
            implied_probability=1 / 1.75,
            raw_status=1,
            normalized_status="OPEN_CONFIRMED",
            metadata_version="raybet-v1",
            provider_updated_at=now - timedelta(seconds=5),
            received_at=now - timedelta(seconds=5),
            raw_event_id=uuid4(),
        )
        session.add(incomplete_odds)

        reply = await odds_reply(session, observed_at=now)

    assert "当前比赛赔率:" in reply
    assert "第1局" in reply
    assert "赔率: OG 1.80 / HULIGANI 2.05" in reply
    assert "更新:" in reply
    assert "第2局" not in reply
    assert "第3局" in reply
    assert "暂无可用赔率" in reply
    await engine.dispose()


@pytest.mark.asyncio
async def test_command_routes_odds_before_matches_and_help_lists_it(tmp_path: Path) -> None:
    store = WeChatClawBotStore(tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        odds_reply = await command_reply(session, store, "当前比赛赔率", channel_label="微信")
        matches_reply = await command_reply(session, store, "当前比赛", channel_label="微信")

    assert odds_reply == "当前没有正在直播的比赛。"
    assert matches_reply == "当前没有正在追踪的比赛。"
    assert "当前比赛赔率 — 查看当前直播比赛双方赔率" in help_text()
    await engine.dispose()
