# Billing and entitlement lifecycle

Billing is intentionally separated from authentication and authorization.

- Email authentication answers **who the user is**.
- `user_entitlements` answers **which premium capabilities the user may use**.
- A payment provider answers **whether a commercial purchase is currently entitled to access**.

The lifecycle core remains provider-neutral. Paddle is the first real provider adapter, while future fiat or stablecoin adapters must normalize into the same `BillingEntitlementService.apply_subscription_event(...)` contract rather than introducing a second authorization model.

## Normalized event contract

A provider adapter supplies:

- `provider`: stable provider key, for example `paddle`.
- `event_ref`: provider event identifier used for idempotency.
- `occurred_at`: provider event/state observation time used to reject delayed older state.
- `user_id`: authenticated Dota AI Decision Lab account owner. The adapter must obtain this from a verified server-side mapping; never from an arbitrary browser-supplied user id.
- `subscription_ref`: stable provider subscription or fixed-term purchase identifier.
- `plan_key`: internal plan key. V1 supports `PRO`.
- `access_state`: internal `ACTIVE` or `INACTIVE` state. Provider-specific statuses must be mapped conservatively.
- optional customer reference, provider status, and current period end.

`PRO` currently grants both `ai_decisions` and `realtime_notifications`.

## Safety properties

Billing events are persisted without raw webhook payloads. A SHA-256 digest of normalized event content is retained instead.

The `(provider, event_ref)` pair is unique. Replaying the exact same event is a no-op; replaying the same event id with different normalized content fails closed. PostgreSQL transaction-scoped advisory locks serialize concurrent deliveries for the same event or subscription before first insert.

Each subscription remembers the latest applied `occurred_at`. A strictly older delayed event is stored for audit with `applied=false` but cannot mutate the subscription or restore revoked entitlements. Provider adapters should preserve the provider's highest-precision event/state timestamp.

Entitlements are granted with a purchase-specific source such as `billing:<provider>:<digest>`. Cancellation, expiry, refund, or chargeback revokes only that source. A promo, development, admin, or other independent entitlement source therefore survives billing cancellation.

No browser endpoint can grant an entitlement directly. Checkout endpoints only create a provider checkout. Provisioning happens later from an authenticated provider webhook after the provider event is reconciled with a server-owned checkout record.

## Paddle adapter

Paddle is the first live payment adapter. It supports two product shapes in the application:

- `pro_monthly`: recurring Pro subscription. Intended for card and eligible Alipay subscription checkout.
- `pro_30d` / `pro_365d`: one-time fixed-term Pro passes. These are the product shape used when a payment method cannot create a recurring subscription, including eligible WeChat Pay checkout.

Price amounts and currencies are not hardcoded in application code. Configure Paddle product/price entities in the Paddle catalog and provide their price IDs through environment variables.

### Server-owned checkout mapping

`billing_checkouts` is the trust bridge between an authenticated application account and a Paddle transaction.

1. An authenticated user calls `POST /api/billing/checkout/{offer}`.
2. The backend selects the configured price ID and creates the Paddle transaction itself.
3. The returned Paddle transaction ID is persisted with the authenticated `user_accounts.id`, offer, price, plan, duration, and Paddle customer ID.
4. The checkout URL is returned to the browser only after this mapping is persisted.
5. A signed `transaction.completed` webhook can grant access only when its transaction ID, price, customer metadata, and server checkout record agree.

Paddle `custom_data` is retained as a correlation and tamper-detection signal, but it is **not** the source of account ownership. A signed Paddle event containing an arbitrary `dota_user_id` without a matching `billing_checkouts` record is ignored and cannot grant Pro access.

For recurring purchases, Paddle's `subscription.created` event includes the originating transaction ID. The adapter can therefore establish the subscription from the same server-owned checkout mapping even if subscription events and `transaction.completed` arrive in a different order. Later subscription lifecycle events resolve ownership from the persisted `billing_subscriptions` record.

The checkout endpoint refuses to create another Paddle purchase while the account already has an active, unexpired Paddle billing record. This prevents accidental overlapping passes or parallel active subscriptions. A customer with active Paddle billing should use the customer portal instead.

### Webhook route and events

Webhook endpoint:

```text
POST /api/billing/webhooks/paddle
```

The endpoint is intentionally reachable without a browser session, but it verifies the exact raw body against `Paddle-Signature` using HMAC-SHA256 and a timestamp tolerance before parsing the event. The application reads the body as a bounded stream and rejects payloads larger than 1 MiB before signature processing.

Configure the Paddle notification destination for at least:

- `transaction.completed`
- `subscription.created`
- `subscription.updated`
- `subscription.activated`
- `subscription.trialing`
- `subscription.resumed`
- `subscription.past_due`
- `subscription.paused`
- `subscription.canceled`
- `adjustment.created`
- `adjustment.updated`

Full approved refunds, chargebacks, and chargeback warnings create a persistent fail-closed payment block for the affected billing source. A later ordinary `subscription.updated` with `status=active` cannot silently clear that block. Partial refunds do not automatically remove the whole Pro purchase. Chargeback reversal events are deliberately **not** sufficient by themselves to restore access; V1 keeps the source blocked until a new purchase or explicit operator reconciliation confirms that access should be restored.

### Configuration

Paddle is disabled by default. Sandbox example:

```text
AUTH_ENABLED=true
PADDLE_ENABLED=true
PADDLE_ENVIRONMENT=sandbox
PADDLE_API_KEY=<sandbox API key>
PADDLE_WEBHOOK_SECRET=<notification destination secret>
PADDLE_PRO_MONTHLY_PRICE_ID=<recurring price id>
PADDLE_PRO_30D_PRICE_ID=<one-time price id>
PADDLE_PRO_365D_PRICE_ID=<one-time price id>
```

At least one configured Pro price is required when Paddle is enabled. `PADDLE_CHECKOUT_URL` is optional and may point at an approved Paddle checkout/default payment-link page.

The current application server deliberately remains loopback-only. Paddle's webhook simulator or a temporary HTTPS tunnel can exercise sandbox webhooks during development, but real internet-facing production billing requires the separate remote-host/TLS/reverse-proxy hardening work before deployment.

## Multi-provider and crypto boundary

The billing lifecycle is intentionally not Paddle-specific. A future provider can create its own server-owned checkout/payment mapping, validate its own webhook or chain settlement proof, and call the same normalized entitlement service.

Stablecoin/crypto payment is **not** enabled by a generic configuration switch. It must be implemented as a separate provider adapter with explicit supported jurisdictions, asset/network allowlists, confirmation/finality rules, refund handling, and a server-side mapping to the authenticated account. This prevents a future crypto path from weakening the existing authorization and audit boundary.

## Provider adapter checklist

Before enabling any real payment provider, the adapter must:

1. verify callback/webhook authenticity using the provider's official mechanism;
2. resolve the purchase to a server-owned mapping for a trusted internal `user_id`;
3. validate provider product/price identifiers against the server catalog;
4. map provider states to `ACTIVE` or `INACTIVE` conservatively;
5. preserve the provider event id and reliable event timestamp;
6. reject or ignore stale/out-of-order state safely;
7. account for refund, dispute, chargeback, and reversal behavior;
8. acknowledge the webhook only after lifecycle processing succeeds;
9. remain retry-safe because the lifecycle service is idempotent;
10. never let frontend subscription or payment state directly grant an entitlement.
