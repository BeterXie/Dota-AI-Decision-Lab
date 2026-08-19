# DLTV live module task brief

## Authority and scope

- Controller / user instruction: restore the useful DLTV live-match capability in the single retained match-detail UI, first deciding placement, structure, and data scope.
- Deliverable surface: one responsive match-detail module with live, stale, unavailable, and post-match states. This Gate 1 package contains design directions only; product code is unchanged.
- Interaction policy: user approval. Implementation begins after the owner selects a direction ID.

## Image role preflight

- Image role status: approved as not required.
- Image role: reference only.
- Image placement: not placed.
- Reference captures are used to study hierarchy and data choreography; no external screenshot or generated image enters the product.

## Reader and truth

- Reader action: after identifying the map, understand who is ahead, whether the lead is growing or shrinking, and whether the live evidence is fresh enough to trust before reading the AI decision.
- Viewing conditions: desktop evidence review and 360-390 px mobile scanning during a live match.
- Required truth: only `DLTV_FAST` values are presented as live: game time, kills, and team net-worth lead. Team labels require verified Radiant/Dire mapping.
- Unknowns that remain visible: missing lead, incomplete mapping, stale effective state, stale message transport, and unsafe market synchronization are shown as unavailable or degraded, never as zero or healthy live data.
- Refusals: no player NW, GPM/XPM, KDA, items, connection ID, reconnect generation, or full sync diagnostics in the primary module; no duplicated hero-scale kill score; no fabricated prediction or win probability.

## Form questions

- State roles: healthy live explains current pressure; stale live preserves the last confirmed value with a warning; unavailable live gives a quiet recovery message; post-match relabels the same evidence as the final DLTV observation.
- Capacity check: team names can occupy two lines; missing 3/5/10-minute baselines remove the unavailable comparison instead of leaving empty metric boxes.
- Visual mother object: a zero-centered net-worth trace. Crossing the center line visibly changes which team owns the lead.
- Title-removal test: team ownership, net-worth direction, recent change, two freshness clocks, and sync safety still identify this as trusted Dota live evidence.
- Single-canvas counterfactual: fails. The product needs related live, stale, unavailable, and final states rather than one static card.

## Evidence and source route

- Local source: current match detail, old `LiveStateCard`, `LiveObservation`, `live_timeline`, freshness resolver, side resolver, and architecture rules.
- Product references: DLTV match detail, esport.vision live detail, and HLTV match hierarchy. STRATZ was inspected but its live content did not load reliably and is not used as visual evidence.
- Asset route: local product -> public reference pages -> no unmet image role -> no generation.

## Autonomous fallback

- Least-assumptive choice: recommend `live-pulse`, a compact full-width band after map navigation and before AI intelligence.
- Unresolved judgment: the owner must select `live-pulse`, `evidence-grid`, or `hero-sheet` before implementation.
