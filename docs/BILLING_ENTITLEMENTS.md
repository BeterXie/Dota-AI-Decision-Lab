# Billing and entitlement lifecycle

Billing is intentionally separated from authentication and authorization.

- Email authentication answers **who the user is**.
- `user_entitlements` answers **which premium capabilities the user may use**.
- A payment provider answers **whether a commercial subscription is currently entitled to access**.

The core application does not depend on Stripe, Paddle, or another vendor. Provider adapters must validate their own webhook signatures and normalize a provider event before calling `BillingEntitlementService.apply_subscription_event(...)`.

## Normalized event contract

A provider adapter supplies:

- `provider`: stable provider key, for example `stripe` or `paddle`.
- `event_ref`: provider event identifier used for idempotency.
- `user_id`: authenticated Dota AI Decision Lab account owner. The adapter must obtain this from trusted checkout/subscription metadata or a verified server-side mapping; never from an arbitrary browser-supplied user id.
- `subscription_ref`: stable provider subscription identifier.
- `plan_key`: internal plan key. V1 supports `PRO`.
- `access_state`: internal `ACTIVE` or `INACTIVE` state. Provider-specific statuses must be mapped by the adapter.
- optional customer reference, provider status, and current period end.

`PRO` currently grants both `ai_decisions` and `realtime_notifications`.

## Safety properties

Billing events are persisted without raw webhook payloads. A SHA-256 digest of normalized event content is retained instead.

The `(provider, event_ref)` pair is unique. Replaying the exact same event is a no-op; replaying the same event id with different normalized content fails closed. PostgreSQL transaction-scoped advisory locks serialize concurrent deliveries for the same event or subscription before first insert.

Entitlements are granted with a subscription-specific source such as `billing:<provider>:<digest>`. Cancellation or expiry revokes only that source. A promo, development, admin, or other independent entitlement source therefore survives billing cancellation.

There is deliberately no public endpoint that grants premium access. A future provider webhook route must verify the provider signature before invoking the lifecycle service.

## Provider adapter checklist

Before enabling real payments, the selected adapter must:

1. verify webhook authenticity using the provider's official mechanism;
2. resolve the subscription to a trusted internal `user_id`;
3. map provider states to `ACTIVE` or `INACTIVE` conservatively;
4. pass the provider event id unchanged as `event_ref`;
5. acknowledge the webhook only after the lifecycle transaction succeeds;
6. retry safely because the lifecycle service is idempotent;
7. never let frontend subscription state directly grant an entitlement.
