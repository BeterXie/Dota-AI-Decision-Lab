# Official visual assets

Dota AI Decision Lab 2.0 uses an **official-first** policy for tournament and team artwork.

## Principles

1. Tournament artwork is registered only when its source can be traced to Valve/Dota 2 or the tournament organizer's official site/CDN.
2. Team crests prefer the Valve/Steam Dota team-logo asset keyed by the canonical numeric team id.
3. A small curated name-to-team-id map is allowed only as a compatibility bridge for provider payloads that do not yet expose the numeric id to the frontend.
4. Unknown or failed assets fall back to the product's own generated abbreviation badge. We do not fill visual gaps with logos scraped from wikis, search results, or unrelated third-party CDNs.
5. Source URLs live in code next to the asset mapping so later audits can tell where an image came from.

## Current tournament registry

### The International

- Artwork: Aegis of Champions front image
- Publisher: Valve / Dota 2
- Source page: `https://www.dota2.com/aegisofchampions`
- Asset host: `cdn.steamstatic.com`

The same official artwork is used for event names that clearly identify The International, including names such as `TI15 国际邀请赛`.

### DreamLeague

- Organizer: ESL
- Verified official event page: `https://pro.eslgaming.com/dreamleague/`
- Registered artwork: none yet

The organizer-owned event page is recorded as the provenance target, but the product deliberately keeps the fallback event badge until a stable organizer-owned logo/image asset URL is verified. This prevents a temporary CMS image, search-result copy, or third-party mirror from silently becoming a permanent product dependency.

### Other tournaments

Until an exact organizer-owned image URL has been verified, the UI deliberately uses the product fallback event badge. New tournament artwork should be added only together with its official provenance here and in the visual asset registry.

## Team logos

Team logo URLs use the Dota/Steam team-logo convention:

`https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/<team-id>.png`

The resolver first uses a numeric team id from the match payload. If the provider currently supplies a non-numeric local id, a curated name mapping can resolve established teams to their Valve team id. If neither route is trustworthy, the UI shows a generated abbreviation badge.

## Failure behavior

Remote images are never required for layout correctness. If an image cannot be loaded, React swaps it for the same-size fallback badge so cards, match rows, and mobile layouts do not collapse or show browser broken-image chrome.
