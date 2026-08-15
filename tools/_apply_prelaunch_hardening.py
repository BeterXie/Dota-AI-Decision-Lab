from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def must_replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    text = read(path)
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{path}: expected {count} occurrences, found {found}: {old[:100]!r}")
    write(path, text.replace(old, new, count))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    text = read(path)
    start_i = text.index(start)
    end_i = text.index(end, start_i)
    write(path, text[:start_i] + replacement + text[end_i:])


# P0/P1 wiring: ai_min_game_time belongs to the web review projection, not FutureOddsService.
must_replace(
    "app/main.py",
    """    future_odds = FutureOddsService(\n        jobs,\n        market_max_age_seconds=settings.live_market_max_age_seconds,\n        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,\n        ai_min_game_time_seconds=settings.ai_min_game_time_seconds,\n    )\n""",
    """    future_odds = FutureOddsService(\n        jobs,\n        market_max_age_seconds=settings.live_market_max_age_seconds,\n        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,\n    )\n""",
)
must_replace(
    "app/main.py",
    """        live_market_max_age_seconds=settings.live_market_max_age_seconds,\n        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,\n    )\n    workers.append(\n        WebServerWorker(\n""",
    """        live_market_max_age_seconds=settings.live_market_max_age_seconds,\n        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,\n        ai_min_game_time_seconds=settings.ai_min_game_time_seconds,\n    )\n    workers.append(\n        WebServerWorker(\n""",
)

# One containment-checked SPA resolver shared by both app factories.
write(
    "app/web/spa.py",
    '''from pathlib import Path\n\nfrom fastapi.responses import FileResponse\n\n\ndef spa_file_response(frontend_dist: Path, full_path: str) -> FileResponse:\n    """Serve only files physically contained by the built frontend directory.\n\n    ``Path.resolve`` closes both ``..`` traversal and symlink escape. Backslashes\n    are normalized before resolution so the same rule holds on Windows. Unknown\n    or escaping paths fall back to the SPA index instead of touching the host FS.\n    """\n    root = frontend_dist.resolve()\n    requested = full_path.replace("\\\\", "/")\n    candidate = (root / requested).resolve()\n    if full_path and candidate.is_relative_to(root) and candidate.is_file():\n        return FileResponse(candidate)\n    return FileResponse(root / "index.html")\n''',
)
for path in ("app/web/__init__.py", "app/web/api.py"):
    must_replace(
        path,
        "from fastapi.responses import FileResponse\n",
        "from fastapi.responses import FileResponse\n" if path == "app/web/api.py" else "from fastapi.responses import FileResponse\n",
    ) if False else None
    text = read(path)
    import_anchor = "from app.runtime.health import HealthRegistry\n"
    if path == "app/web/api.py":
        # api.py has many imports; add beside other app.web imports if available, otherwise after health.
        if "from app.web.spa import spa_file_response\n" not in text:
            marker = "from app.runtime.health import HealthRegistry\n"
            if marker not in text:
                raise RuntimeError(f"{path}: health import anchor missing")
            text = text.replace(marker, marker + "from app.web.spa import spa_file_response\n", 1)
    else:
        if "from app.web.spa import spa_file_response\n" not in text:
            marker = "from app.web.server import WebServerWorker\n"
            text = text.replace(marker, marker + "from app.web.spa import spa_file_response\n", 1)
    old = '''        @app.get("/{full_path:path}")\n        async def frontend(full_path: str) -> FileResponse:\n            candidate = frontend_dist / full_path\n            if full_path and candidate.is_file():\n                return FileResponse(candidate)\n            return FileResponse(frontend_dist / "index.html")\n'''
    new = '''        @app.get("/{full_path:path}")\n        async def frontend(full_path: str) -> FileResponse:\n            return spa_file_response(frontend_dist, full_path)\n'''
    if text.count(old) != 1:
        raise RuntimeError(f"{path}: SPA fallback block not found exactly once")
    write(path, text.replace(old, new, 1))

# WeChat inbound authorization: after first-user binding, only that sender can execute commands.
must_replace(
    "app/providers/wechat_clawbot/service.py",
    '''        if not message.from_user_id:\n            return\n        reply = await _command_reply(\n''',
    '''        if not message.from_user_id:\n            return\n        if account.user_id is not None and message.from_user_id != account.user_id:\n            logger.warning(\n                "wechat_clawbot_unauthorized_sender",\n                account_id=account.account_id,\n            )\n            return\n        reply = await _command_reply(\n''',
)

# Harden server-directed WeChat endpoints against arbitrary-host redirects/SSRF.
text = read("app/providers/wechat_clawbot/client.py")
text = text.replace("from typing import Any\n", "from typing import Any\nfrom urllib.parse import urlsplit\n", 1)
text = text.replace(
    '''        self._base_url = base_url.rstrip("/")\n''',
    '''        self._base_url = base_url.rstrip("/")\n        self._trust_host = urlsplit(self._base_url).hostname\n        if self._trust_host is None:\n            raise ValueError("WeChat base_url must include a hostname")\n''',
    1,
)
text = text.replace(
    '''        request_base_url = (base_url or self._base_url).rstrip("/")\n        client = self._client\n''',
    '''        request_base_url = self._validate_service_base_url(base_url or self._base_url)\n        client = self._client\n''',
    1,
)
# _post has the same assignment; replace its remaining occurrence.
text = text.replace(
    '''        request_base_url = (base_url or self._base_url).rstrip("/")\n        client = self._client\n''',
    '''        request_base_url = self._validate_service_base_url(base_url or self._base_url)\n        client = self._client\n''',
    1,
)
old_qr = '''        return WeChatQrStatus(\n            status=str(raw.get("status") or "wait"),\n            bot_token=_optional_str(raw.get("bot_token")),\n            account_id=_optional_str(raw.get("ilink_bot_id")),\n            base_url=_optional_str(raw.get("baseurl")),\n            user_id=_optional_str(raw.get("ilink_user_id")),\n            redirect_host=_optional_str(raw.get("redirect_host")),\n        )\n'''
new_qr = '''        server_base_url = _optional_str(raw.get("baseurl"))\n        if server_base_url is not None:\n            server_base_url = self._validate_service_base_url(server_base_url)\n        redirect_host = _optional_str(raw.get("redirect_host"))\n        if redirect_host is not None:\n            redirect_url = self._validate_service_base_url(f"https://{redirect_host}")\n            redirect_host = urlsplit(redirect_url).hostname\n        return WeChatQrStatus(\n            status=str(raw.get("status") or "wait"),\n            bot_token=_optional_str(raw.get("bot_token")),\n            account_id=_optional_str(raw.get("ilink_bot_id")),\n            base_url=server_base_url,\n            user_id=_optional_str(raw.get("ilink_user_id")),\n            redirect_host=redirect_host,\n        )\n'''
if text.count(old_qr) != 1:
    raise RuntimeError("wechat client QR block missing")
text = text.replace(old_qr, new_qr, 1)
method_anchor = '''    def _common_headers(self) -> dict[str, str]:\n'''
validate_method = '''    def _validate_service_base_url(self, value: str) -> str:\n        parsed = urlsplit(value.rstrip("/"))\n        configured = urlsplit(self._base_url)\n        if (\n            parsed.scheme != configured.scheme\n            or parsed.hostname is None\n            or parsed.username is not None\n            or parsed.password is not None\n            or parsed.query\n            or parsed.fragment\n        ):\n            raise WeChatClawBotError("untrusted WeChat service URL")\n        configured_host = self._trust_host.casefold()\n        candidate_host = parsed.hostname.casefold()\n        labels = configured_host.split(".")\n        trust_suffix = ".".join(labels[-3:]) if len(labels) >= 3 else configured_host\n        if candidate_host != configured_host and not candidate_host.endswith(f".{trust_suffix}"):\n            raise WeChatClawBotError("untrusted WeChat service host")\n        if parsed.port != configured.port:\n            default_port = 443 if parsed.scheme == "https" else 80\n            if parsed.port not in {None, default_port} or configured.port not in {None, default_port}:\n                raise WeChatClawBotError("untrusted WeChat service port")\n        return value.rstrip("/")\n\n'''
if method_anchor not in text:
    raise RuntimeError("wechat client common headers anchor missing")
text = text.replace(method_anchor, validate_method + method_anchor, 1)
write("app/providers/wechat_clawbot/client.py", text)

# Future odds: MISSING is retryable and can be upgraded in-place to CAPTURED.
text = read("app/evaluation/future_odds.py")
text = text.replace(
    '''        if existing is not None:\n            return existing\n        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)\n''',
    '''        if existing is not None and existing.status == "CAPTURED":\n            return existing\n        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)\n''',
    1,
)
old_time_record = '''        record = DecisionFutureOdds(\n            decision_snapshot_id=snapshot_id,\n            capture_type=FutureOddsCaptureType.TIME_HORIZON,\n            horizon_seconds=horizon_seconds,\n            triggered_at=due_at,\n            due_at=due_at,\n            observed_at=(max(item.received_at for item in captured) if complete else observed_at),\n            odds_a=captured[0].price if complete else None,\n            odds_b=captured[1].price if complete else None,\n            market_type=_market_value(snapshot, "market_type"),\n            match_stage=_market_value(snapshot, "match_stage"),\n            market_status=_market_status(snapshot),\n            capture_policy_version="time-horizon-v1",\n            status="CAPTURED" if complete else "MISSING",\n        )\n        session.add(record)\n        await session.flush()\n        return record\n'''
new_time_record = '''        values = {\n            "triggered_at": due_at,\n            "observed_at": max(item.received_at for item in captured) if complete else observed_at,\n            "odds_a": captured[0].price if complete else None,\n            "odds_b": captured[1].price if complete else None,\n            "market_type": _market_value(snapshot, "market_type"),\n            "match_stage": _market_value(snapshot, "match_stage"),\n            "market_status": _market_status(snapshot),\n            "capture_policy_version": "time-horizon-v1",\n            "status": "CAPTURED" if complete else "MISSING",\n        }\n        if existing is None:\n            record = DecisionFutureOdds(\n                decision_snapshot_id=snapshot_id,\n                capture_type=FutureOddsCaptureType.TIME_HORIZON,\n                horizon_seconds=horizon_seconds,\n                due_at=due_at,\n                **values,\n            )\n            session.add(record)\n        else:\n            record = existing\n            for field, value in values.items():\n                setattr(record, field, value)\n        await session.flush()\n        return record\n'''
if text.count(old_time_record) != 1:
    raise RuntimeError("future odds time record block missing")
text = text.replace(old_time_record, new_time_record, 1)
text = text.replace(
    '''        if existing is not None:\n            return existing\n        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)\n''',
    '''        if existing is not None and existing.status == "CAPTURED":\n            return existing\n        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)\n''',
    1,
)
old_closing_record = '''        record = DecisionFutureOdds(\n            decision_snapshot_id=snapshot_id,\n            capture_type=FutureOddsCaptureType.CLOSING,\n            horizon_seconds=None,\n            triggered_at=triggered_at,\n            due_at=triggered_at,\n            observed_at=(max(item.received_at for item in captured) if complete else triggered_at),\n            odds_a=captured[0].price if complete else None,\n            odds_b=captured[1].price if complete else None,\n            market_type=market_type if isinstance(market_type, str) else None,\n            match_stage=match_stage if isinstance(match_stage, str) else None,\n            market_status=status,\n            capture_policy_version=CLOSING_POLICY_VERSION,\n            pair_quality=(\n                quality.model_dump(mode="json")\n                if quality is not None\n                else {\n                    "eligible": False,\n                    "blockers": ["MARKET_PAIR_IDENTITY_INVALID"],\n                    "warnings": [],\n                }\n            ),\n            pair_skew_seconds=quality.pair_skew_seconds if quality is not None else None,\n            status="CAPTURED" if complete else "MISSING",\n        )\n        session.add(record)\n        await session.flush()\n        return record\n'''
new_closing_record = '''        values = {\n            "triggered_at": triggered_at,\n            "observed_at": max(item.received_at for item in captured) if complete else triggered_at,\n            "odds_a": captured[0].price if complete else None,\n            "odds_b": captured[1].price if complete else None,\n            "market_type": market_type if isinstance(market_type, str) else None,\n            "match_stage": match_stage if isinstance(match_stage, str) else None,\n            "market_status": status,\n            "capture_policy_version": CLOSING_POLICY_VERSION,\n            "pair_quality": (\n                quality.model_dump(mode="json")\n                if quality is not None\n                else {\n                    "eligible": False,\n                    "blockers": ["MARKET_PAIR_IDENTITY_INVALID"],\n                    "warnings": [],\n                }\n            ),\n            "pair_skew_seconds": quality.pair_skew_seconds if quality is not None else None,\n            "status": "CAPTURED" if complete else "MISSING",\n        }\n        if existing is None:\n            record = DecisionFutureOdds(\n                decision_snapshot_id=snapshot_id,\n                capture_type=FutureOddsCaptureType.CLOSING,\n                horizon_seconds=None,\n                due_at=triggered_at,\n                **values,\n            )\n            session.add(record)\n        else:\n            record = existing\n            for field, value in values.items():\n                setattr(record, field, value)\n        await session.flush()\n        return record\n'''
if text.count(old_closing_record) != 1:
    raise RuntimeError("future odds closing record block missing")
text = text.replace(old_closing_record, new_closing_record, 1)
write("app/evaluation/future_odds.py", text)

# Closing captures belong to MAP_ENDED, not MAP_STARTED.
must_replace(
    "app/events/dispatcher.py",
    "            if event_type is DomainEventType.MAP_STARTED:\n                await self._enqueue_closing_captures(session, record)\n",
    "            if event_type is DomainEventType.MAP_ENDED:\n                await self._enqueue_closing_captures(session, record)\n",
)

# Durable reconciliation may explicitly reopen terminal jobs without erasing attempt history.
replace_between(
    "app/jobs/repository.py",
    "    async def enqueue(\n",
    "    async def claim(\n",
    '''    async def enqueue(\n        self,\n        session: AsyncSession,\n        *,\n        job_type: JobType,\n        dedupe_key: str,\n        payload: dict[str, Any],\n        priority: int = 100,\n        not_before: datetime | None = None,\n        max_attempts: int = 8,\n        reopen_terminal: bool = False,\n        reopen_attempts: int = 3,\n    ) -> UUID:\n        due = not_before or utc_now()\n        if reopen_attempts < 1:\n            raise ValueError("reopen_attempts must be positive")\n        dialect = session.get_bind().dialect.name\n        if dialect == "postgresql":\n            statement = (\n                pg_insert(DurableJobRecord)\n                .values(\n                    job_type=job_type.value,\n                    dedupe_key=dedupe_key,\n                    payload=payload,\n                    status=JobStatus.PENDING.value,\n                    priority=priority,\n                    not_before=due,\n                    max_attempts=max_attempts,\n                )\n                .on_conflict_do_nothing(index_elements=["job_type", "dedupe_key"])\n                .returning(DurableJobRecord.id)\n            )\n            created_id = await session.scalar(statement)\n            if created_id is not None:\n                return created_id\n\n        existing = await session.scalar(\n            select(DurableJobRecord)\n            .where(\n                DurableJobRecord.job_type == job_type.value,\n                DurableJobRecord.dedupe_key == dedupe_key,\n            )\n            .with_for_update()\n        )\n        if existing is not None:\n            if reopen_terminal and existing.status == JobStatus.FAILED_TERMINAL.value:\n                existing.status = JobStatus.PENDING.value\n                existing.not_before = due\n                existing.completed_at = None\n                existing.locked_by = None\n                existing.locked_at = None\n                existing.last_error = None\n                existing.max_attempts = max(\n                    existing.max_attempts, existing.attempt_count + reopen_attempts\n                )\n                await session.flush()\n            return existing.id\n\n        record = DurableJobRecord(\n            job_type=job_type.value,\n            dedupe_key=dedupe_key,\n            payload=payload,\n            status=JobStatus.PENDING.value,\n            priority=priority,\n            not_before=due,\n            max_attempts=max_attempts,\n        )\n        session.add(record)\n        await session.flush()\n        return record.id\n\n''',
)

# Reconciliation: reopen terminal intents, retry MISSING future odds in bounded generations,
# keep AI recovery version-safe, and bound live-only scans.
text = read("app/jobs/reconciliation.py")
text = text.replace("from app.domain.jobs import JobType\n", "from app.domain.jobs import JobStatus, JobType\n", 1)
text = text.replace("        ai_jobs = await self._reconcile_ai(session)\n", "        ai_jobs = await self._reconcile_ai(session, now=now)\n", 1)
text = text.replace(
    "        future_jobs = await self._reconcile_future_odds(session)\n",
    "        future_jobs = await self._reconcile_future_odds(session, now=now)\n",
    1,
)
text = text.replace(
    '                        dedupe_key=f"checkpoint-real:{canonical_map.id}:{minute}",\n',
    '                        dedupe_key=f"checkpoint:{canonical_map.id}:{minute}",\n',
    1,
)
# Fixed reconciliation keys can explicitly reopen terminal attempts.
text = text.replace(
    '''                payload={\n                    "canonical_map_id": str(draft.canonical_map_id),\n                    "draft_snapshot_id": str(draft.id),\n                },\n            )\n''',
    '''                payload={\n                    "canonical_map_id": str(draft.canonical_map_id),\n                    "draft_snapshot_id": str(draft.id),\n                },\n                reopen_terminal=True,\n            )\n''',
    1,
)
# Snapshot terminal replay: reopen the same audited replay job.
old_snapshot_existing = '''                if existing is not None:\n                    if existing.status in {"PENDING", "RUNNING", "RETRY_WAIT"}:\n                        break\n                    continue\n                await self._jobs.enqueue(\n                    session,\n                    job_type=JobType.BUILD_SNAPSHOT,\n                    dedupe_key=dedupe_key,\n                    payload={\n                        "canonical_map_id": canonical_map_id,\n                        "canonical_series_id": payload.get("canonical_series_id"),\n                        "decision_at": decision_at_value.isoformat(),\n                        "reconciliation_event_id": str(event.id),\n                    },\n                )\n                created += 1\n                break\n'''
new_snapshot_existing = '''                job_payload = {\n                    "canonical_map_id": canonical_map_id,\n                    "canonical_series_id": payload.get("canonical_series_id"),\n                    "decision_at": decision_at_value.isoformat(),\n                    "reconciliation_event_id": str(event.id),\n                }\n                if existing is not None:\n                    if existing.status in {"PENDING", "RUNNING", "RETRY_WAIT"}:\n                        break\n                    if existing.status == JobStatus.FAILED_TERMINAL.value:\n                        await self._jobs.enqueue(\n                            session,\n                            job_type=JobType.BUILD_SNAPSHOT,\n                            dedupe_key=dedupe_key,\n                            payload=job_payload,\n                            reopen_terminal=True,\n                        )\n                        created += 1\n                        break\n                    continue\n                await self._jobs.enqueue(\n                    session,\n                    job_type=JobType.BUILD_SNAPSHOT,\n                    dedupe_key=dedupe_key,\n                    payload=job_payload,\n                )\n                created += 1\n                break\n'''
if text.count(old_snapshot_existing) != 1:
    raise RuntimeError("reconciliation snapshot terminal block missing")
text = text.replace(old_snapshot_existing, new_snapshot_existing, 1)
write("app/jobs/reconciliation.py", text)

replace_between(
    "app/jobs/reconciliation.py",
    "    async def _reconcile_ai(",
    "    async def _reconcile_future_odds(",
    '''    async def _reconcile_ai(self, session: AsyncSession, *, now: datetime) -> int:\n        """Recover virgin snapshots and terminal jobs for the current experiment only.\n\n        A snapshot with an AI record or a job for another experiment version is\n        still left alone. This preserves the no-implicit-historical-replay rule.\n        """\n        if not self._ai_experiments:\n            return 0\n        snapshots = list(\n            (\n                await session.scalars(\n                    select(DecisionSnapshotRecord)\n                    .where(DecisionSnapshotRecord.decision_at >= now - timedelta(hours=24))\n                    .order_by(DecisionSnapshotRecord.decision_at.asc())\n                    .limit(1000)\n                )\n            ).all()\n        )\n        created = 0\n        for snapshot in snapshots:\n            if not ai_record_is_game_time_eligible(\n                snapshot.canonical_payload,\n                min_game_time_seconds=self._ai_min_game_time_seconds,\n            ):\n                continue\n            any_record = await session.scalar(\n                select(AiDecisionRecord.id)\n                .where(AiDecisionRecord.snapshot_id == snapshot.id)\n                .limit(1)\n            )\n            if any_record is not None:\n                continue\n            existing_jobs = list(\n                (\n                    await session.scalars(\n                        select(DurableJobRecord).where(\n                            DurableJobRecord.job_type == JobType.RUN_AI_PROVIDER.value,\n                            DurableJobRecord.dedupe_key.like(f"ai:{snapshot.snapshot_hash}%"),\n                        )\n                    )\n                ).all()\n            )\n            if existing_jobs:\n                by_key = {job.dedupe_key: job for job in existing_jobs}\n                for experiment in self._ai_experiments:\n                    provider, model = experiment[:2]\n                    dedupe_key = ai_job_dedupe_key_for_experiment(snapshot.snapshot_hash, experiment)\n                    existing = by_key.get(dedupe_key)\n                    if existing is None or existing.status != JobStatus.FAILED_TERMINAL.value:\n                        continue\n                    await self._jobs.enqueue(\n                        session,\n                        job_type=JobType.RUN_AI_PROVIDER,\n                        dedupe_key=dedupe_key,\n                        payload=ai_job_payload(snapshot.id, provider, model),\n                        priority=150,\n                        reopen_terminal=True,\n                    )\n                    created += 1\n                continue\n            for experiment in self._ai_experiments:\n                provider, model = experiment[:2]\n                await self._jobs.enqueue(\n                    session,\n                    job_type=JobType.RUN_AI_PROVIDER,\n                    dedupe_key=ai_job_dedupe_key_for_experiment(\n                        snapshot.snapshot_hash,\n                        experiment,\n                    ),\n                    payload=ai_job_payload(snapshot.id, provider, model),\n                    priority=150,\n                )\n                created += 1\n        return created\n\n''',
)

replace_between(
    "app/jobs/reconciliation.py",
    "    async def _reconcile_future_odds(",
    "    async def _reconcile_settlements(",
    '''    async def _reconcile_future_odds(self, session: AsyncSession, *, now: datetime) -> int:\n        """Recover recent live captures without turning MISSING into a permanent tombstone."""\n        snapshots = list(\n            (\n                await session.scalars(\n                    select(DecisionSnapshotRecord)\n                    .where(DecisionSnapshotRecord.decision_at >= now - timedelta(hours=12))\n                    .order_by(DecisionSnapshotRecord.decision_at.asc())\n                    .limit(1000)\n                )\n            ).all()\n        )\n        if not snapshots:\n            return 0\n        snapshot_ids = [item.id for item in snapshots]\n        rows = list(\n            (\n                await session.scalars(\n                    select(DecisionFutureOdds).where(\n                        DecisionFutureOdds.decision_snapshot_id.in_(snapshot_ids)\n                    )\n                )\n            ).all()\n        )\n        by_snapshot: dict[UUID, list[DecisionFutureOdds]] = {}\n        for row in rows:\n            by_snapshot.setdefault(row.decision_snapshot_id, []).append(row)\n\n        retry_window = timedelta(minutes=30)\n        bucket = int(now.timestamp()) // 300\n        map_end_cache: dict[UUID, datetime | None] = {}\n        created = 0\n        for snapshot in snapshots:\n            captures = by_snapshot.get(snapshot.id, [])\n            for horizon in self._future_odds_horizons:\n                due_at = snapshot.decision_at + timedelta(seconds=horizon)\n                existing = next(\n                    (\n                        item\n                        for item in captures\n                        if item.capture_type == "TIME_HORIZON"\n                        and item.horizon_seconds == horizon\n                        and item.due_at == due_at\n                    ),\n                    None,\n                )\n                if existing is not None and existing.status == "CAPTURED":\n                    continue\n                if now > due_at + retry_window:\n                    continue\n                dedupe_key = (\n                    f"future-odds-retry:{snapshot.id}:{horizon}:{bucket}"\n                    if existing is not None and existing.status == "MISSING" and now >= due_at\n                    else f"future-odds:{snapshot.id}:{horizon}"\n                )\n                await self._jobs.enqueue(\n                    session,\n                    job_type=JobType.CAPTURE_FUTURE_ODDS,\n                    dedupe_key=dedupe_key,\n                    payload={\n                        "snapshot_id": str(snapshot.id),\n                        "capture_type": "TIME_HORIZON",\n                        "horizon_seconds": horizon,\n                        "due_at": due_at.isoformat(),\n                    },\n                    not_before=max(due_at, now) if existing is not None else due_at,\n                    reopen_terminal=True,\n                )\n                created += 1\n\n            if snapshot.canonical_map_id is None:\n                continue\n            if snapshot.canonical_map_id not in map_end_cache:\n                map_ended_at = await session.scalar(\n                    select(DomainEventRecord.occurred_at)\n                    .where(\n                        DomainEventRecord.event_type == DomainEventType.MAP_ENDED.value,\n                        DomainEventRecord.aggregate_id == str(snapshot.canonical_map_id),\n                    )\n                    .order_by(DomainEventRecord.occurred_at.asc())\n                    .limit(1)\n                )\n                if map_ended_at is None:\n                    map_ended_at = await session.scalar(\n                        select(MapResultRecord.basic_first_usable_at).where(\n                            MapResultRecord.canonical_map_id == snapshot.canonical_map_id\n                        )\n                    )\n                map_end_cache[snapshot.canonical_map_id] = map_ended_at\n            triggered_at = map_end_cache[snapshot.canonical_map_id]\n            if triggered_at is None or triggered_at < snapshot.decision_at:\n                continue\n            closing = next(\n                (item for item in captures if item.capture_type == "CLOSING"),\n                None,\n            )\n            if closing is not None and closing.status == "CAPTURED":\n                continue\n            if now < triggered_at or now > triggered_at + retry_window:\n                continue\n            dedupe_key = (\n                f"closing-odds-retry:{snapshot.id}:{bucket}"\n                if closing is not None and closing.status == "MISSING"\n                else f"closing-odds:{snapshot.id}"\n            )\n            await self._jobs.enqueue(\n                session,\n                job_type=JobType.CAPTURE_FUTURE_ODDS,\n                dedupe_key=dedupe_key,\n                payload={\n                    "snapshot_id": str(snapshot.id),\n                    "capture_type": "CLOSING",\n                    "triggered_at": triggered_at.isoformat(),\n                },\n                not_before=max(triggered_at, now),\n                reopen_terminal=True,\n            )\n            created += 1\n        return created\n\n''',
)

# Settlement/evaluation reconciliation can reopen a terminal fixed-key job.
text = read("app/jobs/reconciliation.py")
text = text.replace(
    '''                payload={"canonical_map_id": str(fact.canonical_map_id)},\n            )\n''',
    '''                payload={"canonical_map_id": str(fact.canonical_map_id)},\n                reopen_terminal=True,\n            )\n''',
    1,
)
text = text.replace(
    '''                payload={"snapshot_id": str(snapshot.id)},\n            )\n            created_snapshots.add(snapshot.id)\n''',
    '''                payload={"snapshot_id": str(snapshot.id)},\n                reopen_terminal=True,\n            )\n            created_snapshots.add(snapshot.id)\n''',
    1,
)
write("app/jobs/reconciliation.py", text)

# Unify checkpoint idempotency across broadcast-time and real-time basis.
must_replace(
    "app/snapshots/triggers.py",
    '                    dedupe_key=f"checkpoint-real:{canonical_map_id}:{minute}",\n',
    '                    dedupe_key=f"checkpoint:{canonical_map_id}:{minute}",\n',
)

# AI view identity has one source of truth.
write("app/ai/versions.py", 'AI_VIEW_VERSION = "ai-view-v6"\n')
must_replace(
    "app/ai/input.py",
    "from app.ai.view import build_ai_view\n",
    "from app.ai.versions import AI_VIEW_VERSION\nfrom app.ai.view import build_ai_view\n",
)
must_replace("app/ai/input.py", '\nAI_VIEW_VERSION = "ai-view-v6"\n', "\n")
must_replace(
    "app/ai/view.py",
    "from app.ai.dota_items import DOTA_ITEM_NAMES\n",
    "from app.ai.dota_items import DOTA_ITEM_NAMES\nfrom app.ai.versions import AI_VIEW_VERSION\n",
)
must_replace("app/ai/view.py", '\nAI_VIEW_VERSION = "ai-view-v2"\n', "\n")

# Lease-renewal failure is a distinct fast-fail path, not fake lease loss or worker death.
text = read("app/jobs/runner.py")
if "import structlog\n" not in text:
    text = text.replace("import asyncio\n", "import asyncio\n\nimport structlog\n", 1)
text = text.replace("JobHandler = Callable[[DurableJob], Awaitable[None]]\n", "JobHandler = Callable[[DurableJob], Awaitable[None]]\n\nlogger = structlog.get_logger()\n", 1)
text = text.replace(
    '''            await self._execute(job, worker_id)\n''',
    '''            try:\n                await self._execute(job, worker_id)\n            except Exception as exc:\n                logger.exception(\n                    "durable_job_worker_error",\n                    worker_id=worker_id,\n                    job_id=str(job.id),\n                    job_type=job.job_type.value,\n                    error=f"{type(exc).__name__}: {exc}",\n                )\n                try:\n                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)\n                except TimeoutError:\n                    pass\n''',
    1,
)
write("app/jobs/runner.py", text)
replace_between(
    "app/jobs/runner.py",
    "    async def _execute(",
    "    async def _mark_failed(",
    '''    async def _execute(self, job: DurableJob, worker_id: str | None = None) -> None:\n        owner_id = worker_id or self._worker_id\n        handler = self._handlers.get(job.job_type)\n        if handler is None:\n            await self._mark_failed(\n                job,\n                f"no handler registered for {job.job_type.value}",\n                owner_id,\n            )\n            return\n        renewal_stop = asyncio.Event()\n        handler_task = asyncio.create_task(handler(job))\n        renewal_task = asyncio.create_task(self._renew_lease(job, renewal_stop, owner_id))\n        lease_lost = False\n        renewal_error: Exception | None = None\n        try:\n            done, _pending = await asyncio.wait(\n                (handler_task, renewal_task),\n                return_when=asyncio.FIRST_COMPLETED,\n            )\n            if renewal_task in done:\n                try:\n                    renewal_task.result()\n                except LeaseOwnershipLost:\n                    lease_lost = True\n                except Exception as exc:\n                    renewal_error = exc\n                if lease_lost or renewal_error is not None:\n                    handler_task.cancel()\n        except asyncio.CancelledError:\n            handler_task.cancel()\n            if not lease_lost:\n                await self._mark_failed(job, "worker shutdown during job execution", owner_id)\n            raise\n        finally:\n            renewal_stop.set()\n            if not renewal_task.done():\n                try:\n                    await renewal_task\n                except LeaseOwnershipLost:\n                    lease_lost = True\n                except Exception as exc:\n                    renewal_error = renewal_error or exc\n\n        if renewal_error is not None:\n            try:\n                await handler_task\n            except asyncio.CancelledError:\n                pass\n            except Exception:\n                pass\n            await self._mark_failed(\n                job,\n                f"lease renewal failed: {type(renewal_error).__name__}: {renewal_error}",\n                owner_id,\n            )\n            return\n        try:\n            await handler_task\n        except asyncio.CancelledError:\n            if lease_lost:\n                return\n            raise\n        except Exception as exc:\n            if lease_lost:\n                return\n            await self._mark_failed(job, f"{type(exc).__name__}: {exc}", owner_id)\n            return\n        if lease_lost:\n            return\n        async with self._session_factory() as session, session.begin():\n            await self._repository.succeed(\n                session,\n                job_id=job.id,\n                worker_id=owner_id,\n            )\n\n''',
)

# Remove the dead BaseSnapshotBuilder.build implementation; subclasses reuse only loaders/helpers.
replace_between(
    "app/snapshots/builder.py",
    "    async def build(\n",
    "    async def _load_market(\n",
    "",
)

# Serialize provider rate-limit checks so concurrent workers cannot burst through the interval.
must_replace(
    "app/providers/opendota/client.py",
    "        self._last_request_at: datetime | None = None\n        self._min_request_interval_seconds = 60.0 / 30.0\n",
    "        self._last_request_at: datetime | None = None\n        self._min_request_interval_seconds = 60.0 / 30.0\n        self._request_lock = asyncio.Lock()\n",
)
old_get = '''    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> TimedPayload:\n        if self._last_request_at is not None:\n            elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()\n            if elapsed < self._min_request_interval_seconds:\n                await asyncio.sleep(self._min_request_interval_seconds - elapsed)\n        result = await self._request(path, params=params)\n        self._last_request_at = datetime.now(UTC)\n        return result\n'''
new_get = '''    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> TimedPayload:\n        async with self._request_lock:\n            if self._last_request_at is not None:\n                elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()\n                if elapsed < self._min_request_interval_seconds:\n                    await asyncio.sleep(self._min_request_interval_seconds - elapsed)\n            result = await self._request(path, params=params)\n            self._last_request_at = datetime.now(UTC)\n            return result\n'''
must_replace("app/providers/opendota/client.py", old_get, new_get)
must_replace(
    "app/providers/stratz/client.py",
    "        self._last_request_at: datetime | None = None\n        self._min_request_interval_seconds = 0.4\n",
    "        self._last_request_at: datetime | None = None\n        self._min_request_interval_seconds = 0.4\n        self._request_lock = asyncio.Lock()\n",
)
old_execute = '''    async def execute(\n        self,\n        *,\n        operation_name: str,\n        query: str,\n        variables: dict[str, Any],\n    ) -> TimedPayload:\n        if self._last_request_at is not None:\n            elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()\n            if elapsed < self._min_request_interval_seconds:\n                await asyncio.sleep(self._min_request_interval_seconds - elapsed)\n        started = datetime.now(UTC)\n        response = await self._client.post(\n            self._endpoint,\n            json={\n                "operationName": operation_name,\n                "query": query,\n                "variables": variables,\n            },\n        )\n        self._last_request_at = datetime.now(UTC)\n        received = self._last_request_at\n        response.raise_for_status()\n        payload = response.json()\n        if not isinstance(payload, dict):\n            raise ValueError("STRATZ response must be a JSON object")\n        return TimedPayload(\n            payload=payload,\n            request_started_at=started,\n            received_at=received,\n        )\n'''
new_execute = '''    async def execute(\n        self,\n        *,\n        operation_name: str,\n        query: str,\n        variables: dict[str, Any],\n    ) -> TimedPayload:\n        async with self._request_lock:\n            if self._last_request_at is not None:\n                elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()\n                if elapsed < self._min_request_interval_seconds:\n                    await asyncio.sleep(self._min_request_interval_seconds - elapsed)\n            started = datetime.now(UTC)\n            response = await self._client.post(\n                self._endpoint,\n                json={\n                    "operationName": operation_name,\n                    "query": query,\n                    "variables": variables,\n                },\n            )\n            self._last_request_at = datetime.now(UTC)\n            received = self._last_request_at\n            response.raise_for_status()\n            payload = response.json()\n            if not isinstance(payload, dict):\n                raise ValueError("STRATZ response must be a JSON object")\n            return TimedPayload(\n                payload=payload,\n                request_started_at=started,\n                received_at=received,\n            )\n'''
must_replace("app/providers/stratz/client.py", old_execute, new_execute)

# Do not invent a BO-series map number when historical identity cannot be correlated.
must_replace("app/history/repository.py", "            map_number=1,\n            valve_match_id=valve_match_id,\n", "            map_number=None,\n            valve_match_id=valve_match_id,\n")

# Bound map-detail checkpoint history; the dedicated review API is the long-horizon view.
must_replace(
    "app/web/api.py",
    '''                .where(DecisionSnapshotRecord.canonical_map_id == canonical_map.id)\n                .order_by(DecisionSnapshotRecord.decision_at.desc())\n            )\n''',
    '''                .where(DecisionSnapshotRecord.canonical_map_id == canonical_map.id)\n                .order_by(DecisionSnapshotRecord.decision_at.desc())\n                .limit(200)\n            )\n''',
)

# EventHub remains lossy by design for live UI fan-out, but dropped events are now observable.
must_replace(
    "app/events/hub.py",
    "        self._subscribers: set[asyncio.Queue] = set()\n",
    "        self._subscribers: set[asyncio.Queue] = set()\n        self._dropped_events = 0\n",
)
must_replace(
    "app/events/hub.py",
    "            except asyncio.QueueFull:\n                continue\n\n    def subscribe",
    "            except asyncio.QueueFull:\n                self._dropped_events += 1\n                continue\n\n    @property\n    def dropped_events(self) -> int:\n        return self._dropped_events\n\n    def subscribe",
)

# Frontend: route-level split for review and malformed websocket payload isolation.
text = read("frontend/src/App.tsx")
text = text.replace('import React, { useState } from "react";\n', 'import React, { lazy, Suspense, useState } from "react";\n', 1)
text = text.replace('import { ReviewPage } from "./components/ReviewPage";\n', 'const ReviewPage = lazy(() => import("./components/ReviewPage").then((module) => ({ default: module.ReviewPage })));\n', 1)
text = text.replace(
    '      {reviewRoute ? <ReviewPage /> : <DashboardApp />}\n',
    '      {reviewRoute ? <Suspense fallback={null}><ReviewPage /></Suspense> : <DashboardApp />}\n',
    1,
)
write("frontend/src/App.tsx", text)
must_replace(
    "frontend/src/api.ts",
    '''      socket.onmessage = (event) => {\n        queryClient.setQueryData(queryKeys.runtime, JSON.parse(event.data));\n      };\n''',
    '''      socket.onmessage = (event) => {\n        try {\n          queryClient.setQueryData(queryKeys.runtime, JSON.parse(event.data));\n        } catch {\n          // Ignore one malformed frame; the next 2s runtime frame will recover the view.\n        }\n      };\n''',
)

# Tests: runtime startup path, static path containment, retry semantics, auth, versions, dedupe.
write(
    "tests/test_web_static_security.py",
    '''from pathlib import Path\n\nimport pytest\nfrom httpx import ASGITransport, AsyncClient\nfrom sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n\nfrom app.db import Base\nfrom app.runtime.health import HealthRegistry\nfrom app.web import create_app\nfrom app.web.spa import spa_file_response\n\n\ndef test_spa_file_response_never_escapes_frontend_dist(tmp_path: Path) -> None:\n    dist = tmp_path / "frontend" / "dist"\n    dist.mkdir(parents=True)\n    (dist / "index.html").write_text("INDEX", encoding="utf-8")\n    secret = tmp_path / "secret.env"\n    secret.write_text("TOP_SECRET", encoding="utf-8")\n\n    response = spa_file_response(dist, "../../secret.env")\n    assert Path(response.path).resolve() == (dist / "index.html").resolve()\n\n\n@pytest.mark.asyncio\nasync def test_spa_encoded_traversal_falls_back_to_index(tmp_path: Path) -> None:\n    dist = tmp_path / "frontend" / "dist"\n    dist.mkdir(parents=True)\n    (dist / "index.html").write_text("INDEX", encoding="utf-8")\n    (tmp_path / "secret.env").write_text("TOP_SECRET", encoding="utf-8")\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    app = create_app(async_sessionmaker(engine, expire_on_commit=False), HealthRegistry(), frontend_dist=dist)\n    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:\n        for path in ("/..%2F..%2Fsecret.env", "/%2e%2e/%2e%2e/secret.env", "/..%5C..%5Csecret.env"):\n            response = await client.get(path)\n            assert response.status_code == 200\n            assert response.text == "INDEX"\n            assert "TOP_SECRET" not in response.text\n    await engine.dispose()\n''',
)

write(
    "tests/test_runtime_startup_smoke.py",
    '''import asyncio\nimport os\nimport socket\n\nimport httpx\nimport pytest\n\nfrom app.config import Settings\nfrom app import main as runtime_main\n\n\ndef _free_port() -> int:\n    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:\n        sock.bind(("127.0.0.1", 0))\n        return int(sock.getsockname()[1])\n\n\n@pytest.mark.asyncio\nasync def test_main_run_starts_web_runtime_and_stops_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:\n    database_url = os.environ.get("DATABASE_URL")\n    if not database_url:\n        pytest.skip("runtime smoke requires the CI PostgreSQL DATABASE_URL")\n    port = _free_port()\n    settings = Settings(\n        _env_file=None,\n        database_url=database_url,\n        auto_migrate=False,\n        run_provider_workers=False,\n        wechat_clawbot_enabled=False,\n        email_notifications_enabled=False,\n        host="127.0.0.1",\n        port=port,\n        log_level="WARNING",\n        ai_min_game_time_seconds=777,\n    )\n    monkeypatch.setattr(runtime_main, "get_settings", lambda: settings)\n    probe_error: list[BaseException] = []\n\n    def install_probe(shutdown: asyncio.Event) -> None:\n        async def probe() -> None:\n            try:\n                async with httpx.AsyncClient(timeout=0.5) as client:\n                    for _ in range(80):\n                        try:\n                            health = await client.get(f"http://127.0.0.1:{port}/health")\n                            runtime = await client.get(f"http://127.0.0.1:{port}/api/runtime")\n                            if health.status_code == 200 and runtime.status_code == 200:\n                                assert health.json()["status"] == "RUNNING"\n                                return\n                        except (httpx.ConnectError, httpx.ReadError):\n                            pass\n                        await asyncio.sleep(0.05)\n                raise AssertionError("runtime web server never became healthy")\n            except BaseException as exc:\n                probe_error.append(exc)\n            finally:\n                shutdown.set()\n\n        asyncio.create_task(probe())\n\n    monkeypatch.setattr(runtime_main, "_install_signal_handlers", install_probe)\n    await asyncio.wait_for(runtime_main.run(), timeout=15)\n    assert not probe_error, repr(probe_error[0]) if probe_error else ""\n''',
)

write(
    "tests/test_checkpoint_dedupe.py",
    '''from datetime import UTC, datetime\nfrom uuid import uuid4\n\nimport pytest\nfrom sqlalchemy import func, select\nfrom sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n\nfrom app.db import Base\nfrom app.events.outbox import EventRepository\nfrom app.models import DomainEventRecord\nfrom app.snapshots.triggers import record_crossed_checkpoints\n\n\n@pytest.mark.asyncio\nasync def test_real_time_basis_cannot_duplicate_existing_game_time_checkpoint() -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    map_id = uuid4()\n    observed_at = datetime(2026, 8, 16, tzinfo=UTC)\n    events = EventRepository()\n    async with factory() as session, session.begin():\n        await record_crossed_checkpoints(\n            session,\n            events,\n            canonical_map_id=map_id,\n            previous_game_time=599,\n            current_game_time=600,\n            checkpoint_minutes=(10,),\n            observed_at=observed_at,\n        )\n        await record_crossed_checkpoints(\n            session,\n            events,\n            canonical_map_id=map_id,\n            previous_game_time=600,\n            current_game_time=600,\n            checkpoint_minutes=(10,),\n            observed_at=observed_at,\n            previous_real_elapsed_seconds=599,\n            real_elapsed_seconds=600,\n        )\n    async with factory() as session:\n        count = await session.scalar(\n            select(func.count()).select_from(DomainEventRecord).where(\n                DomainEventRecord.aggregate_id == str(map_id)\n            )\n        )\n        assert count == 1\n    await engine.dispose()\n''',
)

write(
    "tests/test_ai_view_version.py",
    '''from app.ai.input import AI_VIEW_VERSION as INPUT_VERSION\nfrom app.ai.versions import AI_VIEW_VERSION\nfrom app.ai.view import AI_VIEW_VERSION as VIEW_VERSION\n\n\ndef test_ai_view_version_has_one_source_of_truth() -> None:\n    assert INPUT_VERSION == VIEW_VERSION == AI_VIEW_VERSION == "ai-view-v6"\n''',
)

# Append focused regressions to existing suites.
wechat_tests = read("tests/test_wechat_clawbot.py")
if "test_bound_wechat_account_ignores_unrelated_sender" not in wechat_tests:
    wechat_tests = wechat_tests.replace(
        "from app.providers.wechat_clawbot.models import WeChatAccount\n",
        "from app.providers.wechat_clawbot.models import WeChatAccount, WeChatInboundMessage\n",
        1,
    )
    wechat_tests += '''\n\n@pytest.mark.asyncio\nasync def test_bound_wechat_account_ignores_unrelated_sender(tmp_path: Path) -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    sent: list[str] = []\n\n    def handler(request: httpx.Request) -> httpx.Response:\n        sent.append(str(request.url))\n        return httpx.Response(200, json={"ret": 0})\n\n    store = WeChatClawBotStore(tmp_path)\n    account = _account(tmp_path, user_id="owner-user")\n    store.save_account(account)\n    client = WeChatClawBotClient(\n        client=httpx.AsyncClient(\n            base_url="https://ilinkai.weixin.qq.com",\n            transport=httpx.MockTransport(handler),\n        )\n    )\n    service = WeChatClawBotService(\n        client=client,\n        store=store,\n        session_factory=factory,\n        jobs=JobRepository(),\n    )\n    async with factory() as session:\n        await service._handle_message(\n            session,\n            account,\n            WeChatInboundMessage(from_user_id="attacker-user", text="暂停通知"),\n        )\n    assert store.decision_notifications_enabled() is True\n    assert sent == []\n    await client.close()\n    await engine.dispose()\n\n\n@pytest.mark.asyncio\nasync def test_wechat_qr_rejects_untrusted_server_redirect() -> None:\n    def handler(_: httpx.Request) -> httpx.Response:\n        return httpx.Response(\n            200,\n            json={\n                "status": "confirmed",\n                "bot_token": "token",\n                "ilink_bot_id": "bot",\n                "baseurl": "https://evil.example",\n            },\n        )\n\n    client = WeChatClawBotClient(\n        client=httpx.AsyncClient(\n            base_url="https://ilinkai.weixin.qq.com",\n            transport=httpx.MockTransport(handler),\n        )\n    )\n    with pytest.raises(Exception, match="untrusted WeChat service host"):\n        await client.poll_qr_status("qr")\n    await client.close()\n'''
    write("tests/test_wechat_clawbot.py", wechat_tests)

eval_tests = read("tests/test_evaluation.py")
if "test_missing_future_odds_can_upgrade_to_captured" not in eval_tests:
    eval_tests += '''\n\n@pytest.mark.asyncio\nasync def test_missing_future_odds_can_upgrade_to_captured() -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    decision_at = datetime(2026, 8, 16, tzinfo=UTC)\n    due_at = decision_at + timedelta(seconds=30)\n    service = FutureOddsService(JobRepository())\n    async with factory() as session, session.begin():\n        snapshot = await SnapshotRepository().persist(\n            session,\n            canonical_map_id=None,\n            decision_at=decision_at,\n            mode="PREMATCH",\n            identity={},\n            market={"observations": [{"odds_id": 10}, {"odds_id": 20}]},\n            draft=None,\n            history={},\n            live=None,\n            quality={"eligible": True},\n        )\n        missing = await service.capture(\n            session,\n            snapshot_id=snapshot.snapshot_id,\n            horizon_seconds=30,\n            due_at=due_at,\n            observed_at=due_at + timedelta(seconds=1),\n        )\n        assert missing.status == "MISSING"\n        missing_id = missing.id\n        for odds_id, price in ((10, "1.90"), (20, "2.10")):\n            session.add(\n                OddsObservationRecord(\n                    provider_match_id=1,\n                    odds_id=odds_id,\n                    price=Decimal(price),\n                    implied_probability=1 / float(price),\n                    received_at=due_at + timedelta(seconds=2),\n                    raw_event_id=uuid4(),\n                )\n            )\n        captured = await service.capture(\n            session,\n            snapshot_id=snapshot.snapshot_id,\n            horizon_seconds=30,\n            due_at=due_at,\n            observed_at=due_at + timedelta(seconds=5),\n        )\n        assert captured.id == missing_id\n        assert captured.status == "CAPTURED"\n        assert captured.odds_a == Decimal("1.90")\n        assert captured.odds_b == Decimal("2.10")\n    await engine.dispose()\n'''
    write("tests/test_evaluation.py", eval_tests)

job_tests = read("tests/test_job_recovery.py")
if "test_terminal_job_can_be_explicitly_reopened_without_erasing_attempt_history" not in job_tests:
    job_tests += '''\n\n@pytest.mark.asyncio\nasync def test_terminal_job_can_be_explicitly_reopened_without_erasing_attempt_history() -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    jobs = JobRepository()\n    now = datetime(2026, 8, 16, tzinfo=UTC)\n    async with factory() as session, session.begin():\n        job_id = await jobs.enqueue(\n            session,\n            job_type=JobType.SETTLE_MAP,\n            dedupe_key="terminal-reopen",\n            payload={"canonical_map_id": str(uuid4())},\n            max_attempts=1,\n            not_before=now,\n        )\n    async with factory() as session, session.begin():\n        claimed = (await jobs.claim(session, worker_id="worker", now=now))[0]\n        assert claimed.id == job_id\n        status = await jobs.fail(\n            session,\n            job_id=job_id,\n            worker_id="worker",\n            error="boom",\n            failed_at=now,\n        )\n        assert status == JobStatus.FAILED_TERMINAL\n    async with factory() as session, session.begin():\n        reopened_id = await jobs.enqueue(\n            session,\n            job_type=JobType.SETTLE_MAP,\n            dedupe_key="terminal-reopen",\n            payload={"canonical_map_id": str(uuid4())},\n            reopen_terminal=True,\n            not_before=now,\n        )\n        assert reopened_id == job_id\n    async with factory() as session:\n        record = await session.get(DurableJobRecord, job_id)\n        assert record is not None\n        assert record.status == JobStatus.PENDING.value\n        assert record.attempt_count == 1\n        assert record.max_attempts >= 4\n    await engine.dispose()\n\n\n@pytest.mark.asyncio\nasync def test_job_runner_fast_fails_on_lease_renewal_error_without_misclassifying_loss() -> None:\n    engine = create_async_engine("sqlite+aiosqlite:///:memory:")\n    async with engine.begin() as connection:\n        await connection.run_sync(Base.metadata.create_all)\n    factory = async_sessionmaker(engine, expire_on_commit=False)\n    jobs = JobRepository()\n    now = datetime.now(UTC)\n    async with factory() as session, session.begin():\n        await jobs.enqueue(\n            session,\n            job_type=JobType.BUILD_SNAPSHOT,\n            dedupe_key="renewal-failure",\n            payload={},\n            not_before=now,\n        )\n    async with factory() as session, session.begin():\n        job = (await jobs.claim(session, worker_id="worker", now=now))[0]\n\n    cancelled = asyncio.Event()\n\n    async def handler(_: DurableJob) -> None:\n        try:\n            await asyncio.sleep(30)\n        finally:\n            cancelled.set()\n\n    runner = JobRunner(\n        worker_id="worker",\n        session_factory=factory,\n        repository=jobs,\n        handlers={JobType.BUILD_SNAPSHOT: handler},\n        poll_seconds=0.01,\n        lease_seconds=120,\n    )\n\n    async def broken_renewal(*_args, **_kwargs) -> None:\n        raise RuntimeError("database unavailable")\n\n    runner._renew_lease = broken_renewal  # type: ignore[method-assign]\n    await runner._execute(job, "worker")\n    assert cancelled.is_set()\n    async with factory() as session:\n        record = await session.get(DurableJobRecord, job.id)\n        assert record is not None\n        assert record.status == JobStatus.RETRY_WAIT.value\n        assert record.last_error is not None\n        assert "lease renewal failed" in record.last_error\n    await engine.dispose()\n'''
    write("tests/test_job_recovery.py", job_tests)

# Keep architecture policy explicit for future agents.
arch = read("docs/ARCHITECTURE.md")
marker = "\n## Post-match Review Analytics\n"
addition = '''\n## Pre-release Runtime Safety and Recovery\n\n- SPA static serving is containment-checked after path resolution; request paths and symlinks may never escape `frontend/dist`.\n- WeChat direct-chat commands are authorized to the account's bound `user_id`; server-directed iLink endpoints must stay inside the configured trust domain.\n- Future-odds `MISSING` is retryable evidence state, not a tombstone. MAP closing capture is anchored to `MAP_ENDED` (or result first-usable fallback during reconciliation), never `MAP_STARTED`, and late retry generations are bounded to the live recovery window.\n- Reconciliation may explicitly reopen `FAILED_TERMINAL` jobs for the same semantic intent while preserving `JobAttemptRecord` history. AI terminal recovery is limited to the exact current experiment key and must not become implicit historical replay.\n- Broadcast-clock and real-time checkpoint sources share one `(canonical_map_id, minute)` dedupe identity.\n- `app.main.run()` is covered by a PostgreSQL-backed startup smoke test that reaches the real HTTP `/health` and `/api/runtime` endpoints with provider workers disabled.\n\n'''
if addition.strip() not in arch:
    if marker not in arch:
        raise RuntimeError("architecture review marker missing")
    arch = arch.replace(marker, addition + marker, 1)
    write("docs/ARCHITECTURE.md", arch)

print("prelaunch hardening patch applied")
