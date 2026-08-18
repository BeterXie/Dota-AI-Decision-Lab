# Liquipedia Discovery Provider

Liquipedia is the primary source for tournament discovery and scheduled series metadata. RayBet remains an odds provider attached to canonical match identity rather than the source that defines the tournament calendar.

## Selected crawler stack

The project has one crawler architecture:

1. existing `httpx` for ordinary HTTP/API access;
2. existing `curl-cffi` for browser-like HTTP transport when the target permits it;
3. Crawlee for Python with Playwright only when a target genuinely requires browser rendering and permits browser automation.

No Firecrawl, Crawl4AI, Scrapy, Selenium or second crawler framework is part of the production design.

The stack describes the project's escalation options; it does not override a target site's access policy. A provider must use the lowest layer that is both sufficient and permitted.

## Liquipedia-specific access policy

Liquipedia's current API terms explicitly disallow automated access to generated HTML pages while permitting its MediaWiki API under rate limits. Therefore the Liquipedia provider does **not** use Playwright or direct generated-page crawling.

The current Liquipedia path is:

```text
Liquipedia MediaWiki API (`action=parse`)
    ↓
httpx
    ↓ transport failure only
curl-cffi against the same API endpoint
    ↓
rendered HTML returned by MediaWiki API
    ↓
deterministic parser
```

The provider must:

- identify Dota AI Decision Lab with a custom User-Agent and project contact URL;
- accept gzip responses;
- reuse HTTP sessions;
- keep `action=parse` requests at least 30 seconds apart;
- cache/reuse observations rather than repeatedly requesting unchanged pages;
- attribute Liquipedia when its CC-BY-SA text/data is displayed or redistributed;
- never use Playwright, curl impersonation, CAPTCHA handling or login automation to bypass a Liquipedia non-API access restriction.

`curl-cffi` here is only a transport fallback for the permitted MediaWiki API endpoint. It is not used to impersonate a browser against generated wiki pages.

## Discovery pages

The first production observations are intentionally small:

- `Liquipedia:Tournaments` for upcoming / ongoing / concluded tournament discovery;
- `Liquipedia:Matches` for the global Dota schedule;
- a specific tournament page when a tournament-local schedule needs to be refreshed.

`action=parse` returns rendered HTML plus a revision id. The parser extracts stable page links and machine timestamps where present instead of asking an LLM to infer identities.

## Runtime cadence

The active runtime seeds Liquipedia before each RayBet discovery pass only when one source is due. At most one Liquipedia `action=parse` request is attempted in a single pass.

Current cadence:

- global match schedule: every 15 minutes;
- tournament directory: every 6 hours;
- minimum spacing between parse attempts: 30 seconds;
- failed Liquipedia refresh: retry no sooner than 5 minutes.

When both pages are due, the global match schedule runs first because it can create canonical series that the immediately following RayBet discovery can reuse. The tournament directory runs on the next eligible pass.

Liquipedia work is wrapped in a nested database transaction/savepoint. A Liquipedia timeout, parser error, identity ambiguity or temporary API failure rolls back only that seed attempt and does not abort the RayBet discovery transaction.

## Data flow

```text
Liquipedia MediaWiki API
    ↓
raw API/page observation
    ↓
source URL + revision + timestamps + transport + parser version
    ↓
deterministic tournament / series parser
    ↓
normalized Liquipedia observation
    ↓
Liquipedia provider identity mapping
    ↓
canonical event / team / series
    ↓
RayBet existing-series linker
    ↓
RayBet match + odds provider identity
    ↓
DLTV / Valve live and result evidence
```

The canonical projector is deliberately fail-closed:

- Liquipedia team page names become stable provider team ids;
- tournament page names become stable provider event ids;
- existing team aliases are reused when there is exactly one canonical match;
- a nearby same-event/same-team canonical series is reused when unambiguous;
- ambiguous team/event/series identity raises an identity blocker instead of guessing;
- Liquipedia schedule observations never write RayBet odds metadata or rewrite RayBet provider ids.

## RayBet linking policy

When RayBet later discovers a market match, it no longer automatically defines the tournament schedule if a safe canonical series already exists.

The linking order is:

1. reuse an existing RayBet provider-match mapping when present;
2. resolve the RayBet team provider ids against already-known canonical team aliases/mappings;
3. find canonical series with the same unordered team pair inside the configured time window;
4. use an existing RayBet tournament mapping, or an exact event-name match, to disambiguate when possible;
5. if exactly one series remains, attach the RayBet provider match/event/team identities to that existing series;
6. if no safe candidate exists, fall back to the existing RayBet `IdentityResolver` creation path;
7. if multiple equally plausible candidates remain, fail closed instead of guessing.

When an existing Liquipedia-seeded series is reused, its scheduled time is not overwritten by a nearby RayBet time. RayBet may fill a missing best-of or a missing canonical schedule value, but it does not rewrite known Liquipedia schedule identity.

This preserves the provider boundary:

- Liquipedia answers what tournament/series is scheduled;
- RayBet answers which provider match and odds markets belong to that canonical series;
- DLTV/Valve remain the live/map/result evidence sources.

## Provenance requirements

Every accepted observation retains enough information to reproduce and audit the parser result:

- Liquipedia page name and source URL;
- MediaWiki revision id;
- request start and receive timestamps;
- API transport (`httpx` or `curl-cffi`);
- parser version;
- raw rendered HTML from the API response;
- raw payload hash through `ProviderRawEvent`;
- normalized tournament or series fields;
- resulting canonical provider mappings.

Do not use an LLM to decide canonical team, tournament, match time, best-of, score or winner fields. Parser failures stay explicit and unresolved until deterministic extraction or identity rules can resolve them.
