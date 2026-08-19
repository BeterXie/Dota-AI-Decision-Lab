# DLTV live module design control

Design schema: v3.1

## Gate 1 - Proposition

- Gate 1 status: released.
- Image role status: approved.
- Image role: reference.
- Image placement: not placed.
- Brief status: approved by the owner.
- Direction status: approved as `live-pulse`.
- Direction preview shown: yes - `direction-preview.html`.
- Proposed direction: `live-pulse`.
- Approved direction: `live-pulse`.
- Brief approval evidence: the owner selected the recommended placement and required provider-neutral public language.
- Direction approval evidence: “live-pulse确实更好一点，不过注意页面ui和接口返回都不要有dltv的字样，包括raybet字样”.
- Source route: local product and architecture -> DLTV, esport.vision, and HLTV public product references -> no asset generation.
- Source policy: factual product fields and explicitly labelled example values only.
- Asset ledger: `ASSET_LEDGER.md`.
- Reference family: live sports scoreboards and Dota match evidence surfaces.
- Technique rationale: a zero-centered lead trace gives the net-worth sign a spatial meaning; compact delta summaries explain momentum; two freshness clocks and sync safety provide honest trust context without exposing transport internals.
- Target density: one dominant lead statement, one trend visualization, two recent-change facts, a three-part trust footer, and complete degraded/recovery states. At least four visible design acts per state.
- Revision contract: preserve the current match hero and AI priority; remove duplicated score content; strengthen live context and provenance; keep delayed player detail out of the live surface.
- Vocabulary lock: public UI and public API responses must not contain provider brand names. Use “比赛进程”, “市场数据”, “连接更新”, “局势变化”, and “市场同步”. Internal collection and admin diagnostics retain exact provider identities.
- Interpretive copy status: pending. Labels such as `优势扩大` are derived display copy and must remain mechanically tied to signed timeline deltas.

### Form challenge

1. Authority: the owner explicitly asked where and how the missing DLTV live module should be added and which data it should display.
2. Reader action: the user scans one map's current state, recent direction, and trust level before interpreting the AI decision.
3. Single-canvas test: one static state is insufficient; the implementation must cover live, stale, unavailable, and final observations.

### Evidence selection

| Selected evidence | Source | Confidence | Task role | Translation |
| --- | --- | --- | --- | --- |
| Match identity and score remain the first layer | DLTV and esport.vision | High | Prevent duplicate score modules | Keep time/kills in the existing hero |
| Map navigation precedes map-specific evidence | DLTV and esport.vision | High | Establish placement | Put live evidence directly after series navigation |
| A zero-centered net-worth trace explains momentum | DLTV completed map and esport.vision live view | High | Dominant event | Use the recent 10-minute timeline, not a decorative sparkline |
| Dense engineering diagnostics stay subordinate | Current product and architecture | High | Trust and recovery | Show two human-readable ages and sync safety; fold raw diagnostics away |

### Palette and type cause

- Field: inherit the current graphite match surface so this reads as one product, not a restored legacy page.
- Semantic colors: current Radiant/Dire team mapping owns the two trace colors; amber is reserved for stale/unsafe states; neutral gray means unknown.
- Type: inherit the current product UI ladder; tabular numerals are used only for clocks, deltas, and ages.
- Rejected palette: a new neon live-data palette that competes with AI and market semantics.
- Rejected type: condensed broadcast display text that harms Chinese team-name capacity.

## Gate 2 - Master

- Decision: blocked until Gate 1 brief and direction are explicitly approved.

## Gate 3 - Delivery

- Decision: blocked until an implemented master is approved.
