# AGENTS.md

## Dota AI Decision Lab — AI Engineering Execution Contract

This file defines **how an AI coding agent must work in this repository**.

The project is a **single-owner / single-developer project**. There is no product committee, no code-review committee, no approval workflow, and no requirement to preserve obsolete internal interfaces merely because they already exist.

The governing architecture document is:

```text
docs/ARCHITECTURE.md
```

If the repository has not yet copied the architecture document into that location, use the latest project architecture document supplied by the owner as the source of truth and place it at `docs/ARCHITECTURE.md` when appropriate.

---

# 1. Authority and source-of-truth order

When implementing work, follow this priority order:

```text
1. The owner's explicit current instruction
2. AGENTS.md
3. docs/ARCHITECTURE.md
4. Existing tests that are consistent with 1–3
5. Existing implementation
6. Comments / old README / stale examples
```

The existing codebase is **not automatically authoritative**.

If existing code conflicts with the architecture document, **change the code**.

If existing tests encode obsolete behavior that conflicts with the architecture document, **change the tests together with the implementation**.

Do not preserve an incorrect design merely to keep old tests green.

---

# 1.5 Completeness is not negotiable for schedule

This project is primarily developed with AI assistance. **Do not reduce required implementation scope merely to save development time, hit an artificial milestone, or produce an earlier-looking MVP.**

The architecture document defines the required product scope. If a capability is required by `docs/ARCHITECTURE.md`, implement it completely unless the owner explicitly changes or removes that requirement.

Forbidden schedule-driven behavior includes:

```text
"TI is close, so skip this required module"
"Implement only the happy path for now"
"Leave the rest as TODO because it is faster"
"Use a stub/mocked implementation in production path temporarily"
"Skip migration / tests / supervision / observability to save time"
"Reduce Historical / Draft / Live / Evaluation scope because of deadline"
"Return a partial vertical slice when the requested task is an integrated feature"
```

The correct rule is:

```text
required by architecture -> implement it
required for correctness -> implement it
required for operability -> implement it
required for verification -> test it
explicitly out of scope in architecture -> do not implement unless requested
owner explicitly removes requirement -> it may be removed
```

**Time pressure may change implementation order, never silently change required scope or quality.**

AI agents should use their ability to work quickly across multiple files to complete the full coherent change, rather than shrinking the change to imitate a human time-constrained MVP process.

If a task is too large for one edit, continue implementing the remaining required parts in the same task context. Do not stop at an arbitrary partial milestone and ask for approval to continue.

---

# 2. Required operating mode

## 2.1 Execute, do not ask for routine approval

This is a single-person project. The owner explicitly authorizes the coding agent to perform necessary implementation work without asking for routine approval.

When the requested goal is clear, the agent should directly:

- create files;
- modify files;
- delete obsolete files;
- rename modules;
- refactor APIs;
- change database schemas;
- create Alembic migrations;
- rewrite tests;
- add or remove dependencies;
- replace an incorrect implementation;
- consolidate duplicate modules;
- change internal interfaces;
- update configuration;
- update documentation;
- add runtime workers;
- wire workers into `python -m app.main`;
- add health/readiness reporting;
- add fixtures based on verified HAR payloads;
- implement fallback/degradation behavior required by the architecture.

Do **not** stop and ask:

```text
“Should I refactor this?”
“Should I create a migration?”
“Should I delete the old implementation?”
“Would you like me to continue?”
“Do you want me to wire this into the main runtime?”
“Should I add tests?”
```

If those actions are necessary to satisfy the requested outcome and the architecture, perform them.

## 2.2 Do not manufacture approval gates

Do not introduce artificial workflow such as:

```text
proposal → owner approval → skeleton → owner approval → implementation
```

Do not require PR approval, architecture sign-off, migration approval, or interface approval for normal development.

Do not split one coherent task into a sequence of approval-dependent mini-projects.

The expected behavior is:

```text
understand requirement
→ inspect relevant code/docs
→ implement complete solution
→ migrate/update dependent code
→ test
→ report result
```

## 2.3 Ask only when the requirement is genuinely unknowable

A clarification question is justified only when a required product decision cannot be derived from:

- the owner's request;
- this file;
- `docs/ARCHITECTURE.md`;
- verified provider data/fixtures;
- existing repository context.

Do not ask merely because multiple implementation techniques are possible. Choose the simplest architecture-consistent solution and implement it.

---

# 3. No defensive development

“Defensive development” in this project means adding complexity primarily to avoid changing existing code, avoid making a decision, or avoid taking ownership of the requested implementation.

That behavior is prohibited.

## 3.1 Do not preserve obsolete interfaces by default

Do not add unnecessary compatibility wrappers such as:

```python
new_service = NewService()
legacy_service = LegacyServiceAdapter(new_service)
legacy_service_v2 = CompatibilityAdapter(legacy_service)
```

unless an **actual currently required external consumer** needs the legacy contract.

Internal APIs may be changed freely when doing so produces the architecture required by the project.

If a method or module is obsolete after the refactor, delete it.

## 3.2 Do not keep two implementations “just in case”

Avoid:

```text
new implementation
+ old implementation
+ feature flag
+ compatibility mode
+ fallback to old implementation
```

when the old implementation is no longer part of the architecture.

A fallback is valid only when it is a **documented data/provider fallback**, for example:

```text
STRATZ → OpenDota fallback
DLTV websocket → polling transport fallback
LIVE_BASIC → POST_DRAFT degradation
```

A fallback is not valid merely because the agent is afraid to remove old code.

## 3.3 Do not over-abstract hypothetical futures

Do not build generic frameworks for providers, markets, databases, message buses, or model routers that do not yet exist.

Use interfaces where the architecture explicitly requires provider interchangeability, but keep them narrow and concrete.

Bad:

```text
UniversalEsportsProviderFactory
GenericMarketEventMetaProtocolV4
PluggableEverythingRegistry
```

Good:

```text
HistoricalProvider
LiveStateProvider
AiProvider
RayBetHttpClient
DltvSocketClient
```

## 3.4 Do not add silent defaults to make code “safe”

Missing data must remain missing.

Never convert unknown values to fake neutral values such as:

```text
None → 0
UNKNOWN → 0.5
missing GPM → 0
missing confidence → 1.0
missing position → Pos5
```

If data is unavailable, represent it explicitly and let the quality gate decide what is usable.

## 3.5 Do not swallow exceptions without state

This is prohibited:

```python
try:
    ...
except Exception:
    pass
```

Provider failures must become observable runtime state and must preserve the last valid data where appropriate.

Record at least:

```text
last_attempt_at
last_success_at
consecutive_failures
last_error
provider health / worker state
```

## 3.6 Do not substitute TODOs for implementation

For a requested feature, do not finish with:

```text
TODO implement parser
TODO add migration
TODO wire worker
TODO add tests
```

unless the owner explicitly asked only for a design or scaffold.

When asked to implement, implementation means the end-to-end behavior is wired and testable.

---

# 4. Completion standard

A task is not complete merely because a class or function exists.

For repository implementation work, “done” normally means:

```text
schema/domain model
+ storage/migration
+ provider/parser/service implementation
+ runtime wiring
+ error/degradation handling
+ observability/readiness where relevant
+ tests
+ documentation/config updates
```

Only omit a layer when it truly does not apply.

If a new worker exists but `python -m app.main` never starts it, the feature is not complete.

If a new database field exists but no migration exists, the feature is not complete.

If a provider parser exists but no raw payload is persisted, the provider integration is not complete.

If a Decision feature exists but cannot be reproduced with an `as_of`/`knowledge_cutoff`, the feature is not complete.

---

# 5. Core project mission

The repository implements a standalone Dota 2 decision-intelligence system:

```text
RayBet market data
        +
DLTV draft/live state
        +
STRATZ/OpenDota historical facts
        +
local minute-level Draft Intelligence / R.O.S.H.
        ↓
Temporal alignment + deterministic quality gates
        ↓
immutable DecisionSnapshot @ exact T
        ↓
independent GPT / Claude / Gemini / DeepSeek / Kimi decisions
        ↓
future odds + result evaluation
```

The project is not a generic betting platform and is not a replacement for STRATZ/OpenDota.

V1 is **Shadow Decision only**. Do not implement automatic betting, bankroll management, Kelly sizing, or transaction execution unless the architecture is explicitly changed by the owner.

---

# 6. Standalone requirement

The new repository must run independently.

It must not require the old `dota2-predictor` project at runtime.

Do not:

```text
import old project packages
query old project database
call old project HTTP APIs
require old project workers to be running
```

The old project may be used only as a reference when porting already validated logic, particularly RayBet behavior and R.O.S.H.-related algorithms.

Port the needed capability into this repository with clean local ownership.

---

# 7. Mandatory data invariants

These rules override convenience.

## 7.1 Raw first

Every third-party payload used by the system must be persisted or archivable as raw input before/alongside normalization.

Pipeline:

```text
Provider Raw
→ versioned parser/normalizer
→ normalized observation/fact
→ feature snapshot
→ DecisionSnapshot
```

Do not keep only normalized current values.

## 7.2 Append-only history

The following are historical/event data and must be append-oriented:

- RayBet odds observations;
- DLTV live observations;
- provider raw events;
- team rating snapshots;
- team form snapshots;
- player performance maps;
- player form snapshots;
- player-hero snapshots;
- draft snapshots;
- minute curves;
- synchronization estimates;
- DecisionSnapshots;
- AI decisions;
- future-odds evaluations;
- map results/evaluations.

Do not replace history with a mutable `current_score` field.

A current projection/cache may exist for performance, but the authoritative historical series must remain recoverable.

## 7.3 Unknown is not zero

Missing/uncertain values are:

```text
None
null
UNKNOWN
```

not fabricated numeric defaults.

## 7.4 Time semantics are mandatory

Where relevant, preserve:

```text
event_time
provider_updated_at
source_game_time
request_started_at
received_at
stored_at
first_usable_at
knowledge_cutoff
calculated_at
```

Do not collapse all of these concepts into one `timestamp`.

## 7.5 No future leakage

Historical facts used by a decision must satisfy:

```text
first_usable_at <= decision_at
```

Historical feature snapshots must satisfy:

```text
knowledge_cutoff <= decision_at
```

A past DecisionSnapshot must never gain information that became available later.

## 7.6 DecisionSnapshot immutability

Once persisted, a DecisionSnapshot is immutable.

If new data arrives, create a new snapshot.

Do not update an old snapshot in place.

## 7.7 Same snapshot for every AI

All AI providers participating in one decision checkpoint must receive the exact same canonical snapshot payload / `snapshot_hash`.

Never create separate “fresh” snapshots for GPT, Claude, Gemini, DeepSeek, and Kimi during the
same checkpoint.

---

# 8. Provider-specific rules

## 8.1 RayBet

Use the architecture-confirmed model:

```text
HTTP bootstrap/discovery
+ SocketCluster incremental odds stream
```

HTTP responsibilities:

- Dota match discovery;
- complete odds bootstrap;
- odds metadata registry;
- match/event/team metadata.

Socket responsibilities:

- subscribe to `match` channel;
- receive incremental odds updates;
- record `odds_id`, `match_id`, price, `last_update`, raw status;
- automatically reconnect.

Do not replace the websocket with aggressive `/odds` polling as the primary real-time mechanism.

The provider hosts must remain configuration, not scattered string literals.

### RayBet raw status

Do not guess undocumented raw status semantics.

Always persist:

```text
raw_status
```

Only normalize states that have verified mappings.

### Odds metadata

Unknown `odds_id` received from the socket should trigger metadata refresh/bootstrap rather than being discarded.

## 8.2 DLTV

Use:

```text
GET /live/{valve_match_id}.json
+ Socket.IO / Engine.IO live events
```

Do not use browser DOM scraping as the main transport when the structured endpoint/socket is available.

### Draft identity main path

Primary fields:

```text
account_id
hero_id
team
team_slot
```

The current main interpretation is:

```text
team_slot 1 → Pos1
team_slot 2 → Pos2
team_slot 3 → Pos3
team_slot 4 → Pos4
team_slot 5 → Pos5
```

but this must always pass `DraftIdentityValidator`.

Required validation:

```text
10 players
10 non-zero hero ids
5 players per side
each side slots == {1,2,3,4,5}
10 unique heroes
```

If validation fails, mark the draft partial/uncertain. Do not silently invent positions.

### DLTV fast vs delayed data

Keep these logically separate:

```text
DLTV_BOOTSTRAP
DLTV_FAST_SOCKET
DLTV_DELAYED_DETAIL
```

`DLTV_FAST_SOCKET` is the V1 source for live decision state such as:

```text
game_time
kills
team net-worth lead
```

Do not treat `full_stats`/delayed player detail as live evidence merely because fields exist.

Individual player NW/GPM/XPM/KDA/items may enter `LIVE_FULL` only after freshness has been empirically validated and the gate permits them.

### Duplicate socket states

Raw socket events are retained.

Normalized live observations should append only when relevant state changes, not once for every duplicate broadcast.

## 8.3 STRATZ and OpenDota

Historical V1 priority:

```text
STRATZ = primary historical provider
OpenDota = fallback + verification + enrichment
```

Business/domain code must not depend directly on provider-specific JSON shapes.

Normalize provider data into project-owned historical models first.

If STRATZ fails temporarily:

- preserve the latest valid feature snapshot;
- try the documented OpenDota fallback where applicable;
- mark staleness/health;
- do not overwrite previous data with zero or empty values.

If providers disagree on key identity/result facts, emit a `DATA_CONFLICT` state. Do not silently pick whichever payload is easier.

---

# 9. Canonical identity rules

Provider IDs are not global project IDs.

Maintain canonical identities for at least:

```text
Event
Series
Map
Team
Player
Hero
```

Provider mapping must be explicit and traceable.

Preferred map resolution order:

```text
1. existing explicit provider mapping
2. Valve Match ID
3. canonical teams + event + map/series context
4. aliases + start-time window
5. ambiguous → reject / require resolution
```

Do not force-match ambiguous events using only fuzzy team names.

Once available, Valve Match ID should be treated as the strongest map identity anchor in the current architecture.

---

# 10. Draft Intelligence / R.O.S.H. rules

Draft Intelligence is a **local native module in this repository**.

Implementing or modifying Draft Intelligence / R.O.S.H.
**MUST inspect the reference implementation first.**

Reference implementation:

- Repository: `BeterXie/dota2-predictor`
- Primary file: `prematch/stratz_rosh.py`

The reference implementation is an algorithm/provider-behavior reference, not a runtime dependency.
Do not redesign or replace validated R.O.S.H. behavior without first understanding the existing implementation and demonstrating why the change is necessary.

It must not call the old project as a runtime R.O.S.H. service.

R.O.S.H. does not own match discovery or market identification.

Input is normalized draft identity:

```text
Radiant Pos1–5 heroes
Dire Pos1–5 heroes
optional player identities
statistics_cutoff
```

It consumes project-owned/normalized STRATZ-derived inputs for:

```text
Hero × Position
Hero × Time
Synergy
Counter/Matchup
Player × Hero
```

It outputs both:

```text
Pure Draft Curve
Player-Adjusted Draft Curve
```

V1 minute range should remain aligned with the validated statistical range, approximately 20–60 minutes, unless new verified data justifies expansion.

Do not fabricate 0–19 minute precision from a model/data source that does not support it.

AI-facing draft data should include derived summaries such as:

```text
current minute edge
next 5m average
next 10m average
peak minute
peak edge
cross-over minute
early/mid/late/ultra-late averages
curve slopes
```

Do not force AI models to calculate these from dozens of raw curve points.

Every draft computation must record:

```text
statistics_cutoff
model_version
data_version
```

---

# 11. Historical Intelligence rules

Historical Intelligence answers:

```text
How strong is the team historically?
How is the team performing recently?
How strong/formful are the five players actually playing today?
How experienced/effective is each player on the current hero and position?
```

Every feature requires:

```text
value
sample_size
confidence
knowledge_cutoff
model_version
```

## 11.1 Current roster source

Use current DLTV match identity to determine who is actually playing:

```text
account_id + hero_id + team_slot
```

Do not blindly rely on static roster pages when current-match evidence exists.

## 11.2 Historical sync model

Do not query STRATZ/OpenDota from scratch for every AI checkpoint.

Use:

```text
Provider
→ Historical Sync Worker
→ local PostgreSQL historical store
→ feature builders
→ append-only feature snapshots
```

Prewarm expected tournament teams and players at startup.

Player-Hero data should be loaded on demand for the ten current hero/player combinations instead of preloading all players × all heroes.

## 11.3 Team V1

Use separate components:

```text
Team Base Strength     = map-level Elo
Team Recent Form       = weighted last 5/10/20 maps
Current Roster Strength
Roster Stability
```

Do not collapse these into one opaque “team score”.

V1 Elo defaults may be configuration such as initial 1500 and K=24.

Keep every rating update as a snapshot so an `as_of` historical query is possible.

## 11.4 Player V1

Keep separate:

```text
Player Base Strength
Recent Professional Form
Current Role
Player × Current Hero
```

Player Base Strength should use a longer role-adjusted professional window, while Recent Form uses a shorter recent window.

Do not mix public ranked/pub games into professional form in V1 unless the architecture is explicitly changed.

## 11.5 Role adjustment

Never compare raw Carry metrics to raw Support metrics as if they mean the same thing.

Build metric baselines by at least:

```text
patch + position
```

Missing advanced metrics remain unknown.

Weights for role-adjusted player performance must be configurable/versioned.

## 11.6 Player Recent Form

Compute per-map role-adjusted performance first, then aggregate windows.

V1 window weighting:

```text
last 5 maps     50%
maps 6–10       30%
maps 11–20      20%
```

Do not average raw metrics across different roles first.

Confidence is distinct from the form score.

## 11.7 Player × Hero

Use:

```text
long-term history
recent 180 days
current patch
position fit
performance
sample sizes
confidence
```

Small samples must be shrunk toward an appropriate prior/baseline.

A 3-0 hero record must never become “100% true skill”.

V1 may use Beta-Binomial shrinkage and supported-window reweighting as specified in the architecture.

## 11.8 BO3/BO5 map-to-map updates

After a map ends:

```text
Basic result available
→ update team Elo/W-L, basic player/player-hero samples, roster counts

Advanced parsed data later available
→ update role-adjusted player performance and richer player-hero features
```

If Map 1 basic data becomes usable before Map 2 decision time, Map 2 may use it.

If Map 1 advanced data becomes usable after a Map 2 snapshot was created, it may affect future snapshots but must not rewrite the old Map 2 snapshot.

---

# 12. Temporal alignment and live safety

This is a core requirement, not an optional optimization.

RayBet price updates and DLTV live state are not assumed to describe the same instant merely because they were received near each other.

Persist the relevant clocks and build `LiveSynchronizationEstimate` using multiple events.

Track at least:

```text
estimated lag
p50
p90
jitter
sample count
confidence
status
```

Initial configurable states may be:

```text
SAFE
CAUTION
UNSAFE
UNKNOWN
```

Do not hard-code a permanent lag such as “DLTV is always 8 seconds behind”.

If live synchronization is not safe enough for the configured gate:

```text
LIVE_BASIC / LIVE_FULL
→ POST_DRAFT
```

Do not fail the whole decision pipeline if a lower valid mode exists.

---

# 13. Decision modes

Supported modes:

```text
PREMATCH
POST_DRAFT
LIVE_BASIC
LIVE_FULL
```

### PREMATCH

Uses market + team/player historical intelligence.

### POST_DRAFT

Adds validated 10-hero/position draft, minute R.O.S.H., Player×Hero.

### LIVE_BASIC

Adds only freshness/sync-approved DLTV fast state:

```text
game time
kills
team net-worth lead
```

### LIVE_FULL

May add individual live detail only after empirical freshness validation.

The system should automatically select the highest valid mode, not force a requested high mode using unsafe data.

---

# 14. Deterministic gates

AI never overrides hard data-quality rules.

Before model invocation, check at least:

```text
identity complete / unambiguous
market available
market freshness
draft completeness when required
historical knowledge cutoffs
historical blockers
live freshness
live synchronization
provider availability needed by selected mode
```

Examples of blockers:

```text
IDENTITY_AMBIGUOUS
MARKET_MISSING
MARKET_STALE
DRAFT_PARTIAL
ROSTER_IDENTITY_AMBIGUOUS
HISTORICAL_DATA_FUTURE_LEAK
LIVE_SYNC_UNKNOWN
LIVE_DATA_DESYNC
LIVE_STALE
```

Small historical samples usually reduce confidence and create warnings rather than blocking the whole decision.

Do not weaken a gate merely to make a demo produce a BUY decision.

---

# 15. Multi-AI rules

AI models are decision analysts, not data collectors.

In V1 they must not independently browse for match information.

Each provider receives the same immutable DecisionSnapshot.

Use a common structured output schema with actions limited to:

```text
BUY_A
BUY_B
NO_BUY
INSUFFICIENT_DATA
```

`NO_BUY` is a normal and expected result.

Require counter-arguments and data-quality concerns.

Do not make models debate each other in V1.

Do not turn simple majority voting into automatic execution.

One AI provider timeout/failure must not block the others.

Invalid model JSON is a parse failure; never fabricate missing fields into a successful decision.

Persist model, model version, prompt version, timings, raw response, normalized response, snapshot hash, and parse status.

---

# 16. Runtime rules

There is one supported launch command:

```bash
python -m app.main
```

It must start/supervise the complete runtime required by the architecture, including the applicable workers/services:

```text
RayBetDiscoveryWorker
RayBetSocketWorker
DltvSocketWorker
HistoricalSyncWorker
DraftCoordinator
TemporalAligner
SnapshotCoordinator
AiCoordinator
EmailNotificationWorker
FutureOddsWorker
SettlementWorker
WebServer
```

Do not require the owner to remember multiple terminal commands for normal operation.

Socket workers must reconnect automatically.

A worker crash must not silently disappear.

Expose runtime state such as:

```text
STARTING
RUNNING
DEGRADED
RESTARTING
FAILED
```

with relevant health metadata.

---

# 17. Business readiness

`/health == 200` is not sufficient.

The system must expose business readiness for key dependencies, e.g.:

```text
RAYBET_HTTP
RAYBET_SOCKET
DLTV_SOCKET
DLTV_DRAFT
LIVE_SYNC
STRATZ
DRAFT_ENGINE
HISTORY
GPT
CLAUDE
GEMINI
DEEPSEEK
KIMI
EMAIL
```

Overall status should distinguish:

```text
READY
DEGRADED
ACTION_REQUIRED
```

A degraded optional live feed should not make valid PREMATCH/POST_DRAFT operation appear completely unavailable.

---

# 18. Database and migration behavior

Schema changes required by architecture should be implemented directly with migrations.

Do not postpone a necessary schema change merely to avoid touching the database.

Rules:

- use Alembic for persistent schema evolution;
- maintain unique constraints/indexes appropriate to provider identity and as-of queries;
- use JSONB for raw/provider payloads where appropriate, but do not hide all normalized business fields inside unqueryable blobs;
- preserve raw provenance;
- support efficient `knowledge_cutoff <= decision_at` queries;
- make migrations deterministic and testable;
- do not destructively rewrite historical snapshots to simplify a migration.

If a schema concept is obsolete and the repository contains no required external consumer, migrate away from it instead of supporting both designs forever.

---

# 19. Testing rules

Tests are required for domain invariants and provider parsers.

Prefer deterministic fixtures over live internet tests for CI.

Use sanitized HAR-derived fixtures for RayBet/DLTV parser/protocol behavior where helpful.

At minimum, maintain coverage for the architecture-defined cases, including:

### RayBet

```text
match parser
odds registry
socket odds delta
unknown odds_id metadata refresh
reconnect
raw status preservation
```

### DLTV

```text
bootstrap → 10 draft slots
slot validation
fast-state parsing
duplicate-state deduplication
socket reconnect
delayed detail rejected by live freshness gate
```

### Identity

```text
explicit mapping
Valve Match ID mapping
alias mapping
ambiguous mapping rejection
```

### Historical

```text
Elo upset behavior
append-only rating snapshots
as-of query blocks future data
recent-form window weights
support not compared to carry raw GPM
missing metric stays unknown
small player-hero sample shrinkage
position fit
new roster stability
Map1 basic can affect Map2
late advanced data cannot rewrite old Map2 snapshot
STRATZ failure preserves/falls back safely
provider conflict flagged
```

### Snapshot / AI

```text
same canonical input → same hash
past snapshot immutable
UNKNOWN remains null/unknown
future knowledge cutoff rejected
same snapshot hash sent to all models
one AI failure does not block the others
invalid JSON does not become fabricated decision
```

Do not mark a task complete while relevant tests are knowingly broken unless the owner explicitly requested an intermediate diagnostic state.

---

# 20. Provider and network testing

Do not make CI depend on live RayBet/DLTV/STRATZ availability.

Use:

```text
unit fixtures
HAR-derived fixtures
mock server/protocol frames
integration tests with recorded payloads
```

Live provider probes may exist under `tools/`, but they are diagnostics, not the only test coverage.

Network protocol changes discovered in new evidence should update:

```text
fixtures
parser/protocol tests
implementation
architecture notes if the contract changes
```

in the same task.

---

# 21. Error handling and degradation

The project must degrade intentionally, not accidentally.

Examples:

```text
DLTV unavailable
→ PREMATCH/POST_DRAFT can continue when their requirements are met

DLTV sync unsafe
→ POST_DRAFT

one AI provider unavailable
→ other AI providers still run

STRATZ temporary failure
→ use eligible cached/local feature snapshot and/or documented OpenDota fallback

unknown market metadata
→ refresh odds metadata registry
```

Do not convert a provider problem into a total-system outage if the architecture defines a valid lower mode.

Conversely, do not hide a blocker merely to keep the UI green.

---

# 22. Observability rules

When implementing background ingestion/coordination, include enough observability to know whether it is actually working.

Relevant workers/providers should expose at least:

```text
last_attempt_at
last_success_at
last_message_at
consecutive_failures
last_error
messages_received
```

Where useful also expose:

```text
freshness
lag
p50/p90
sample size
current map/match being processed
```

Do not add logging that prints API keys, cookies, auth tokens, or private session values.

---

# 23. Security and secrets

Secrets belong in environment/configuration, not source control.

Examples:

```text
STRATZ_TOKEN
OPENAI_API_KEY
ANTHROPIC_API_KEY
GEMINI_API_KEY
DEEPSEEK_API_KEY
KIMI_API_KEY
DATABASE_URL
```

Never commit HAR cookies/session values as reusable credentials.

Fixtures derived from HAR files must be sanitized.

Do not log full authorization headers or provider session cookies.

---

# 24. UI rules

The TI V1 dashboard is an operational decision dashboard, not a design showcase.

Prioritize:

```text
current match/map identity
market odds + freshness
Draft Intelligence
Historical Intelligence
DLTV live state + freshness
sync status
AI decisions
quality warnings/blockers
worker/provider readiness
```

Data quality must be displayed near decisions.

Do not hide uncertainty behind a clean-looking BUY/SELL card.

Do not spend disproportionate effort on animation, complex frontend state frameworks, or visual polish before the data/decision chain is complete.

---

# 25. Code style and implementation preferences

Prefer straightforward Python 3.11+ async code.

Use the architecture's baseline stack unless there is a concrete reason not to:

```text
FastAPI
Pydantic v2
SQLAlchemy 2
Alembic
PostgreSQL
asyncio
httpx
websockets
python-socketio
```

Guidelines:

- type domain/service boundaries;
- use explicit Pydantic/domain models for normalized data;
- keep provider parsing separate from domain logic;
- keep side effects at service/provider/repository boundaries;
- use timezone-aware datetimes;
- store UTC internally;
- avoid giant god classes;
- avoid unnecessary dependency injection frameworks;
- keep config centralized;
- version parsers, feature models, and prompts where reproducibility requires it;
- prefer deterministic pure functions for scoring/normalization where possible.

---

# 26. Respect explicit architecture scope — never invent schedule cuts

The following systems are excluded **because the architecture explicitly marks them out of scope**, not because development time is scarce. Unless explicitly requested by the owner, do not implement:

```text
automatic betting
bankroll management
Kelly sizing
custom replay parser
Vision OCR
map-coordinate model
complex deep-learning predictor
AI debate system
majority-vote execution
custom LLM training
large BI platform
```

Do not add these as “helpful extras” unless the owner changes scope. Conversely, **never use this section to justify omitting anything that `docs/ARCHITECTURE.md` requires.**

---

# 27. Development workflow for every task

Use this workflow without waiting for approval between steps.

## Step A — Read before editing

Read:

```text
AGENTS.md
relevant sections of docs/ARCHITECTURE.md
relevant current implementation
tests/fixtures for the affected subsystem
```

Do not read the entire repository blindly if the affected scope is clear.

## Step B — Trace the full impact

Before editing, identify all affected layers:

```text
provider / parser
domain model
repository/schema/migration
service/coordinator
runtime wiring
API/dashboard
readiness
fixtures/tests
docs/config
```

Then implement the complete coherent change.

## Step C — Prefer one coherent implementation

Do not produce a partial new path while leaving the normal runtime on the old path.

Example: if changing RayBet ingestion to websocket-based deltas, ensure the live runtime actually uses the new path and the odds registry/bootstrap is wired.

## Step D — Remove superseded code

After callers have migrated and tests pass, delete code that exists only for the obsolete architecture.

Do not leave dead code “for safety”.

## Step E — Validate

Run the most relevant tests first, then broader tests as practical.

For schema/runtime changes, also run/import/smoke-check the application entry path where possible.

## Step F — Report concrete completion

Final development report should state:

```text
what changed
what was removed/replaced
migrations/config added
runtime behavior now achieved
tests run and result
remaining empirically unknown provider facts, if any
```

Do not end with a list of routine implementation steps that the agent could have completed itself.

---

# 28. Prohibited completion language / behavior

Avoid using “safe” language to mask unfinished work.

Do not claim:

```text
“implemented”
```

when only models/interfaces were created.

Do not say:

```text
“the rest can be wired later”
“you can add a migration later”
“we could add tests next”
“this provides the foundation”
```

for a task whose requested outcome requires those pieces now.

Do not substitute an implementation plan for implementation when repository write access is available.

---

# 29. Architecture uncertainty vs implementation hesitation

The architecture intentionally contains a few empirical unknowns, for example:

- exact RayBet raw status mapping;
- universal reliability of DLTV `team_slot` semantics;
- RayBet ↔ DLTV lag/jitter;
- freshness of DLTV individual `full_stats` across events;
- broadcast coverage details.

These unknowns are **not a reason to stop development**.

Implement them as measured/configurable contracts:

```text
preserve raw values
validate assumptions
record metrics
use UNKNOWN where unresolved
use gates/fallbacks
add probes/fixtures
```

Do not invent facts, but also do not block the entire project waiting for perfect certainty.

---

# 30. Engineering priorities

When trade-offs are genuinely required between implementation qualities, prioritize correctness and system value in this order. This ordering **does not authorize dropping required features**:

```text
1. data completeness
2. time correctness
3. identity correctness
4. reproducibility/auditability
5. resilient ingestion
6. decision pipeline reliability
7. evaluation quality
8. UI polish
```

Do not optimize code elegance at the expense of missing market/live data.

Do not prematurely optimize throughput before establishing correct event-time semantics and append-only storage.

These are prioritization rules for engineering decisions, **not a license to reduce documented scope because of schedule or perceived implementation cost.**

---

# 31. Definition of Done checklist

Before declaring a feature complete, check applicable items:

```text
[ ] Behavior matches docs/ARCHITECTURE.md
[ ] No documented requirement was omitted for schedule, convenience, or perceived MVP speed
[ ] No unnecessary approval step was introduced
[ ] No obsolete compatibility layer remains without a real consumer
[ ] Raw provider input is retained where required
[ ] Normalized model has correct time/provenance fields
[ ] Unknown values remain unknown
[ ] Append-only/history rules are preserved
[ ] No future leakage path was introduced
[ ] Canonical identity is used instead of raw provider IDs as global identity
[ ] Relevant freshness/sync gate exists
[ ] Lower-mode degradation works where architecture requires it
[ ] Runtime starts the feature through python -m app.main
[ ] Worker reconnection/failure state is observable when applicable
[ ] Database migration exists when schema changed
[ ] Tests cover success + important failure/edge paths
[ ] Existing obsolete code/tests were updated or removed
[ ] Secrets are not logged/committed
[ ] Documentation/config is consistent with actual runtime
[ ] End-to-end path is testable
```

---

# 32. Final instruction to coding agents

This project values **decisive, architecture-faithful implementation** over cautious accumulation of wrappers and TODOs.

When the owner gives a clear development request:

```text
DO NOT wait for approval.
DO NOT reduce required scope to save time or hit an artificial deadline.
DO NOT protect obsolete internal code merely because it exists.
DO NOT split a coherent fix into approval-dependent stages.
DO NOT invent data to make the system appear healthy.
DO NOT weaken temporal/data-quality invariants.

READ the architecture.
MAKE the necessary changes.
WIRE the full runtime path.
MIGRATE dependent code/data.
DELETE superseded code.
TEST the result.
REPORT what is actually complete.
```

The project is allowed to move quickly.

It is **not** allowed to become temporally incorrect, unauditable, silently stale, or internally inconsistent in order to move quickly.
