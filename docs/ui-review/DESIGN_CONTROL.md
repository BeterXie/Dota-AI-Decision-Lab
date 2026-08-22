# Full-site UI design control

Design schema: v3.1

## Gate 1 - Proposition

- Gate 1 status: released for an incremental product revision.
- Image role status: approved.
- Image role: mixed.
- Image placement: per asset.
- Brief status: approved by explicit owner instructions.
- Direction status: approved as `existing-product-refinement`.
- Direction preview shown: yes - the running current product, the owner's earlier detail-page captures, and the named official Dota reference.
- Approved direction: `existing-product-refinement`.
- Approval evidence: the owner stated that the current UI is good, rejected a wholesale restoration, asked to learn from the official site, identified undersized type, required commercially usable fonts, and authorized direct changes to layout, typography, backgrounds, and interaction.
- Source route: local product and assets -> official Dota reference -> no unmet asset role.
- Source policy: no new generation; factual product data only.
- Asset ledger: `docs/ui-review/ASSET_LEDGER.md`.
- Reference family: esports event and data-product interfaces.
- Technique rationale: larger fixed type ladder for scanability; stronger image-to-content contact for event identity; restrained semantic color for state; clearer focus/hover feedback; responsive recomposition for dense rows.
- Target density: every primary route needs a clear dominant event, real evidence, system furniture, and complete empty/recovery behavior, with at least four visible authored acts per primary state.
- Revision contract: preserve current structure and data semantics; remove decorative noise; strengthen hierarchy, scale, atmosphere, and interaction; official Dota quality is the reference level.
- Interpretive copy status: none. Do not add marketing filler.

### Form challenge

1. Authority: the owner explicitly requested a full-site UI interaction review and direct optimization of layout, typography, backgrounds, and interaction.
2. Reader action: users navigate a multi-route product state flow, scan competition data, and inspect evidence.
3. Single-canvas test: one canvas cannot perform those actions; the existing responsive application is the correct carrier.

### Palette and type cause

- Field: near-black match-broadcast field keeps team, hero, odds, and decision evidence legible and lets approved event imagery carry atmosphere.
- Semantic colors: cyan for navigation/action, green/red only for true success/loss or Radiant/Dire semantics, amber for market/warning, violet only for AI evidence.
- Type: IBM Plex Sans provides clear UI proportions and numeric legibility; IBM Plex Mono is limited to real numeric/code evidence; Noto Sans SC provides readable Chinese fallback.
- Rejected palette: purple-blue AI gradients and color zoning without state meaning.
- Rejected type: proprietary display faces and condensed Latin-first faces that force poor Chinese fallback.

## Gate 2 - Master

- Decision: released for application-code delivery after desktop and mobile browser review.
- HTML master: `frontend/` application at `http://127.0.0.1:5182/`.
- Approved render: running application after the shared typography/background pass.
- Visual review: desktop and 390px mobile captures covered home, events, TI event detail, match detail, performance, review, billing, account, notifications, and the team not-found state.
- Review result: no new page overflow, broken images, or post-restart browser errors; the dense match state keeps score, AI reason, market, R.O.S.H., and hero evidence readable.
- Benchmark comparison:
  - Type levels: the official event-product reference uses a strong display title plus readable body and metadata; the implementation now uses a fixed 12/13/14/15/19px UI ladder with 34-54px route titles.
  - Reading loop: orientation -> event/match identity -> result or decision -> evidence -> next action remains intact on desktop and mobile.
  - Image operations: approved Aegis/event/performance assets are cropped into their named hero slots; official team and hero images remain replaceable content evidence.
  - Craft family: broadcast field plus evidence board; cyan is navigation/action, amber is market/warning, green/red are true result or side semantics, and violet is limited to AI/access state.
  - Dense/quiet zones: hero and primary result occupy the first viewport; cards use quieter graphite fields, readable copy, and explicit gaps instead of decorative orbs or tiny annotation clusters.

## Gate 3 - Delivery

- Decision: application-code delivery; separate Figma reconstruction waived because the requested deliverable is the existing implemented product.
- Editable format: React/CSS source.
- Interactive HTML: the running Vite application.
- Motion inventory: functional hover/focus/state feedback only, 150-250 ms, with reduced-motion support.

## 2026-08-21 revision control — prediction points and legal pages

- Gate 1 status: released under the approved `existing-product-refinement` direction.
- Approval evidence: the owner explicitly requested the terminology change, two legal pages, and footer links in the existing project.
- Reference role: `IMG_0504.PNG` is a positive product benchmark, not placed. It demonstrates a viable closed-points prediction interaction; DotaScope learns the outcome-selection, points-commitment, expected-points, settlement, and ranking relationship without copying MAX+ visual treatment.
- Revision contract: preserve the current shell and evidence hierarchy; remove public virtual-money, BUY, stake, bankroll, P&L, ROI, turnover, position, and purchase-like prediction copy; strengthen the explicit boundary between free prediction points and paid access.
- Interpretive copy status: approved as an implementation draft by the requested legal-page scope; copy reflects current product behavior and does not invent an operator entity, physical address, or product capability. It is not recorded as jurisdiction-specific legal advice.
- Source route: repository architecture, authentication, billing, and notification contracts; no external visual asset and no generated content.
- Target density: legal pages carry orientation, a plain-language summary, navigable policy sections, effective date/contact, and a recovery route; operational AI states retain their existing evidence density.
- Gate 2 master: released after build validation and browser review of the running React application at `http://127.0.0.1:5173/`.
- Browser review: Edge extension at the desktop viewport plus a 390 × 844 responsive override covered home/footer, a populated match AI card and its four-round detail, the populated points leaderboard, Competition Access, Terms, Privacy, and the mobile Terms/footer state.
- Content review: static labels and historical AI explanations show prediction, points balance, points change, market reference, and prediction records. Original API/database values remain unchanged for audit. The raw `SHADOW_ONLY` mode and legacy policy identifier receive presentation aliases only.
- Layout review: Terms and Performance reported no horizontal overflow; the mobile Terms page reached its bottom edge without clipping; legal navigation, contact recovery, footer links, and long Chinese paragraphs remained readable.
- Review result: no P0/P1 findings remain. The observed P2 issues—8 px match disclaimer copy and low-contrast footer microcopy—were corrected and rechecked.
- Copy sweep: `unlock`/`解锁` is retained only as the factual paid-access entitlement action. Negative statements about payments, wagers, cash value, affiliation, and tracking are sourced service boundaries, not marketing contrast.
- Gate 3 delivery: React/CSS source; no separate Figma deliverable requested.

## Benchmark comparison — prediction-points revision

- Reference family: the user-supplied MAX+ screenshot is a positive closed-points prediction-flow benchmark; the approved DotaScope application remains the visual master.
- Type levels: MAX+ uses modal title, outcome choice, field label, numeric value, and action levels. DotaScope preserves at least five functional levels across prediction cards and legal pages: route title, section title, action/state, body evidence, and metadata/disclaimer.
- Reading loop: MAX+ moves from outcome selection to committed points, expected points, and submission. DotaScope moves from model and prediction state to prediction points, available points, settled change, full round evidence, then Terms/Privacy recovery links.
- Image operations: the MAX+ screenshot remains reference-only and is not placed. No new main image was introduced; existing DotaScope hero crops and identity assets remain unchanged.
- Craft family: DotaScope keeps its broadcast field and evidence-board system. Cyan marks navigation/action, amber marks abstention or caution, violet identifies AI evidence, and green/red carry real result or points-change state.
- Dense and quiet zones: prediction cards concentrate state and metrics; modal rounds carry dense evidence; legal hero and section gaps provide quiet orientation; the footer closes the route without competing with primary content.
- Concrete acts: action-label mapping, points-ledger relabeling, generated-reason normalization, policy/mode presentation aliases, plain-language legal summaries, sticky/stacked policy navigation, explicit contact recovery, and responsive footer recomposition.
- Signature refusal: the implementation does not copy MAX+ branding, teams, split-color match header, modal layout, icons, or H-coin treatment.
