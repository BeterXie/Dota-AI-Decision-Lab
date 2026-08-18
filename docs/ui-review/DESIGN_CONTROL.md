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
