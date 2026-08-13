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

## Architecture invariants

The implementation contract is defined by `AGENTS.md` and `docs/ARCHITECTURE.md`. In particular, provider data is raw-first and append-oriented; unknown values remain unknown; historical facts obey `first_usable_at` and `knowledge_cutoff`; snapshots are immutable; every AI receives the same canonical `snapshot_hash`; and unsafe live synchronization degrades to a valid lower decision mode. RayBet pairs must pass strict identity/freshness/skew checks, DLTV freshness uses effective state changes as well as message receipt, and closing/result evidence remains explicit and auditable.
