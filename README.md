# Dota AI Decision Lab

Dota AI Decision Lab is a standalone Dota 2 decision-intelligence runtime. It aligns RayBet market observations, DLTV draft/live state, STRATZ and OpenDota historical facts, local Draft Intelligence, deterministic quality gates, immutable DecisionSnapshots, and independent GPT, Claude, Gemini, DeepSeek, and Kimi decisions. The operational dashboard supports Chinese and English and keeps data quality, provenance, closing odds, result evidence, and worker readiness next to each decision.

V1 is shadow decision only. It does not place bets or manage a bankroll.

## Requirements

- PowerShell 7
- Python 3.14
- PostgreSQL 18
- `uv`
- Node.js 22.23 or newer for frontend development
- Docker Desktop when using the included PostgreSQL service

## Local setup

Run these commands from the repository root in PowerShell 7:

```powershell
Copy-Item -LiteralPath '.env.example' -Destination '.env'
docker compose up -d postgres
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL startup failed with exit code $LASTEXITCODE" }

uv sync --extra dev
if ($LASTEXITCODE -ne 0) { throw "Python dependency sync failed with exit code $LASTEXITCODE" }

Set-Location -LiteralPath (Join-Path (Get-Location) 'frontend')
npm ci
if ($LASTEXITCODE -ne 0) { throw "Frontend dependency install failed with exit code $LASTEXITCODE" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed with exit code $LASTEXITCODE" }
Set-Location -LiteralPath '..'
```

If port 5432 is already occupied, set `POSTGRES_PORT` before starting Docker and update `DATABASE_URL` to the same host port:

```powershell
$env:POSTGRES_PORT = '55432'
docker compose up -d postgres
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL startup failed with exit code $LASTEXITCODE" }
```

The runtime applies Alembic migrations automatically by default. Activate the environment and use the single supported launch command:

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.main
if ($LASTEXITCODE -ne 0) { throw "Runtime exited with code $LASTEXITCODE" }
```

For a one-click start on Windows, run `start-app.cmd` (double-click or from a terminal). It stops any running instance of this project only, rotates the `.runtime` logs, starts the runtime detached, and waits for the API to become healthy before printing `OK`/`FAILED`.

The dashboard and API are served from `http://127.0.0.1:8000` by default. Important operational endpoints are `/health`, `/ready`, `/metrics`, `/api/runtime`, `/api/maps`, and `/api/jobs/summary`.

## Configuration

Copy `.env.example` to `.env` and provide the credentials available to this installation. Missing credentials stay explicit: readiness reports `ACTION_REQUIRED`, and the runtime does not invent substitute data.

`STRATZ_TOKEN` enables primary historical synchronization and local R.O.S.H. inputs. `OPENDOTA_API_KEY` is optional. Each configured AI provider runs independently; one unavailable provider does not block the others.

Decision email notifications are owned by this runtime and use the Resend HTTP API. Set
`EMAIL_NOTIFICATIONS_ENABLED=true`, `EMAIL_RECIPIENTS`, `RESEND_API_KEY`, and
`RESEND_FROM`. One bilingual
text/HTML email is durably queued after a snapshot's AI decisions are persisted; the
message uses that immutable snapshot's match, odds, live, draft, history, and quality data.
Resend requests use a persistent notification ID as the idempotency key so job retries and
runtime restarts do not produce duplicate messages.

Provider hosts, model IDs, live synchronization thresholds, decision checkpoints, worker timing, and runtime binding are centralized in `app/config.py` and can be overridden by environment variables.

## Development and verification

Backend checks:

```powershell
uv run ruff format --check app migrations tests tools
if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed with exit code $LASTEXITCODE" }
uv run ruff check app migrations tests tools
if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed with exit code $LASTEXITCODE" }
uv run pytest
if ($LASTEXITCODE -ne 0) { throw "Pytest failed with exit code $LASTEXITCODE" }
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed with exit code $LASTEXITCODE" }
uv run alembic check
if ($LASTEXITCODE -ne 0) { throw "Alembic schema check failed with exit code $LASTEXITCODE" }
```

Frontend checks:

```powershell
Set-Location -LiteralPath (Join-Path (Get-Location) 'frontend')
npm test
if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed with exit code $LASTEXITCODE" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed with exit code $LASTEXITCODE" }
npm run test:e2e
if ($LASTEXITCODE -ne 0) { throw "Frontend E2E failed with exit code $LASTEXITCODE" }
```

Run the deterministic recorded-timeline replay without provider network access:

```powershell
uv run pytest tests\test_deterministic_replay.py
if ($LASTEXITCODE -ne 0) { throw "Replay tests failed with exit code $LASTEXITCODE" }
uv run pytest tests\test_production_lifecycle_replay.py
if ($LASTEXITCODE -ne 0) { throw "Production replay failed with exit code $LASTEXITCODE" }
```

The deterministic replay harness verifies ordering, duplicate delivery, restart recovery, no future leakage, degradation, and deterministic snapshot hashes. The production lifecycle replay creates an isolated PostgreSQL database, applies real Alembic migrations, and drives production collectors, historical fallback, PREMATCH/POST_DRAFT/LIVE_BASIC snapshots, AI isolation, closing odds, settlement, evaluation, and durable job lease recovery. `tools/replay_timeline.py` accepts owner-recorded JSON timelines together with explicit `--canonical-map-id` and `--valve-match-id` arguments. Sanitized provider fixtures under `tests/fixtures` cover RayBet, DLTV, Historical, and pinned R.O.S.H. contracts.

## Shadow runtime audit

After a real shadow map has been captured, export the runtime-integrity evidence for that canonical map:

```powershell
uv run python tools\shadow_run_audit.py --canonical-map-id '<CANONICAL_MAP_UUID>' --output '.\shadow-audit.json'
if ($LASTEXITCODE -ne 0) { throw "Shadow runtime audit failed with exit code $LASTEXITCODE" }
```

`shadow-run-audit-v1` reports RayBet/DLTV provider evidence, map-side identity stability, DLTV connection transitions and durable reconnect recovery coverage, immutable LIVE_BASIC field-freshness evidence, persisted temporal-alignment status/confidence, snapshot modes and quality warnings/blockers, and AI-to-snapshot hash alignment. Its integrity checks return `PASS`, `WARN`, `FAIL`, or `NOT_APPLICABLE` only from persisted evidence. A single audit with passing checks is evidence about that captured map; it is not a declaration that the entire system is production-ready. Closing odds, settlement, evaluation, and durable-job lifecycle remain independently auditable through their persisted records, dashboard views, and production lifecycle replay.

## Architecture invariants

The implementation contract is defined by `AGENTS.md`, `docs/ARCHITECTURE.md`, and the normative addendum `docs/MAP_SIDE_IDENTITY.md`. Provider data is raw-first and append-oriented; unknown values remain unknown; historical facts obey `first_usable_at` and `knowledge_cutoff`; snapshots are immutable; every AI receives the same canonical `snapshot_hash`; and unsafe live synchronization degrades to a valid lower decision mode. RayBet pairs must pass strict identity/freshness/skew checks, DLTV LIVE_BASIC freshness is derived from the oldest required field's latest explicit raw observation rather than socket receipt alone, and closing/result evidence remains explicit and auditable.

Map-side identity is an explicit correctness gate: canonical Team A / Team B ordering is not Radiant / Dire ordering, and DLTV `first_team` is never treated as Radiant by position. POST_DRAFT or LIVE decision inputs may bind R.O.S.H., roster, Player×Hero, or live side-relative features to Team A / Team B only after the immutable snapshot contains verified Radiant / Dire canonical team identity. See `docs/MAP_SIDE_IDENTITY.md` for the evidence, temporal, degradation, UI, and regression requirements.
