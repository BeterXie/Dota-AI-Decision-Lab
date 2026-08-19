# DotaScope production launch

This runbook turns the public DotaScope brand into a production origin at
`https://dotascope.com` without weakening the runtime's existing access and audit
boundaries. Issue #56 is the launch checklist; this document is the repository-side
execution contract.

## Non-negotiable topology

The Python application stays bound to loopback (`127.0.0.1:8000`). It is **not**
made internet-facing by setting `HOST=0.0.0.0`.

A production TLS edge/reverse proxy owns ports 80/443 and forwards requests to the
loopback application. `deploy/Caddyfile.example` is the reference configuration.
Another edge is acceptable only if it preserves the same invariants:

- canonical public origin is `https://dotascope.com`;
- `https://www.dotascope.com/*` redirects permanently to the apex origin;
- the upstream `Host` remains `dotascope.com`, so `/ws/status` same-origin checks
  compare the browser `Origin` to the real public host;
- `/ready` and `/metrics` are not publicly readable;
- TLS certificates renew automatically;
- HSTS is added only after HTTPS, redirects and OAuth callbacks are proven stable.

`/health` may remain externally reachable as the minimal liveness endpoint. Do not
expose database credentials, runtime secrets or detailed readiness output through
the edge.

## Configuration split

The application intentionally has two configuration surfaces. Keep them separate.

### Core `.env`

Production must at minimum set or verify:

```dotenv
HOST=127.0.0.1
PORT=8000
AUTH_ENABLED=true
AUTH_COOKIE_SECURE=true
AUTH_SECRET_KEY=<generated-secret>
RESEND_API_KEY=<secret>
RESEND_FROM=DotaScope <verified-sender@your-verified-domain>
EMAIL_SUBJECT_PREFIX=[DotaScope]
AUTH_EMAIL_SUBJECT_PREFIX=[DotaScope]
```

Do not enable live billing until the production Paddle catalog and webhook have
been verified:

```dotenv
PADDLE_ENABLED=false
PADDLE_ENVIRONMENT=live
PADDLE_API_KEY=<secret>
PADDLE_WEBHOOK_SECRET=<secret>
PADDLE_SERIES_PASS_PRICE_ID=<price-id>
PADDLE_EVENT_PASS_PRICE_ID=<price-id>
```

After the production webhook, checkout mapping, refund/chargeback revocation and
scoped-grant tests pass, switch `PADDLE_ENABLED=true` through the normal deployment
process.

### Social auth `.env.social` / process environment

Use the `DOTA_AUTH_*` names from `.env.social.example`. Production values are:

```dotenv
DOTA_AUTH_EXTERNAL_BASE_URL=https://dotascope.com
DOTA_AUTH_GOOGLE_ENABLED=false
DOTA_AUTH_GOOGLE_CLIENT_ID=<client-id>
DOTA_AUTH_GOOGLE_CLIENT_SECRET=<secret>
DOTA_AUTH_STEAM_ENABLED=false
```

Configure provider consoles first, then enable each provider separately.

Google redirect URI:

```text
https://dotascope.com/api/auth/google/callback
```

Steam realm and return URL:

```text
https://dotascope.com/
https://dotascope.com/api/auth/steam/callback
```

Do not put `DOTA_AUTH_*` keys into the core `.env`; core settings validate unknown
keys strictly.

### Runtime DB control plane

Auth settings are seeded into PostgreSQL. Once a setting row exists, the Runtime
Admin value is authoritative over the original environment default. Before enabling
Google or Steam in production, verify in Runtime Admin that:

```text
auth.external_base_url = https://dotascope.com
```

Also verify the Google client ID/secret and provider enablement state shown by the
control plane are the intended production values.

## DNS and TLS cutover

Before changing public DNS:

1. enable registrar auto-renew, account 2FA and transfer/domain lock;
2. record the authoritative DNS provider and current records;
3. provision the production host/edge and keep the application on loopback;
4. validate the edge configuration locally or on a temporary host;
5. lower DNS TTL ahead of the cutover if the current provider allows it.

At cutover, point the apex and `www` records at the production edge. Confirm both
names obtain valid certificates before enabling social login or billing.

Do not enable HSTS during the initial cutover. Add it only after at least one stable
verification window where apex HTTPS, `www` redirect, OAuth callbacks, cookies and
WebSockets all work correctly.

## Email identity

Use a sender under a domain/subdomain that is verified with the selected mail
provider. Configure SPF and DKIM first, verify alignment, then publish DMARC with a
policy appropriate to the rollout stage. Login codes and AI decision notifications
must visibly identify DotaScope while retaining their existing idempotency behavior.

## Paddle activation order

Keep the billing kill switch off until all of the following are true:

1. live Series Pass and Event Pass price IDs are configured;
2. checkout/customer return paths use the DotaScope HTTPS origin;
3. the production webhook endpoint receives and validates signed events;
4. duplicate/replayed events do not create duplicate grants;
5. refund/chargeback paths revoke the associated grant;
6. Group Stage Free Access remains free;
7. paid/unknown-stage AI remains unavailable without the correct scoped grant.

Enable live checkout only after these checks pass.

## Public metadata

The frontend build publishes:

- canonical URL metadata for `https://dotascope.com/`;
- Open Graph/Twitter title and description;
- `robots.txt` that excludes control/API/billing/notification surfaces;
- a minimal `sitemap.xml` containing only the canonical public root.

Do not add an `og:image` until a reviewed DotaScope social asset exists. Expand the
sitemap only when stable public landing/content routes are intentionally indexable.

## Production acceptance

After DNS and TLS are live, run:

```powershell
uv run python tools/verify_production_origin.py --base-url https://dotascope.com
```

The automated probe verifies the public-origin plumbing. Then perform the product
acceptance pass from issue #56:

- anonymous homepage/event/match browsing;
- sanitized Group Stage Free AI projection;
- paid/unknown-stage AI denied without an applicable grant;
- email login/logout;
- Google login;
- Steam login;
- Series/Event Pass checkout and scoped authorization;
- Notification Center authorization and email delivery;
- QQ/WeChat paid-notification boundaries;
- `/performance` and `/review`;
- same-origin `/ws/status` behavior;
- Runtime Admin allowlist/403 boundary;
- desktop/mobile no-overflow smoke test.

## Rollback

Keep rollback boring:

- disable new billing checkout first if payment behavior is suspect;
- disable an affected social provider independently if its callback fails;
- restore the previous DNS target/edge config if the origin itself is unhealthy;
- keep the application loopback-only throughout;
- do not rename or roll back database/API/experiment identities for brand reasons.

A launch rollback must not delete persisted billing, entitlement, audit, snapshot or
AI decision records.
