import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import AiDecisionRecord, DurableJobRecord
from app.providers.wechat_clawbot.client import WeChatClawBotClient
from app.providers.wechat_clawbot.models import WeChatAccount
from app.providers.wechat_clawbot.service import WeChatClawBotService, _command_reply
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
                "confidence": 0.8,
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
                "action": "BUY_A",
                "fair_probability_a": 0.61,
                "confidence": 0.8,
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
        assert "支持 OG" in sent[0][1]
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
        reply = await _command_reply(session, store, "暂停通知")
        assert "已暂停" in reply
        assert store.decision_notifications_enabled() is False
        reply = await _command_reply(session, store, "恢复通知")
        assert "已恢复" in reply
        assert store.decision_notifications_enabled() is True
    await engine.dispose()
