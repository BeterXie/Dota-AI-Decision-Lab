# Billing and entitlement lifecycle

Authentication answers who the user is. `user_entitlements` answers which capability and
competition scope the user may use. Paddle only confirms a purchase; the signed webhook is what
provisions or revokes access.

## Paddle product model

The application sells two one-time, non-expiring products:

- `Series Pass`: one BO series, including its maps.
- `Event Pass`: one event, including every series and map in that event.

Both products grant `ai_decisions` and `realtime_notifications` at their purchase scope. Free
Access is a stage rule for group-stage AI decisions, not a payment row.

Settled-map AI decisions are also available through the public post-match projection for every
stage. This does not create a grant and does not unlock realtime notifications or unsettled maps.

Price amounts and currencies are configured in the Paddle catalog and are never hardcoded in the
application.

`GET /api/billing/offers` reads the configured catalog price records and exposes each active
one-time price as a lowest-unit amount plus ISO currency code. The frontend formats that payload
for the current locale; checkout uses the same server-configured price id.

The generic membership page only offers upcoming or live series and events for purchase. Completed
competition scopes are omitted because their AI decision history is already public.

## Server-owned purchase mapping

`competition_pass_purchases` is the trust bridge between an authenticated account and a Paddle
transaction.

1. The user calls an event- or series-scoped checkout endpoint.
2. The backend chooses the configured price and creates the Paddle transaction.
3. The transaction id is persisted with the authenticated user, scope, configured price, and
   Paddle customer id.
4. The checkout URL is returned only after that mapping is persisted.
5. A signed `transaction.completed` event must match the purchase mapping before grants are made.

Paddle `custom_data` is a correlation and tamper-detection signal, not the source of account
ownership. A signed event without a matching server purchase is ignored.

## Webhook behavior

Endpoint:

```text
POST /api/billing/webhooks/paddle
```

The route reads a bounded raw body, verifies `Paddle-Signature`, and processes:

- `transaction.completed` to activate a pass;
- approved full `adjustment.created` / `adjustment.updated` refunds and chargebacks to revoke it.

The event id is unique. Replays are idempotent; older events are recorded as stale and cannot
restore a revoked purchase. The handler runs both scope adapters against the same signed payload,
so an event for one price cannot activate the other scope.

Configure the notification destination for:

- `transaction.completed`
- `adjustment.created`
- `adjustment.updated`

## Configuration

```text
AUTH_ENABLED=true
PADDLE_ENABLED=true
PADDLE_ENVIRONMENT=sandbox
PADDLE_API_KEY=<sandbox API key>
PADDLE_WEBHOOK_SECRET=<notification destination secret>
PADDLE_SERIES_PASS_PRICE_ID=<one-time Series Pass price id>
PADDLE_EVENT_PASS_PRICE_ID=<one-time Event Pass price id>
```

Sandbox and production catalogs, client tokens, API keys, and webhook secrets are separate.
`PADDLE_CHECKOUT_URL` is optional when the Paddle account has a default payment link.

## Referrals

Referral rewards remain explicit operational grants. A code claim alone grants nothing. A reward
is issued only after the invited account completes a verified first competition-pass purchase, and
a full refund or chargeback revokes only the linked reward source.

## Provider boundary

Future fiat or stablecoin providers must create their own server-owned purchase mapping and feed
the same entitlement ledger. They must not bypass scope checks or provision access from browser
state.
