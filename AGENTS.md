# AGENTS.md

## Dota AI Decision Lab — Lean AI Engineering Contract

`AGENTS.md` defines **how AI works**. `docs/ARCHITECTURE.md` defines **what the system must be**.  
This is a single-owner, AI-assisted project. Routine implementation approval is not required.

## 1. Authority

Priority:

1. Owner's current explicit instruction
2. `AGENTS.md`
3. `docs/ARCHITECTURE.md`
4. Current task-specific review/acceptance document
5. Tests consistent with the above
6. Existing implementation
7. README/comments/old examples

Existing code is not automatically correct. If code/tests conflict with architecture, change them. Do not preserve obsolete behavior just to keep old tests green.

## 2. Execute without routine approval

When required to complete a clear task, directly create/modify/delete files, refactor internal APIs, change schema, create Alembic migrations, change dependencies/config, change workers/runtime wiring, change API/frontend, rewrite affected tests, remove obsolete code, and update docs.

Do not stop to ask whether to refactor, add a migration, delete obsolete code, add tests, wire runtime, or continue. If the requested outcome requires it, do it.

## 3. Continue until COMPLETE or HARD_BLOCKED

Ordinary engineering problems are not blockers: test/type/build failures, migration conflicts, dependency issues, large refactors, many callers, legacy conflicts, or multiple valid implementation choices.

Diagnose, fix, continue.

Only stop early for a genuine HARD BLOCKER, such as a required unavailable secret, denied permission, an external fact that cannot be derived/measured, irreconcilable owner requirements, or a required external service with no usable fixture/fallback.

Normal terminal states:

```text
COMPLETE
HARD_BLOCKED
```

## 4. Task-scoped execution is the default

**A new AI session is NOT a reason to re-audit the repository.**

Normal workflow:

```text
understand request
→ identify impact surface
→ inspect relevant code/tests
→ read relevant ARCHITECTURE sections
→ implement complete change
→ run sufficient relevant validation
→ expand only when evidence requires it
```

Do not automatically read the entire architecture, inspect every provider/worker/database path, inspect R.O.S.H., start the full runtime, open a browser, or run every test merely because the session is new.

## 5. Validation depth

Choose automatically from impact.

### LOCAL
For isolated parser/helper/UI/config/CI/query bugs. Use targeted tests/build/lint. Usually no full runtime/browser.

### CROSS-SUBSYSTEM
For changes such as Provider→Repository, Repository→Snapshot, Schema→Service, Worker→Durable Job, API→Frontend, Market/Historical→Gate. Use relevant integration/migration/replay/runtime checks.

### SYSTEM
Use for explicit full audit/release acceptance, major architecture changes, `app.main`/Supervisor core changes, Durable Job/Event core changes, Canonical Identity changes, DecisionSnapshot/hash changes, Deterministic Gate changes, Temporal Alignment core changes, R.O.S.H. core model changes, Historical core model/as-of changes, or large cross-cutting correctness changes.

SYSTEM validation may include broader tests, clean PostgreSQL migration, runtime startup/shutdown, restart/recovery, reconciliation, deterministic replay, lifecycle E2E, browser when relevant, and CI.

## 6. Complete implementation, proportionate verification

```text
implementation completeness != verification breadth
```

Small change = complete local fix + targeted proof.  
Large feature = complete all applicable layers + broader proof.

Task-scoped execution never authorizes partial implementation.

## 7. No schedule-driven scope cuts

Do not reduce architecture-required scope because of time, token cost, file count, complexity, MVP thinking, or deadlines.

Forbidden: “tests later”, “migration later”, “happy path only”, TODO placeholders, temporary production stubs, skipping supervision/recovery, or shrinking Historical/Draft/Live/Evaluation for speed.

Rule:

```text
required by architecture → implement
required for correctness → implement
required for operation → implement
required for verification → test
explicitly out of scope → do not invent
owner removes requirement → may remove
```

## 8. No defensive development

Do not preserve obsolete internal interfaces merely because they exist. Avoid unnecessary legacy adapters, compatibility layers, duplicate implementations, and feature flags for dead architecture unless a real current consumer requires them.

After callers migrate and tests pass, delete superseded code. Do not over-abstract hypothetical futures.

## 9. Non-negotiable data invariants

Always preserve:

```text
Raw First
Append-oriented historical state
Unknown != Zero
Canonical Identity
decision_at
first_usable_at
knowledge_cutoff
no future leakage
immutable DecisionSnapshot
same snapshot_hash for every AI in one checkpoint
provider freshness
live synchronization safety
unsafe live data degrades to safer mode
```

Never fabricate data to make the system look healthy. Past snapshots must never gain later information. Provider IDs are provider-scoped and require explicit canonical mapping.

## 10. R.O.S.H. reference trigger

Only when changing Draft Intelligence / R.O.S.H. core behavior, inspect:

```text
BeterXie/dota2-predictor
commit c7a54b59299fb6f46988cb85ed85ebacfe9c0f04
prematch/stratz_rosh.py
```

Required for changes to R.O.S.H. scoring, Hero×Position, Hero×Time, Synergy/Counter, player adjustment, minute curve, R.O.S.H. STRATZ queries, slot semantics feeding R.O.S.H., or reference/golden tests.

Do **not** inspect it merely because a session is new. The old project is reference only, never a runtime dependency.

## 11. Architecture-specific correctness

Detailed business rules live in `docs/ARCHITECTURE.md`.

When affected by the task, preserve architecture-defined behavior for RayBet market eligibility/raw status, DLTV sparse-state merge/effective freshness, Historical provider identity/as-of rules, Temporal alignment/confidence, Deterministic Gate, AI same-snapshot behavior, Durable Jobs/Reconciliation, Closing odds/settlement/evaluation, and Runtime readiness.

Do not reread or revalidate unrelated areas.

## 12. Runtime, durable work, database

Normal launch:

```bash
python -m app.main
```

Do not require multiple manual terminals.

Must-complete work must not exist only in memory. Where required, preserve dedupe/idempotency, leases, retry, attempt history, terminal failure state, and reconciliation.

A worker not wired into the supported runtime is not complete.

Persistent schema change requires an Alembic migration. Do not destructively rewrite historical snapshots for convenience.

## 13. Testing policy

Default:

```text
run the smallest test set that credibly proves the change
```

Expand when a shared/core contract changed, schema/runtime wiring changed, tests reveal broader impact, a correctness-critical invariant changed, or the owner requested broad validation.

Examples:

```text
parser → parser + fixture/contract tests
scoring → scoring + relevant invariant tests
frontend → tests/build; browser only if needed
schema/repository → migration + integration tests
Snapshot/Gate → snapshot + gate + replay/integration tests
```

Do not run unrelated systems for ceremony.

## 14. Browser/runtime policy

Do not start the whole system/browser for every edit.

Browser verification is appropriate when frontend interaction/visual behavior, API/frontend integration, or dashboard behavior changed, or SYSTEM acceptance requires it.

Full runtime startup is appropriate when `app.main`, worker lifecycle, Supervisor, provider integration, or major runtime config changed, or SYSTEM/release acceptance requires it.

## 15. CI and security

Do not claim repository-wide completion while relevant CI is knowingly red.

Never make CI green by skipping correctness tests, weakening gates, ignoring platform failures, or converting failures into silent passes. Fix the cause.

Never commit/log API keys, Authorization headers, HAR cookies, session tokens, or provider credentials. Sanitize captured fixtures.

## 16. Product scope

Unless architecture/owner changes scope, do not add automatic betting, bankroll/Kelly execution, Vision OCR, own replay parser, custom LLM training, AI debate, majority-vote automatic execution, or a large generic BI platform.

These are product boundaries, not time-saving shortcuts. Do not use this section to omit architecture-required functionality.

## 17. Full repository review trigger

Full review is **not** default.

Perform it only when the owner explicitly requests a full audit/review, asks whether all architecture requirements are complete, requests release/milestone acceptance, or when a major architecture migration / large cross-cutting correctness change requires SYSTEM acceptance.

Only then consider full architecture/repository/runtime/replay/E2E/browser/CI review.

## 18. Definition of Done

Apply only relevant items:

```text
[ ] Requested behavior is complete
[ ] Relevant architecture requirements are satisfied
[ ] No required scope was cut for speed
[ ] No unnecessary approval gate was introduced
[ ] No obsolete compatibility layer remains without a real consumer
[ ] Affected data invariants remain correct
[ ] Unknown remains unknown
[ ] No future leakage was introduced
[ ] Canonical identity is respected where affected
[ ] Freshness/sync/degradation remains correct where affected
[ ] Runtime wiring updated if runtime behavior changed
[ ] Migration exists if schema changed
[ ] Relevant tests pass
[ ] Broader validation ran when core/shared contracts changed
[ ] Browser/runtime validation ran only when relevant
[ ] Secrets are safe
[ ] Docs/config updated if contracts changed
[ ] No known relevant failure is hidden
```

Do not mechanically execute irrelevant checklist items.

## 19. Final instruction

```text
DO NOT wait for routine approval.
DO NOT shrink required implementation.
DO NOT re-audit the repository merely because the session is new.
DO NOT reread unrelated architecture sections.
DO NOT inspect R.O.S.H. reference unless the task affects R.O.S.H.
DO NOT start every provider/runtime/browser for every local edit.
DO NOT preserve obsolete code merely because it exists.
DO NOT invent data.
DO NOT weaken time/data-quality invariants.

UNDERSTAND the task.
IDENTIFY the impact surface.
READ relevant code/tests/architecture.
IMPLEMENT the complete coherent change.
MIGRATE affected callers/data when needed.
DELETE superseded code when appropriate.
RUN the smallest sufficient validation.
ESCALATE validation when impact becomes broader.
CONTINUE until COMPLETE or genuinely HARD_BLOCKED.
REPORT what is actually complete.
```

Guiding principle:

```text
complete implementation
+
task-scoped context
+
proportionate verification
+
automatic escalation when necessary
```

Move quickly by removing unnecessary ceremony, **not by reducing correctness**.
