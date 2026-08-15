from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{path}: expected {count} occurrences, found {found}: {old[:120]!r}")
    write(path, text.replace(old, new, count))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    text = read(path)
    start_i = text.index(start)
    end_i = text.index(end, start_i)
    write(path, text[:start_i] + replacement + text[end_i:])


# ---------------------------------------------------------------------------
# Reconciliation: turn the remaining full-table + N+1 scans into bounded SQL
# candidate queries. These are repair loops, not analytics queries.
# ---------------------------------------------------------------------------
replace_between(
    "app/jobs/reconciliation.py",
    "    async def _reconcile_drafts(",
    "    async def _reconcile_postmatch(",
    '''    async def _reconcile_drafts(self, session: AsyncSession) -> int:\n        drafts = list(\n            (\n                await session.scalars(\n                    select(DraftSnapshotRecord)\n                    .where(\n                        DraftSnapshotRecord.complete.is_(True),\n                        ~select(DraftMinuteCurveRecord.id)\n                        .where(\n                            DraftMinuteCurveRecord.draft_snapshot_id == DraftSnapshotRecord.id,\n                            DraftMinuteCurveRecord.model_version == MODEL_VERSION,\n                        )\n                        .exists(),\n                    )\n                    .order_by(DraftSnapshotRecord.observed_at.desc())\n                    .limit(1000)\n                )\n            ).all()\n        )\n        for draft in drafts:\n            await self._jobs.enqueue(\n                session,\n                job_type=JobType.BUILD_DRAFT_CURVE,\n                dedupe_key=f"reconcile-draft:{MODEL_VERSION}:{draft.id}",\n                payload={\n                    "canonical_map_id": str(draft.canonical_map_id),\n                    "draft_snapshot_id": str(draft.id),\n                },\n                reopen_terminal=True,\n            )\n        return len(drafts)\n\n''',
)

replace_between(
    "app/jobs/reconciliation.py",
    "    async def _reconcile_settlements(",
    "    async def _reconcile_evaluations(",
    '''    async def _reconcile_settlements(self, session: AsyncSession) -> int:\n        facts = list(\n            (\n                await session.scalars(\n                    select(HistoricalMapRecord)\n                    .where(\n                        HistoricalMapRecord.canonical_map_id.is_not(None),\n                        HistoricalMapRecord.winner_team_id.is_not(None),\n                        HistoricalMapRecord.sync_status != "DATA_CONFLICT",\n                        select(ProviderMatchMapping.id)\n                        .where(\n                            ProviderMatchMapping.provider == "raybet",\n                            ProviderMatchMapping.canonical_map_id\n                            == HistoricalMapRecord.canonical_map_id,\n                        )\n                        .exists(),\n                        ~select(MapResultRecord.id)\n                        .where(\n                            MapResultRecord.canonical_map_id\n                            == HistoricalMapRecord.canonical_map_id\n                        )\n                        .exists(),\n                    )\n                    .order_by(HistoricalMapRecord.first_usable_at.desc())\n                    .limit(1000)\n                )\n            ).all()\n        )\n        for fact in facts:\n            await self._jobs.enqueue(\n                session,\n                job_type=JobType.SETTLE_MAP,\n                dedupe_key=f"reconcile-settlement:{fact.canonical_map_id}",\n                payload={"canonical_map_id": str(fact.canonical_map_id)},\n                reopen_terminal=True,\n            )\n        return len(facts)\n\n''',
)

replace_between(
    "app/jobs/reconciliation.py",
    "    async def _reconcile_evaluations(",
    # method is last in file; replace to EOF
    "",
    "",
) if False else None
text = read("app/jobs/reconciliation.py")
start = text.index("    async def _reconcile_evaluations(")
replacement = '''    async def _reconcile_evaluations(self, session: AsyncSession) -> int:\n        snapshot_ids = list(\n            (\n                await session.scalars(\n                    select(DecisionSnapshotRecord.id)\n                    .join(\n                        AiDecisionRecord,\n                        AiDecisionRecord.snapshot_id == DecisionSnapshotRecord.id,\n                    )\n                    .join(\n                        MapResultRecord,\n                        MapResultRecord.canonical_map_id\n                        == DecisionSnapshotRecord.canonical_map_id,\n                    )\n                    .where(\n                        DecisionSnapshotRecord.canonical_map_id.is_not(None),\n                        AiDecisionRecord.parse_status == "SUCCESS",\n                        AiDecisionRecord.normalized_response.is_not(None),\n                        MapResultRecord.provider_conflict.is_(False),\n                        MapResultRecord.winner_team_id.is_not(None),\n                        ~select(DecisionEvaluationRecord.id)\n                        .where(\n                            DecisionEvaluationRecord.ai_decision_id == AiDecisionRecord.id,\n                            DecisionEvaluationRecord.metrics_version == METRICS_VERSION,\n                        )\n                        .exists(),\n                    )\n                    .distinct()\n                    .order_by(DecisionSnapshotRecord.id)\n                    .limit(1000)\n                )\n            ).all()\n        )\n        for snapshot_id in snapshot_ids:\n            await self._jobs.enqueue(\n                session,\n                job_type=JobType.EVALUATE_DECISION,\n                dedupe_key=f"reconcile-evaluation:{METRICS_VERSION}:{snapshot_id}",\n                payload={"snapshot_id": str(snapshot_id)},\n                reopen_terminal=True,\n            )\n        return len(snapshot_ids)\n'''
write("app/jobs/reconciliation.py", text[:start] + replacement)

# Postmatch is already query-based; cap repair work per pass and avoid ancient stale streams.
replace(
    "app/jobs/reconciliation.py",
    '''                        latest_live.c.latest_received_at < now - timedelta(minutes=3),\n                        ~select(MapResultRecord.id)\n''',
    '''                        latest_live.c.latest_received_at < now - timedelta(minutes=3),\n                        latest_live.c.latest_received_at >= now - timedelta(days=2),\n                        ~select(MapResultRecord.id)\n''',
)
replace(
    "app/jobs/reconciliation.py",
    '''                    )\n                )\n            ).all()\n        )\n        bucket = int(now.timestamp()) // 900\n''',
    '''                    )\n                    .limit(500)\n                )\n            ).all()\n        )\n        bucket = int(now.timestamp()) // 900\n''',
    1,
)

# ---------------------------------------------------------------------------
# Unknown != known: keep DLTV's conservative fetched_at fallback for ordering,
# but make the estimate explicit and auditable all the way to persistence.
# ---------------------------------------------------------------------------
replace(
    "app/domain/history.py",
    "    started_at: datetime\n    ended_at: datetime | None = None\n",
    "    started_at: datetime\n    started_at_estimated: bool = False\n    ended_at: datetime | None = None\n",
)
replace(
    "app/models.py",
    '''    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)\n    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))\n''',
    '''    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)\n    started_at_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)\n    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))\n''',
)
replace(
    "app/providers/dltv/results.py",
    '''    series = database.get("series") if isinstance(database.get("series"), dict) else {}\n    started_at = _iso_datetime(series.get("started_at")) or fetched_at\n    ended_at = _iso_datetime(series.get("ended_at"))\n''',
    '''    series = database.get("series") if isinstance(database.get("series"), dict) else {}\n    published_started_at = _iso_datetime(series.get("started_at"))\n    started_at = published_started_at or fetched_at\n    started_at_estimated = published_started_at is None\n    ended_at = _iso_datetime(series.get("ended_at"))\n''',
)
replace(
    "app/providers/dltv/results.py",
    '''        started_at=started_at,\n        ended_at=ended_at,\n''',
    '''        started_at=started_at,\n        started_at_estimated=started_at_estimated,\n        ended_at=ended_at,\n''',
)
replace(
    "app/providers/dltv/results.py",
    '''    return HistoricalMatchBundle(\n        match=match,\n        players=(),\n        advanced_available=False,\n    )\n''',
    '''    return HistoricalMatchBundle(\n        match=match,\n        players=(),\n        advanced_available=False,\n        warnings=("STARTED_AT_ESTIMATED_FROM_FETCHED_AT",) if started_at_estimated else (),\n    )\n''',
)
replace(
    "app/history/repository.py",
    '''                started_at=bundle.match.started_at,\n                ended_at=bundle.match.ended_at,\n''',
    '''                started_at=bundle.match.started_at,\n                started_at_estimated=bundle.match.started_at_estimated,\n                ended_at=bundle.match.ended_at,\n''',
)
replace(
    "app/history/repository.py",
    '''            record.patch_id = record.patch_id or bundle.match.patch_id\n            record.ended_at = record.ended_at or bundle.match.ended_at\n''',
    '''            record.patch_id = record.patch_id or bundle.match.patch_id\n            if record.started_at_estimated and not bundle.match.started_at_estimated:\n                record.started_at = bundle.match.started_at\n                record.started_at_estimated = False\n            record.ended_at = record.ended_at or bundle.match.ended_at\n''',
)
write(
    "migrations/versions/0028_historical_start_time_provenance.py",
    '''"""Track whether historical map started_at is estimated.\n\nRevision ID: 0028_historical_start_time_provenance\nRevises: 0027_ai_token_usage\n"""\n\nfrom collections.abc import Sequence\n\nimport sqlalchemy as sa\nfrom alembic import op\n\nrevision: str = "0028_historical_start_time_provenance"\ndown_revision: str | None = "0027_ai_token_usage"\nbranch_labels: str | Sequence[str] | None = None\ndepends_on: str | Sequence[str] | None = None\n\n\ndef upgrade() -> None:\n    op.add_column(\n        "historical_maps",\n        sa.Column(\n            "started_at_estimated",\n            sa.Boolean(),\n            nullable=False,\n            server_default=sa.false(),\n        ),\n    )\n    op.alter_column("historical_maps", "started_at_estimated", server_default=None)\n\n\ndef downgrade() -> None:\n    op.drop_column("historical_maps", "started_at_estimated")\n''',
)

# ---------------------------------------------------------------------------
# Strict configuration: a typo in .env is startup-visible instead of ignored.
# ---------------------------------------------------------------------------
replace("app/config.py", '        extra="ignore",\n', '        extra="forbid",\n')
replace("pyproject.toml", '    "ruff>=0.15,<1",\n', '    "ruff==0.16.2",\n')
write(
    ".pre-commit-config.yaml",
    '''repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.16.2\n    hooks:\n      - id: ruff-check\n        args: [--fix]\n      - id: ruff-format\n''',
)

# ---------------------------------------------------------------------------
# EventHub loss remains intentionally lossy for live UI fan-out, but is exported
# as a real Prometheus counter.
# ---------------------------------------------------------------------------
write(
    "app/events/hub.py",
    '''import asyncio\nfrom collections.abc import Callable\n\n\nclass EventHub:\n    def __init__(self, *, on_drop: Callable[[], None] | None = None) -> None:\n        self._subscribers: set[asyncio.Queue] = set()\n        self._dropped_events = 0\n        self._on_drop = on_drop\n\n    async def publish(self, topic: str, payload: dict) -> None:\n        event = {"topic": topic, "payload": payload}\n        for queue in tuple(self._subscribers):\n            try:\n                queue.put_nowait(event)\n            except asyncio.QueueFull:\n                self._dropped_events += 1\n                if self._on_drop is not None:\n                    self._on_drop()\n\n    @property\n    def dropped_events(self) -> int:\n        return self._dropped_events\n\n    def subscribe(self, *, maxsize: int = 100) -> asyncio.Queue:\n        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)\n        self._subscribers.add(queue)\n        return queue\n\n    def unsubscribe(self, queue: asyncio.Queue) -> None:\n        self._subscribers.discard(queue)\n''',
)
replace(
    "app/observability/metrics.py",
    '''        self.worker_restarts = Counter("worker_restart_total", "Worker restart count", ["worker"])\n''',
    '''        self.worker_restarts = Counter("worker_restart_total", "Worker restart count", ["worker"])\n        self.event_hub_dropped = Counter(\n            "event_hub_dropped_total", "Live EventHub messages dropped because a subscriber queue was full"\n        )\n''',
)
replace(
    "app/main.py",
    "    hub = EventHub()\n",
    "    hub = EventHub(on_drop=metrics.event_hub_dropped.inc)\n",
)

# ---------------------------------------------------------------------------
# Ruff security baseline: fix real issues and annotate only verified false
# positives/non-security randomness. The CI command will enforce this list stays clean.
# ---------------------------------------------------------------------------
text = read("app/ai/coordinator.py")
text = text.replace("from pydantic_core import to_jsonable_python\n", "from pydantic import ValidationError\nfrom pydantic_core import to_jsonable_python\n", 1)
text = text.replace(
    '''        try:\n            decision = AiDecision.model_validate(record.normalized_response)\n        except Exception:\n            continue\n''',
    '''        try:\n            decision = AiDecision.model_validate(record.normalized_response)\n        except ValidationError:\n            continue\n''',
    1,
)
write("app/ai/coordinator.py", text)

# Role assignment has already gated these optionals; use explicit guards instead of asserts
# so optimization flags can never remove correctness checks.
text = read("app/draft/role_assignment.py")
text = text.replace(
    '''    for pick in picks:\n        assert pick.account_id is not None\n        rows = evidence.get(pick.account_id, [])\n''',
    '''    for pick in picks:\n        account_id = pick.account_id\n        if account_id is None:\n            return None\n        rows = evidence.get(account_id, [])\n''',
    1,
)
text = text.replace("        position_shares[pick.account_id] = {\n", "        position_shares[account_id] = {\n", 1)
text = text.replace("        sample_sizes[pick.account_id] = len(rows)\n", "        sample_sizes[account_id] = len(rows)\n", 1)
text = text.replace(
    '''        for pick, position in zip(picks, assignment, strict=True):\n            assert pick.account_id is not None\n            share = position_shares[pick.account_id][position]\n''',
    '''        for pick, position in zip(picks, assignment, strict=True):\n            account_id = pick.account_id\n            if account_id is None:\n                return None\n            share = position_shares[account_id][position]\n''',
    1,
)
text = text.replace(
    '''    for pick, position in zip(picks, best_assignment, strict=True):\n        assert pick.account_id is not None and pick.hero_id is not None\n        share = position_shares[pick.account_id][position]\n        sample = sample_sizes[pick.account_id]\n''',
    '''    for pick, position in zip(picks, best_assignment, strict=True):\n        account_id = pick.account_id\n        hero_id = pick.hero_id\n        if account_id is None or hero_id is None:\n            return None\n        share = position_shares[account_id][position]\n        sample = sample_sizes[account_id]\n''',
    1,
)
text = text.replace("                account_id=pick.account_id,\n                hero_id=pick.hero_id,\n", "                account_id=account_id,\n                hero_id=hero_id,\n", 1)
write("app/draft/role_assignment.py", text)

replace(
    "app/events/outbox.py",
    '''                record = await session.get(DomainEventRecord, event_id)\n                assert record is not None\n''',
    '''                record = await session.get(DomainEventRecord, event_id)\n                if record is None:\n                    raise RuntimeError("inserted domain event could not be reloaded")\n''',
)
replace(
    "app/main.py",
    '''    assert settings.resend_api_key is not None\n    assert settings.resend_from is not None\n''',
    '''    if settings.resend_api_key is None or settings.resend_from is None:\n        raise RuntimeError("validated email configuration is incomplete")\n''',
)
replace(
    "app/jobs/runner.py",
    '''            except Exception:\n                pass\n            await self._mark_failed(\n''',
    '''            except Exception as exc:\n                logger.warning(\n                    "durable_job_handler_error_after_lease_failure",\n                    job_id=str(job.id),\n                    error=f"{type(exc).__name__}: {exc}",\n                )\n            await self._mark_failed(\n''',
)

# Dynamic SQL identifiers are selected only from the closed partition map. Bind values stay parameterized.
text = read("app/db_partitions.py")
text = text.replace(
    '''async def _ensure_partition(\n    connection: AsyncConnection,\n    *,\n    table: str,\n    timestamp_column: str,\n    start: date,\n    end: date,\n) -> int:\n''',
    '''async def _ensure_partition(\n    connection: AsyncConnection,\n    *,\n    table: str,\n    timestamp_column: str,\n    start: date,\n    end: date,\n) -> int:\n    if PARTITIONED_TABLES.get(table) != timestamp_column:\n        raise ValueError("partition table/column is not allowlisted")\n''',
    1,
)
text = text.replace('            f"WITH moved AS ("\n', '            f"WITH moved AS ("  # noqa: S608 - identifiers are allowlisted above\n', 1)
text = text.replace(
    '    await connection.execute(text(f"INSERT INTO {table} SELECT * FROM {temporary}"))\n',
    '    await connection.execute(\n        text(f"INSERT INTO {table} SELECT * FROM {temporary}")  # noqa: S608 - allowlisted identifiers\n    )\n',
    1,
)
write("app/db_partitions.py", text)

# Non-cryptographic retry jitter is intentional and explicitly marked as such.
for path in ("app/providers/raybet/http.py", "app/providers/raybet/http_transport.py", "app/runtime/supervisor.py"):
    text = read(path)
    lines = []
    for line in text.splitlines():
        if "uniform(" in line and "# noqa: S311" not in line:
            line += "  # noqa: S311 - retry jitter is not security-sensitive randomness"
        lines.append(line)
    write(path, "\n".join(lines) + "\n")

# WeChat state: sha256 filenames, warnings for corrupted state/permission failures,
# and resolve the Windows system utility before invoking it without a shell.
text = read("app/providers/wechat_clawbot/storage.py")
text = text.replace("import subprocess\n", "import shutil\nimport subprocess\n\nimport structlog\n", 1)
text = text.replace("from app.providers.wechat_clawbot.models import WeChatAccount\n", "from app.providers.wechat_clawbot.models import WeChatAccount\n\nlogger = structlog.get_logger()\n", 1)
text = text.replace(
    '''            except Exception:\n                continue\n        return result\n''',
    '''            except Exception as exc:\n                logger.warning("wechat_clawbot_invalid_account_state", error=str(exc))\n                continue\n        return result\n''',
    1,
)
text = text.replace(
    '''            except Exception:\n                pass\n\n    def cursor''',
    '''            except Exception as exc:\n                logger.warning("wechat_clawbot_cursor_cleanup_failed", error=str(exc))\n\n    def cursor''',
    1,
)
text = text.replace('hashlib.sha1(account_id.encode("utf-8")).hexdigest()[:16]', 'hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16]', 1)
text = text.replace(
    '''        except Exception:\n            # State storage must not become unavailable because a platform\n            # cannot express POSIX-style permissions.\n            pass\n''',
    '''        except Exception as exc:\n            # Keep the local runtime usable, but make permission hardening failure visible.\n            logger.warning("wechat_clawbot_directory_permission_hardening_failed", path=str(path), error=str(exc))\n''',
    1,
)
text = text.replace(
    '''        except Exception:\n            pass\n\n    @staticmethod\n    def _restrict_windows_path''',
    '''        except Exception as exc:\n            logger.warning("wechat_clawbot_file_permission_hardening_failed", path=str(path), error=str(exc))\n\n    @staticmethod\n    def _restrict_windows_path''',
    1,
)
old_run = '''        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)\n        subprocess.run(\n            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:{permission}"],\n            check=False,\n            capture_output=True,\n            creationflags=creation_flags,\n        )\n'''
new_run = '''        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)\n        executable = shutil.which("icacls")\n        if executable is None:\n            raise RuntimeError("icacls is unavailable")\n        subprocess.run(  # noqa: S603 - no shell; executable is resolved and args are structured\n            [executable, str(path), "/inheritance:r", "/grant:r", f"{user}:{permission}"],\n            check=False,\n            capture_output=True,\n            creationflags=creation_flags,\n        )\n'''
if old_run not in text:
    raise RuntimeError("wechat icacls block not found")
text = text.replace(old_run, new_run, 1)
write("app/providers/wechat_clawbot/storage.py", text)

# Legacy migrations use closed in-file constant identifier lists; values remain bound.
for path in (
    "migrations/versions/0015_ti_provider_identity_repair.py",
    "migrations/versions/0017_ti_team_alias_identity_merge.py",
):
    text = read(path)
    text = text.replace(
        'sa.text(f"UPDATE {table} SET {column} = :target WHERE {column} = :source"),',
        'sa.text(  # noqa: S608 - table/column come only from closed migration constants\n                    f"UPDATE {table} SET {column} = :target WHERE {column} = :source"\n                ),',
        1,
    )
    write(path, text)

# CLI QR rendering invokes a fixed npx package without shell interpolation; document the intentional subprocess.
text = read("tools/wechat_clawbot.py")
text = text.replace(
    '''        completed = subprocess.run(\n            ["npx", "-y", "qrcode-terminal", qrcode_url],\n''',
    '''        completed = subprocess.run(  # noqa: S603, S607 - fixed local CLI, no shell\n            ["npx", "-y", "qrcode-terminal", qrcode_url],\n''',
    1,
)
write("tools/wechat_clawbot.py", text)

# ---------------------------------------------------------------------------
# CI: enforce security lint and official-registry production dependency audit.
# ---------------------------------------------------------------------------
replace(
    ".github/workflows/ci.yml",
    "      - run: uv run ruff check app migrations tests tools\n      - run: uv run pytest\n",
    "      - run: uv run ruff check app migrations tests tools\n      - run: uv run ruff check --select S app migrations tools\n      - run: uv run pytest\n",
)
replace(
    ".github/workflows/ci.yml",
    "      - run: npm ci\n      - run: npm test\n",
    "      - run: npm ci\n      - run: npm audit --omit=dev --audit-level=high --registry=https://registry.npmjs.org\n      - run: npm test\n",
)

# ---------------------------------------------------------------------------
# Regression tests for the second wave.
# ---------------------------------------------------------------------------
write(
    "tests/test_event_hub.py",
    '''import pytest\n\nfrom app.events.hub import EventHub\n\n\n@pytest.mark.asyncio\nasync def test_event_hub_counts_and_exports_queue_drops() -> None:\n    exported = 0\n\n    def on_drop() -> None:\n        nonlocal exported\n        exported += 1\n\n    hub = EventHub(on_drop=on_drop)\n    queue = hub.subscribe(maxsize=1)\n    await hub.publish("status", {"n": 1})\n    await hub.publish("status", {"n": 2})\n\n    assert queue.qsize() == 1\n    assert hub.dropped_events == 1\n    assert exported == 1\n''',
)

main_tests = read("tests/test_main_import.py")
if "test_unknown_dotenv_setting_is_rejected" not in main_tests:
    main_tests = main_tests.replace("import pytest\n", "import pytest\nfrom pydantic import ValidationError\n", 1)
    main_tests += '''\n\ndef test_unknown_dotenv_setting_is_rejected(tmp_path) -> None:\n    from app.config import Settings\n\n    env_file = tmp_path / ".env"\n    env_file.write_text("AI_TIMEOUT_SECNODS=10\\n", encoding="utf-8")\n    with pytest.raises(ValidationError, match="AI_TIMEOUT_SECNODS"):\n        Settings(_env_file=env_file)\n'''
    write("tests/test_main_import.py", main_tests)

write(
    "tests/test_dltv_result_provenance.py",
    '''from datetime import UTC, datetime\n\nfrom app.providers.dltv.results import normalize_match_result\n\n\ndef _payload(*, started_at: str | None) -> dict:\n    return {\n        "match_id": 12345,\n        "winner": "radiant",\n        "game_time": 2100,\n        "db": {\n            "first_team": {"id": 1, "is_radiant": True},\n            "second_team": {"id": 2, "is_radiant": False},\n            "series": {"event_id": 9, "started_at": started_at},\n        },\n    }\n\n\ndef test_dltv_missing_started_at_is_explicitly_estimated() -> None:\n    fetched_at = datetime(2026, 8, 16, 2, 0, tzinfo=UTC)\n    bundle = normalize_match_result(_payload(started_at=None), fetched_at=fetched_at)\n    assert bundle.match.started_at == fetched_at\n    assert bundle.match.started_at_estimated is True\n    assert bundle.warnings == ("STARTED_AT_ESTIMATED_FROM_FETCHED_AT",)\n\n\ndef test_dltv_published_started_at_is_not_estimated() -> None:\n    fetched_at = datetime(2026, 8, 16, 2, 0, tzinfo=UTC)\n    bundle = normalize_match_result(\n        _payload(started_at="2026-08-16T01:00:00+00:00"),\n        fetched_at=fetched_at,\n    )\n    assert bundle.match.started_at == datetime(2026, 8, 16, 1, 0, tzinfo=UTC)\n    assert bundle.match.started_at_estimated is False\n    assert bundle.warnings == ()\n''',
)

# Alembic-head assertion follows the new provenance migration.
text = read("tests/test_production_lifecycle_replay.py")
text = text.replace('"0027_ai_token_usage"', '"0028_historical_start_time_provenance"')
write("tests/test_production_lifecycle_replay.py", text)

# Readiness is deliberately availability-oriented: DEGRADED services can still serve local diagnostics.
web_tests = read("tests/test_web_api_contract.py")
if "test_ready_stays_available_for_degraded_dependencies" not in web_tests:
    web_tests += '''\n\n@pytest.mark.asyncio\nasync def test_ready_stays_available_for_degraded_dependencies() -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    health = HealthRegistry()\n    await health.dependency("DATABASE", "READY")\n    await health.dependency("GPT", "DEGRADED", message="temporary provider issue")\n    app = create_app(factory, health)\n    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:\n        response = await client.get("/ready")\n    assert response.status_code == 200\n    assert response.json()["overall"] == "DEGRADED"\n    await engine.dispose()\n'''
    write("tests/test_web_api_contract.py", web_tests)

# Architecture/security docs make intentional local credential/readiness semantics explicit.
readme = read("README.md")
security_section = '''\n## Local security notes\n\n- The application is loopback-only until authenticated HTTP/WebSocket access exists. Do not expose it through a reverse proxy or non-loopback bind.\n- WeChat ClawBot credentials are stored locally in `.runtime/wechat-clawbot/accounts.json`. They are plaintext application credentials protected with owner-only POSIX permissions / a restricted Windows DACL on a best-effort basis; they are **not encrypted at rest**. Treat compromise of the local OS account as compromise of the bot token and rotate/re-login after a machine or account compromise.\n- `/ready` is an availability signal: `ACTION_REQUIRED` returns 503, while `DEGRADED` remains 200 so the local dashboard and diagnostics stay reachable during recoverable provider failures. Dependency detail is present in the response body.\n- `.env` keys are validated strictly. Unknown keys fail startup rather than being silently ignored.\n\n'''
if "## Local security notes" not in readme:
    readme += security_section
    write("README.md", readme)

arch = read("docs/ARCHITECTURE.md")
arch_extra = '''\n### Pre-release operational contracts\n\n- Reconciliation repair scans are bounded and query candidates with `NOT EXISTS` / joins instead of repeatedly loading whole audit tables and issuing N+1 lookups.\n- Historical `started_at` fallbacks are never silent: provider records persist `started_at_estimated`, and DLTV emits `STARTED_AT_ESTIMATED_FROM_FETCHED_AT` when a provider timestamp is missing.\n- Runtime `.env` parsing is strict (`extra=forbid`); misspelled configuration is a startup error.\n- EventHub fan-out is intentionally lossy for live UI status only, and every full-queue drop increments `event_hub_dropped_total`.\n- CI includes Ruff security rules for production/migration/tooling code and a production npm vulnerability audit against the official npm registry.\n'''
if "### Pre-release operational contracts" not in arch:
    anchor = "\n## Post-match Review Analytics\n"
    if anchor not in arch:
        raise RuntimeError("architecture anchor missing")
    arch = arch.replace(anchor, arch_extra + anchor, 1)
    write("docs/ARCHITECTURE.md", arch)

print("second-wave prelaunch hardening applied")
