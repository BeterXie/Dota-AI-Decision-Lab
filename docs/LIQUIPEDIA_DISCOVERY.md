# Liquipedia Discovery Provider

Liquipedia is the planned primary source for tournament discovery and scheduled series metadata.

The crawler stack is intentionally narrow:

1. `httpx` for normal HTML requests;
2. `curl-cffi` when browser-like HTTP behavior is required;
3. Crawlee for Python with Playwright only when the page genuinely requires browser rendering.

There is no second crawler framework or hosted extraction provider in this architecture. The escalation order is part of the provider contract and is covered by tests.

## Fetch policy

Routine discovery starts with HTTP because it is cheaper, faster and easier to reproduce. A failed HTTP request may escalate to `curl-cffi`. A real Chromium page is the final fallback, not the default transport.

The browser fallback uses Crawlee's `PlaywrightCrawler`; crawler workers therefore need the `crawlee[playwright]` Python extra and a Chromium browser installation before browser fallback is enabled.

Crawler requests must identify the project with a stable user agent, use conservative concurrency, cache/reuse observations where possible, and avoid login/CAPTCHA bypasses.

## Data flow

```text
Liquipedia page
    ↓
httpx
    ↓ failure / incompatible response
curl-cffi
    ↓ failure / JS-required page
Crawlee + Playwright
    ↓
raw page observation + source URL + fetch transport
    ↓
deterministic parser
    ↓
normalized Liquipedia event / series observation
    ↓
identity resolution
    ↓
canonical event / series
    ↓
RayBet provider match + odds mapping
```

Liquipedia discovery must not write RayBet odds metadata. RayBet remains a provider attached to an existing canonical match identity; Liquipedia owns the planned tournament/schedule observation that helps create or match that canonical identity.

## Provenance requirements

Every accepted observation must retain enough information to reproduce and audit the parser result:

- source URL;
- request start and receive timestamps;
- fetch transport (`httpx`, `curl-cffi`, or `crawlee-playwright`);
- parser version;
- raw/normalized payload hash;
- normalized tournament or series fields;
- resulting canonical identity mapping.

Do not use an LLM to decide canonical team, tournament, match time, best-of, score or winner fields. Parser failures stay explicit and unresolved until deterministic extraction or identity rules can resolve them.
