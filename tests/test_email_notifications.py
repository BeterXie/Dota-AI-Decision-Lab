import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderResponse
from app.ai.coordinator import AiCoordinator
from app.db import Base
from app.domain.decision import AiDecision
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.jobs.handlers import ApplicationJobHandlers
from app.jobs.repository import JobRepository
from app.models import AiDecisionRecord, DecisionEmailNotificationRecord, DurableJobRecord
from app.notifications.email import (
    DecisionEmailNotificationService,
    OutgoingEmail,
    ResendEmailSender,
    render_decision_email,
)
from app.notifications.translation import DeepSeekEmailTranslator
from app.runtime.health import HealthRegistry
from app.snapshots.repository import SnapshotRepository


class RecordingSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.messages: list[OutgoingEmail] = []
        self.error = error

    async def send(self, message: OutgoingEmail) -> str:
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        return "resend-fixture-id"

    async def close(self) -> None:
        return None


class SuccessfulProvider:
    name = "openai"
    model = "fixture-model"

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, _snapshot_input: str) -> AiProviderResponse:
        self.calls += 1
        return AiProviderResponse(
            raw_response={"model": self.model},
            decision=AiDecision(
                action="NO_BUY",
                fair_probability_a=None,
                confidence=0.6,
                market_assessment="UNKNOWN",
                minimum_acceptable_odds_a=None,
                primary_reasons=["No verified edge"],
                counter_arguments=["Market may move"],
                data_quality_concerns=["Sample is limited"],
                blockers=[],
            ),
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


class BuyProvider(SuccessfulProvider):
    async def decide(self, _snapshot_input: str) -> AiProviderResponse:
        self.calls += 1
        return AiProviderResponse(
            raw_response={"model": self.model},
            decision=AiDecision(
                action="BUY_A",
                fair_probability_a=0.55,
                confidence=0.8,
                market_assessment="UNDERPRICED",
                minimum_acceptable_odds_a=1.9,
                stake=250.0,
                primary_reasons=["Verified draft edge"],
                counter_arguments=["Late crossover"],
                data_quality_concerns=[],
                blockers=[],
            ),
            model_version=self.model,
        )


class ScriptedProvider(SuccessfulProvider):
    def __init__(self, decisions: list[AiDecision]) -> None:
        super().__init__()
        self._decisions = decisions

    async def decide(self, _snapshot_input: str) -> AiProviderResponse:
        self.calls += 1
        decision = self._decisions[min(self.calls - 1, len(self._decisions) - 1)]
        return AiProviderResponse(
            raw_response={"model": self.model},
            decision=decision,
            model_version=self.model,
        )


class RecordingWeChatService:
    def __init__(self) -> None:
        self.prepared_batches: list[list[str]] = []

    async def prepare_decision_notification(self, session, *, snapshot, decisions) -> None:
        self.prepared_batches.append(sorted(str(item.id) for item in decisions))


async def _snapshot_and_decisions(session, decision_at: datetime | None = None):
    if decision_at is None:
        decision_at = datetime.now(UTC)
    snapshot = await SnapshotRepository().persist(
        session,
        canonical_map_id=None,
        decision_at=decision_at,
        mode="LIVE_BASIC",
        identity={
            "map_number": 2,
            "valve_match_id": 8940730389,
            "team_a": {"id": "team-a", "name": "Spirit"},
            "team_b": {"id": "team-b", "name": "Tundra"},
        },
        market={
            "market_type": "match_winner",
            "match_stage": "Map 2",
            "observations": [
                {
                    "selection_team_id": "team-a",
                    "price": "1.86",
                    "fair_probability": 0.537,
                    "normalized_status": "UNKNOWN",
                    "received_at": "2026-08-13T01:02:02Z",
                },
                {
                    "selection_team_id": "team-b",
                    "price": "2.04",
                    "fair_probability": 0.49,
                    "normalized_status": "UNKNOWN",
                    "received_at": "2026-08-13T01:02:02Z",
                },
            ],
        },
        draft={
            "slots": [{"side": "radiant", "position": 1, "account_id": 101, "hero_id": 10}],
            "curve": {"derived_features": {"current_minute_edge": 3.2}},
        },
        history={
            "team_a": {"base_rating": 1680, "recent_form": 0.2},
            "team_b": {"base_rating": 1600, "recent_form": 0.1},
            "coverage": {"team_strength_ready_count": 2},
        },
        live={
            "game_time_seconds": 754,
            "radiant_kills": 12,
            "dire_kills": 9,
            "radiant_nw_lead": 2450,
            "first_blood": "radiant",
        },
        quality={
            "eligible": True,
            "blockers": [],
            "warnings": ["LIVE_SYNC_CAUTION"],
            "live_sync": {"status": "CAUTION"},
        },
    )
    decisions = [
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
            request_started_at=decision_at,
            response_received_at=decision_at,
            latency_seconds=1.2,
            raw_response={},
            normalized_response={
                "action": "BUY_A",
                "fair_probability_a": 0.61,
                "confidence": 0.72,
                "market_assessment": "UNDERPRICED",
                "minimum_acceptable_odds_a": 1.75,
                "primary_reasons": ["market.observations favors A"],
                "counter_arguments": ["quality.live_sync is CAUTION"],
                "data_quality_concerns": ["LIVE_SYNC_CAUTION"],
                "blockers": [],
            },
            parse_status="SUCCESS",
        ),
        AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="deepseek",
            model="deepseek-test",
            model_version="deepseek-test",
            prompt_version="prompt-v1",
            decision_policy_version="policy-v1",
            ai_view_version="ai-view-v2",
            request_started_at=decision_at,
            response_received_at=decision_at,
            latency_seconds=2.4,
            parse_status="PARSE_FAILED",
            error="response has no output text",
        ),
    ]
    session.add_all(decisions)
    await session.flush()
    return snapshot, decisions


@pytest.mark.asyncio
async def test_email_content_uses_the_immutable_snapshot_and_all_ai_results() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        snapshot, decisions = await _snapshot_and_decisions(session)

    subject, text_body, html_body = render_decision_email(
        snapshot,
        decisions,
        subject_prefix="[Decision]",
    )

    assert "Spirit vs Tundra" in subject
    assert "BUY Spirit" in subject
    assert "AI ERROR" in subject
    assert "比赛中实时分析" in subject
    assert "赔率 1.86" in text_body
    assert "12-9" in text_body
    assert "12:34" in text_body
    assert "天辉 领先 2,450 金币" in text_body
    assert "10" in text_body
    assert "当前时间优势：3.2" in text_body
    assert "队伍基础评分：1680" in text_body
    assert "赔率与比赛数据可能存在时间差" in text_body
    assert "主要理由：market.observations favors A" in text_body
    assert "可能出错的地方" not in text_body
    assert "数据方面的顾虑" not in text_body
    assert "模型状态：回答格式异常" in text_body
    assert "Spirit" in html_body and "各 AI 的判断" in html_body
    await engine.dispose()


@pytest.mark.asyncio
async def test_email_subject_lists_deduplicated_ai_conclusions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        snapshot, decisions = await _snapshot_and_decisions(session)
        decisions[1].parse_status = "SUCCESS"
        decisions[1].normalized_response = {
            "action": "NO_BUY",
            "fair_probability_a": None,
            "confidence": 0.5,
            "market_assessment": "UNKNOWN",
            "minimum_acceptable_odds_a": None,
            "primary_reasons": [],
            "counter_arguments": [],
            "data_quality_concerns": [],
            "blockers": [],
        }
        decisions.append(
            AiDecisionRecord(
                id=uuid4(),
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                provider="kimi",
                model="kimi-test",
                model_version="kimi-test",
                prompt_version="prompt-v1",
                decision_policy_version="policy-v1",
                ai_view_version="ai-view-v2",
                request_started_at=snapshot.decision_at,
                response_received_at=snapshot.decision_at,
                latency_seconds=1.0,
                raw_response={},
                normalized_response={
                    "action": "BUY_A",
                    "fair_probability_a": 0.6,
                    "confidence": 0.7,
                    "market_assessment": "UNDERPRICED",
                    "minimum_acceptable_odds_a": 1.75,
                    "primary_reasons": [],
                    "counter_arguments": [],
                    "data_quality_concerns": [],
                    "blockers": [],
                },
                parse_status="SUCCESS",
            )
        )

    subject, _, _ = render_decision_email(
        snapshot,
        decisions,
        subject_prefix="[Decision]",
    )

    assert subject == ("[Decision] NO BUY / BUY Spirit | Spirit vs Tundra | 比赛中实时分析")
    await engine.dispose()


@pytest.mark.asyncio
async def test_email_notification_is_durable_idempotent_and_not_resent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sender = RecordingSender()
    service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=JobRepository(),
        sender=sender,
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("one@example.com", "two@example.com"),
        subject_prefix="[Decision]",
    )
    async with factory() as session, session.begin():
        snapshot, decisions = await _snapshot_and_decisions(session)
        first = await service.prepare(session, snapshot=snapshot, decisions=decisions)
        second = await service.prepare(session, snapshot=snapshot, decisions=decisions)
        assert first == second

    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(DecisionEmailNotificationRecord))
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DurableJobRecord)
                .where(DurableJobRecord.job_type == JobType.SEND_DECISION_EMAIL.value)
            )
            == 1
        )

    restarted_service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=JobRepository(),
        sender=sender,
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("one@example.com", "two@example.com"),
        subject_prefix="[Decision]",
    )
    sent = await restarted_service.deliver(first)
    repeated = await restarted_service.deliver(first)

    assert sent.status == "SENT" and sent.sent_at is not None
    assert sent.provider_message_id == "resend-fixture-id"
    assert repeated.status == "SENT"
    assert len(sender.messages) == 1
    message = sender.messages[0]
    assert message.sender == "Decision Lab <alerts@example.com>"
    assert message.recipients == ("one@example.com", "two@example.com")
    assert message.text_body and message.html_body
    assert message.idempotency_key == f"decision-email/{first}"
    await engine.dispose()


@pytest.mark.asyncio
async def test_email_failure_is_persisted_and_raised_for_job_retry() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=JobRepository(),
        sender=RecordingSender(ConnectionError("Resend offline")),
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("owner@example.com",),
        subject_prefix="[Decision]",
    )
    async with factory() as session, session.begin():
        snapshot, decisions = await _snapshot_and_decisions(session)
        notification_id = await service.prepare(
            session,
            snapshot=snapshot,
            decisions=decisions,
        )

    with pytest.raises(ConnectionError, match="Resend offline"):
        await service.deliver(notification_id)

    async with factory() as session:
        failed = await session.get(DecisionEmailNotificationRecord, notification_id)
        assert failed is not None
        assert failed.status == "FAILED"
        assert failed.attempt_count == 1
        assert failed.last_error == "ConnectionError: Resend offline"
    await engine.dispose()


@pytest.mark.asyncio
async def test_resend_sender_uses_http_api_contract_and_idempotency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.resend.com/emails"
        assert request.headers["Authorization"] == "Bearer resend-test-key"
        assert request.headers["Idempotency-Key"] == "decision-email/fixture"
        assert request.headers["Content-Type"] == "application/json"
        assert request.read()
        payload = json.loads(request.content)
        assert payload == {
            "from": "Decision Lab <alerts@example.com>",
            "to": ["owner@example.com"],
            "subject": "Decision",
            "text": "plain body",
            "html": "<p>html body</p>",
        }
        return httpx.Response(200, json={"id": "resend-email-id"})

    client = httpx.AsyncClient(
        base_url="https://api.resend.com",
        transport=httpx.MockTransport(handler),
    )
    sender = ResendEmailSender(
        api_key="resend-test-key",
        base_url="https://api.resend.com",
        timeout_seconds=10,
        client=client,
    )

    provider_id = await sender.send(
        OutgoingEmail(
            sender="Decision Lab <alerts@example.com>",
            recipients=("owner@example.com",),
            subject="Decision",
            text_body="plain body",
            html_body="<p>html body</p>",
            idempotency_key="decision-email/fixture",
        )
    )

    assert provider_id == "resend-email-id"
    await client.aclose()


@pytest.mark.asyncio
async def test_resend_sender_raises_on_provider_error() -> None:
    client = httpx.AsyncClient(
        base_url="https://api.resend.com",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                422,
                json={"name": "validation_error", "message": "invalid sender"},
            )
        ),
    )
    sender = ResendEmailSender(
        api_key="resend-test-key",
        base_url="https://api.resend.com",
        timeout_seconds=10,
        client=client,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await sender.send(
            OutgoingEmail(
                sender="alerts@example.com",
                recipients=("owner@example.com",),
                subject="Decision",
                text_body="body",
                html_body="<p>body</p>",
                idempotency_key="decision-email/fixture",
            )
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_deepseek_email_translation_keeps_decision_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        _, decisions = await _snapshot_and_decisions(session)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-flash"
        assert "普通Dota 2玩家" in payload["instructions"]
        source = json.loads(payload["input"])
        assert all("counter_arguments" not in item for item in source)
        assert all("data_quality_concerns" not in item for item in source)
        ids = [item["decision_id"] for item in source]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "deepseek-v4-flash",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "translations": [
                                            {
                                                "decision_id": decision_id,
                                                "primary_reasons": ["市场价格支持该判断"],
                                                "blockers": [],
                                                "error": None,
                                            }
                                            for decision_id in ids
                                        ]
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    client = httpx.AsyncClient(
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(handler),
    )
    translator = DeepSeekEmailTranslator(
        api_key="deepseek-test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="xhigh",
        timeout_seconds=10,
        client=client,
    )
    result = await translator.translate(decisions)

    assert set(result.translations) == {str(decision.id) for decision in decisions}
    assert result.translations[str(decisions[0].id)]["primary_reasons"] == ["市场价格支持该判断"]
    await client.aclose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_handler_atomically_enqueues_one_email_batch() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    sender = RecordingSender()
    email_service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=jobs,
        sender=sender,
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("owner@example.com",),
        subject_prefix="[Decision]",
    )
    snapshots = SnapshotRepository()
    provider = BuyProvider()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
    handler = ApplicationJobHandlers(
        SimpleNamespace(
            settings=SimpleNamespace(ai_min_game_time_seconds=600),
            session_factory=factory,
            snapshots=snapshots,
            ai=AiCoordinator([provider], timeout_seconds=1),
            health=HealthRegistry(),
            email_notifications=email_service,
        )
    )
    job = DurableJob(
        id=uuid4(),
        job_type=JobType.RUN_AI_PROVIDER,
        dedupe_key="ai-fixture",
        payload={
            "snapshot_id": str(snapshot.snapshot_id),
            "provider": provider.name,
            "model": provider.model,
        },
        status=JobStatus.RUNNING,
        priority=100,
        not_before=now,
        created_at=now,
        attempt_count=1,
        max_attempts=8,
        locked_by="fixture",
        locked_at=now,
    )

    await handler.run_ai(job)
    await handler.run_ai(job)

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AiDecisionRecord)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(DecisionEmailNotificationRecord))
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DurableJobRecord)
                .where(DurableJobRecord.job_type == JobType.SEND_DECISION_EMAIL.value)
            )
            == 1
        )
    assert sender.messages == []
    assert provider.calls == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_handler_skips_email_when_no_buy_decision() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    email_service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=JobRepository(),
        sender=RecordingSender(),
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("owner@example.com",),
        subject_prefix="[Decision]",
    )
    snapshots = SnapshotRepository()
    provider = SuccessfulProvider()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
    handler = ApplicationJobHandlers(
        SimpleNamespace(
            settings=SimpleNamespace(ai_min_game_time_seconds=600),
            session_factory=factory,
            snapshots=snapshots,
            ai=AiCoordinator([provider], timeout_seconds=1),
            health=HealthRegistry(),
            email_notifications=email_service,
        )
    )
    job = DurableJob(
        id=uuid4(),
        job_type=JobType.RUN_AI_PROVIDER,
        dedupe_key="ai-fixture-no-buy",
        payload={
            "snapshot_id": str(snapshot.snapshot_id),
            "provider": provider.name,
            "model": provider.model,
        },
        status=JobStatus.RUNNING,
        priority=100,
        not_before=now,
        created_at=now,
        attempt_count=1,
        max_attempts=8,
        locked_by="fixture",
        locked_at=now,
    )

    await handler.run_ai(job)

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AiDecisionRecord)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(DecisionEmailNotificationRecord))
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DurableJobRecord)
                .where(DurableJobRecord.job_type == JobType.SEND_DECISION_EMAIL.value)
            )
            == 0
        )
    await engine.dispose()


async def _persist_checkpoint_snapshot(
    snapshots: SnapshotRepository,
    session,
    *,
    canonical_map_id,
    decision_at: datetime,
):
    return await snapshots.persist(
        session,
        canonical_map_id=canonical_map_id,
        decision_at=decision_at,
        mode="LIVE_BASIC",
        identity={
            "team_a": {"id": "team-a", "name": "A"},
            "team_b": {"id": "team-b", "name": "B"},
        },
        market={},
        draft=None,
        history={},
        live={"game_time_seconds": 600},
        quality={"eligible": True, "blockers": [], "warnings": []},
    )


def _decision(action: str, *, stake: float | None = 100.0) -> AiDecision:
    return AiDecision(
        action=action,
        fair_probability_a=0.6 if action == "BUY_A" else None,
        confidence=0.7,
        market_assessment="UNDERPRICED" if action in {"BUY_A", "BUY_B"} else "UNKNOWN",
        minimum_acceptable_odds_a=1.7,
        stake=stake if action in {"BUY_A", "BUY_B"} else None,
        primary_reasons=[],
        counter_arguments=[],
        data_quality_concerns=[],
        blockers=[],
    )


@pytest.mark.asyncio
async def test_ai_handler_emails_only_when_the_buy_side_changes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    email_service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=JobRepository(),
        sender=RecordingSender(),
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("owner@example.com",),
        subject_prefix="[Decision]",
    )
    snapshots = SnapshotRepository()
    provider = ScriptedProvider(
        [
            _decision("BUY_A"),
            _decision("NO_BUY"),
            _decision("BUY_A"),
            _decision("BUY_B"),
            _decision("BUY_A"),
        ]
    )
    wechat_service = RecordingWeChatService()
    handler = ApplicationJobHandlers(
        SimpleNamespace(
            settings=SimpleNamespace(ai_min_game_time_seconds=600),
            session_factory=factory,
            snapshots=snapshots,
            ai=AiCoordinator([provider], timeout_seconds=1),
            health=HealthRegistry(),
            email_notifications=email_service,
            wechat_clawbot=wechat_service,
        )
    )
    canonical_map_id = uuid4()
    now = datetime.now(UTC)
    for offset in range(5):
        decision_at = now + timedelta(minutes=offset)
        async with factory() as session, session.begin():
            snapshot = await _persist_checkpoint_snapshot(
                snapshots,
                session,
                canonical_map_id=canonical_map_id,
                decision_at=decision_at,
            )
        job = DurableJob(
            id=uuid4(),
            job_type=JobType.RUN_AI_PROVIDER,
            dedupe_key=f"ai-side-change-{offset}",
            payload={
                "snapshot_id": str(snapshot.snapshot_id),
                "provider": provider.name,
                "model": provider.model,
            },
            status=JobStatus.RUNNING,
            priority=100,
            not_before=decision_at,
            created_at=decision_at,
            attempt_count=1,
            max_attempts=8,
            locked_by="fixture",
            locked_at=decision_at,
        )
        await handler.run_ai(job)

    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(DecisionEmailNotificationRecord))
            == 3
        )
        notifications = list(
            (
                await session.scalars(
                    select(DecisionEmailNotificationRecord).order_by(
                        DecisionEmailNotificationRecord.created_at
                    )
                )
            ).all()
        )
    assert "BUY A" in notifications[0].subject
    assert "BUY B" in notifications[1].subject
    assert "BUY A" in notifications[2].subject
    assert provider.calls == 5
    assert len(wechat_service.prepared_batches) == 3
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_handler_does_not_call_providers_before_ten_minutes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    snapshots = SnapshotRepository()
    provider = SuccessfulProvider()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 599},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
    handler = ApplicationJobHandlers(
        SimpleNamespace(
            settings=SimpleNamespace(ai_min_game_time_seconds=600),
            session_factory=factory,
            snapshots=snapshots,
            ai=AiCoordinator([provider], timeout_seconds=1),
            health=HealthRegistry(),
            email_notifications=None,
        )
    )
    job = DurableJob(
        id=uuid4(),
        job_type=JobType.RUN_AI_PROVIDER,
        dedupe_key="ai-fixture-early",
        payload={
            "snapshot_id": str(snapshot.snapshot_id),
            "provider": provider.name,
            "model": provider.model,
        },
        status=JobStatus.RUNNING,
        priority=100,
        not_before=now,
        created_at=now,
        attempt_count=1,
        max_attempts=8,
        locked_by="fixture",
        locked_at=now,
    )

    await handler.run_ai(job)

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AiDecisionRecord)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(DecisionEmailNotificationRecord))
            == 0
        )
    assert provider.calls == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_decision_email_is_skipped_and_marked_expired() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    sender = RecordingSender()
    email_service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=jobs,
        sender=sender,
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("owner@example.com",),
        subject_prefix="[Decision]",
        max_decision_age_seconds=60.0,
    )
    snapshots = SnapshotRepository()
    # 2 hours old snapshot
    stale_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=stale_time,
            mode="LIVE_BASIC",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        decisions = [
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
                request_started_at=stale_time,
                response_received_at=stale_time,
                latency_seconds=1.2,
                raw_response={},
                normalized_response={
                    "action": "BUY_A",
                    "fair_probability_a": 0.65,
                    "confidence": 0.8,
                    "market_assessment": "UNDERPRICED",
                    "primary_reasons": ["赔率划算"],
                    "counter_arguments": [],
                    "data_quality_concerns": [],
                    "blockers": [],
                },
                parse_status="SUCCESS",
            )
        ]
        # Prepare should skip stale snapshot
        notification_id = await email_service.prepare(
            session, snapshot=snapshot, decisions=decisions
        )
        assert notification_id is None

    assert len(sender.messages) == 0
    await engine.dispose()
