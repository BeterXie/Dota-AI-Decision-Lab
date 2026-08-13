# Map Side Identity — Normative Architecture Addendum

Status: **Normative correctness contract**

This document supplements `docs/ARCHITECTURE.md` and makes one identity invariant explicit: **canonical series team order and per-map Dota side assignment are different coordinate systems**. Until this material is folded into a later architecture revision, implementations must satisfy this addendum whenever Team A / Team B data is combined with Radiant / Dire data.

If an older example, fixture, UI convention, or implementation detail conflicts with this addendum, the correctness rules in this document take precedence.

## 1. Two independent coordinate systems

`CanonicalSeries.team_a_id` and `CanonicalSeries.team_b_id` define stable **Team A / Team B** ordering for RayBet selections and market pairing, no-vig probabilities, AI `fair_probability_a`, `BUY_A` / `BUY_B`, Team A / Team B historical features, settlement, and evaluation.

A Dota map separately has **Radiant / Dire** sides. That coordinate system is used by DLTV draft slots, kills, net-worth lead, first blood, R.O.S.H. / Draft Intelligence minute curves, and every feature explicitly defined as Radiant-minus-Dire.

The following implications are forbidden:

```text
Team A = Radiant
Team B = Dire
DLTV first_team = Radiant
DLTV second_team = Dire
```

None of those equalities may be assumed from ordering alone.

## 2. Empirical reason this gate is required

A recorded DLTV bootstrap sample demonstrated the exact counterexample this invariant protects against:

```text
db.first_team.is_radiant  = false
db.second_team.is_radiant = true
```

Structured live team identity in the same sample agreed that the second team was Radiant. Provider first/second ordering is therefore not a Radiant/Dire contract.

## 3. Authoritative side evidence

The currently validated primary authority is DLTV bootstrap team metadata:

```text
db.first_team.id
db.first_team.is_radiant
db.second_team.id
db.second_team.is_radiant
```

A side assignment is usable only when all conditions hold:

1. both provider team IDs are valid;
2. both `is_radiant` values are booleans;
3. exactly one team has `is_radiant=true`;
4. both provider team IDs map to canonical team IDs;
5. the mapped canonical set is exactly `{CanonicalSeries.team_a_id, CanonicalSeries.team_b_id}`;
6. Radiant and Dire do not resolve to the same canonical team.

When these checks pass, current provenance is:

```text
source     = DLTV_DB_IS_RADIANT
confidence = 1.0
```

Other structured DLTV fields may be validation or future alternative evidence only after their contract is separately proven. They must not silently weaken this gate.

## 4. Missing or conflicting evidence remains unknown

Never repair missing side identity by guessing from provider first/second order, Team A/B order, array order, odds order, player order, team names alone, previous-map sides, or tournament convention.

Current explicit blocker vocabulary includes:

```text
SIDE_IDENTITY_VALVE_MATCH_MISSING
SIDE_IDENTITY_EVIDENCE_MISSING
SIDE_IDENTITY_UNRESOLVED
SIDE_IDENTITY_TEAM_MAPPING_MISSING
SIDE_IDENTITY_SERIES_CONFLICT
SIDE_IDENTITY_PROVIDER_CONFLICT
SIDE_IDENTITY_PARTIAL
ROSTER_SIDE_IDENTITY_UNRESOLVED
```

These are data-quality facts, not exceptions to hide with fallback inference.

## 5. Temporal integrity

For a DecisionSnapshot with `decision_at = T`:

- use only DLTV bootstrap raw events with `received_at <= T`;
- use only provider-team mappings usable by `T`;
- never apply side evidence learned later to an existing historical snapshot;
- preserve enough provenance to reproduce the projection.

The immutable snapshot side projection should expose, when available:

```text
status
radiant_team_id
dire_team_id
source
confidence
observed_at
raw_event_id
blocker
```

Later improved mapping may be used by a new snapshot. It must not rewrite an older snapshot hash or its AI decisions.

## 6. Historical Intelligence alignment

Historical data consumed by AI is organized around canonical Team A/B semantics, while current draft slots arrive as Radiant/Dire. Current-roster and Player×Hero data may therefore be attached to `players_a` / `players_b` only after per-map side assignment is verified.

Example:

```text
Canonical Team A = Alpha
Canonical Team B = Bravo
Map Radiant       = Bravo
Map Dire          = Alpha
```

Required mapping:

```text
Radiant roster -> players_b
Dire roster    -> players_a
```

The same mapping applies to derived current-roster strength.

If side identity is unresolved, Team-level historical facts that do not depend on current map side may remain available, but roster-specific Team A/B history must not be fabricated. Current-roster and Player×Hero coverage must be removed or marked unavailable rather than assigned to the wrong canonical team.

## 7. DecisionSnapshot degradation rule

A complete DLTV draft does not by itself make POST_DRAFT safe. POST_DRAFT requires the draft Radiant/Dire coordinate system to be connected to canonical Team A/B.

```text
effective_draft_complete = draft_complete AND side_identity_resolved
```

If draft is complete but side identity is unresolved:

- preserve raw/normalized draft observation and R.O.S.H. curve for audit/display;
- do not bind that curve to Team A/B;
- remove unsafe roster-specific Team A/B history;
- degrade the AI DecisionSnapshot to a safe lower mode, normally PREMATCH;
- retain independently valid market and Team-level historical inputs;
- surface explicit side-identity quality state.

LIVE_BASIC and LIVE_FULL must not bypass this rule. Any live mode depending on post-draft state is eligible only when the same verified side mapping exists.

## 8. R.O.S.H. semantic contract

R.O.S.H. remains mathematically defined in map-side coordinates:

```text
R.O.S.H. edge = Radiant edge relative to Dire
positive       = favors Radiant
negative       = favors Dire
```

The minute curve must not be relabeled as Team A-minus-Team B.

When side identity is verified, presentation may enrich the side with canonical team name, for example `Bravo · Radiant +3.2pp`.

When side identity is not verified, the curve may still be displayed as Radiant/Dire intelligence, but it must not say Team A or Team B is favored, must not be marked decision-ready for POST_DRAFT, and must not be merged with Team A/B market probability for AI decision input.

The 20–60 minute R.O.S.H. range remains a data-constrained model boundary and is unrelated to this side-identity gate.

## 9. Frontend presentation contract

Use Team A/B for market prices, fair probabilities, AI decisions, `fair_probability_a`, and canonical series ordering. Team A/B must use neutral identity styling, not Radiant/Dire green/red merely because they occupy left/right layout positions.

Use Radiant/Dire for live kills, net-worth lead, first blood, draft lineup, and R.O.S.H. direction.

Concrete labels such as `TEAM A · DIRE` or `Bravo · RADIANT` may appear only when immutable snapshot side identity is `RESOLVED` and both canonical IDs close exactly over the selected series teams.

If verification fails or an older snapshot has no side identity, the UI falls back to generic Radiant/Dire wording rather than guessing. A complete draft with unverified sides must be visibly distinguished from a fully decision-ready draft, for example `SIDE UNVERIFIED` rather than `READY`.

## 10. AI boundary

AI providers must not infer or repair map sides themselves. Deterministic upstream code owns provider evidence validation, canonical mapping, temporal cutoffs, roster realignment, and mode degradation.

Every configured AI receives the same immutable, already-gated DecisionSnapshot. A model must not use Dota knowledge to guess which canonical team is Radiant or Dire when the snapshot does not establish it.

## 11. Required regression coverage

The following regression cases are mandatory:

1. DLTV fixture where `first_team` is Dire and `second_team` is Radiant;
2. missing `is_radiant` stays unresolved and never falls back to first/second order;
3. Team A = Dire and Team B = Radiant moves Radiant roster history to Team B and Dire roster history to Team A;
4. unresolved side identity removes roster-specific Team A/B history rather than leaving a potentially wrong assignment;
5. unresolved sides with a complete draft degrade AI snapshot to the safe lower mode;
6. frontend reversed-side fixture verifies Header, R.O.S.H., Lineup, and Live use the same mapping;
7. invalid/non-canonical side IDs are never rendered as verified teams.

Changes to these semantics require updated regression tests and replay evidence. Passing visual tests alone is insufficient.

## 12. Implementation priority

```text
Architecture invariants
    > explicit validated provider side evidence
    > canonical identity consistency
    > immutable snapshot cutoff/provenance
    > UI convenience
    > inferred provider ordering
```

Provider ordering is never an acceptable substitute for missing identity evidence.

This protects the platform guarantee that all AIs analyze the same temporally valid facts and deterministic upstream code never invents the fact connecting Radiant/Dire intelligence to Team A/Team B market identity.
