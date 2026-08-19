# Liquipedia Discovery Provider

Liquipedia is the authoritative source for tournament discovery and scheduled series metadata. RayBet remains an odds provider and DLTV remains a map/live provider; both attach to Liquipedia-backed canonical identity and never define the tournament calendar.

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
RayBet match and odds identity (separate provider)
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
- RayBet and DLTV observations without a unique Liquipedia series stay unresolved and retry later;
- the public match feed includes only series carrying a Liquipedia schedule mapping;
- unknown or unsettled matches without a current schedule window are archived from the public feed;
- provider raw events and historical evidence remain archived even when they are not publicly listed.

RayBet discovery searches existing Liquipedia-backed series before attaching market identity. It does not create a canonical event or series. DLTV may create a canonical map only after resolving a unique Liquipedia-backed series, except when an authoritative Valve Match ID already identifies an existing map.

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
