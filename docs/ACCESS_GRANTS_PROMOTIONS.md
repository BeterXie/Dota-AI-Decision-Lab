# Access grants and promotions

The product now models premium access as independently revocable grants instead of a single plan boolean.

## Scope model

A grant has an entitlement, source, validity window, and scope:

- `GLOBAL`: site-wide entitlement. Existing Pro subscription/pass behavior remains GLOBAL.
- `SERIES`: entitlement applies only to one `canonical_series.id` (the full BO matchup and its maps).
- `MAP`: entitlement applies only to one `canonical_maps.id`. The authorization layer supports this scope even though V1 commerce sells SERIES rather than individual maps.

`EntitlementService.active_entitlements()` deliberately returns GLOBAL entitlements only. Resource-scoped grants are exposed through `active_grants()` and checked through `has_resource_entitlement()` / `access_scope()`. This prevents buying one series from accidentally turning legacy `user.plan == Pro`-style surfaces into site-wide access.

## Product behavior

### Global Pro

Paddle monthly and fixed-term Pro products continue to grant both:

- `ai_decisions`
- `realtime_notifications`

with `GLOBAL` scope.

### BO Series Pass

When `PADDLE_SERIES_PASS_PRICE_ID` is configured, an authenticated user can buy a one-time pass for a specific canonical series. The server creates the Paddle transaction and persists its trusted mapping to `user_id + canonical_series_id + configured price` before returning checkout.

A signed matching `transaction.completed` event grants both premium entitlements with `SERIES` scope. The default access duration is three days (`PADDLE_SERIES_PASS_ACCESS_DAYS`), enough to cover normal BO completion and delayed review without becoming a subscription.

Full approved refunds, chargebacks, and chargeback warnings revoke only that purchase source and permanently block the purchase record from automatic reactivation. Chargeback reversals do not auto-regrant in V1.

The series pass unlocks:

- premium AI decisions for maps inside that canonical series;
- Email / QQ / WeChat decision notifications only for snapshots inside that series.

It deliberately does **not** unlock cross-match `/review` or raw `/api/snapshots/*` diagnostics. Those remain GLOBAL Pro surfaces in V1.

## Notification enforcement

A scoped notification grant is checked twice:

1. when a per-user delivery row is created, by resolving `snapshot -> map -> series`;
2. immediately before provider send.

A refund, expiry, disabled account, binding change, or preference change therefore prevents a previously queued delivery from escaping its current authorization scope.

## Referrals

Referral campaigns are disabled by default (`REFERRAL_ENABLED=false`).

Each active account can obtain one stable referral code. A newly created account may claim one code within `REFERRAL_CLAIM_WINDOW_DAYS`. Self-referral and multiple inviter attribution are rejected.

A claim alone gives no premium access. V1 qualification requires the invited account's first verified Paddle `transaction.completed` purchase after the server-owned billing mapping has been reconciled. Defaults:

- inviter: 7 GLOBAL Pro days;
- invited user: 3 GLOBAL Pro days;
- up to 20 rewarded referrals per inviter.

Rewards grant both premium entitlements and are tagged with the configured campaign key and referral-specific source. Repeated inviter rewards stack sequentially rather than overlap. A full refund or chargeback of the qualifying purchase revokes only the grants created by that referral attribution.

## API and UI

Authenticated resource inspection:

```text
GET /api/access/maps/{canonical_map_id}
```

Referral:

```text
GET  /api/promotions/referral
POST /api/promotions/referral/claim
```

Series checkout:

```text
POST /api/billing/series/{canonical_series_id}/checkout
```

The `/billing?series=<canonical_series_id>` UI presents a series-specific pass alongside GLOBAL Pro products. `/billing?ref=<code>` preserves an invite code through login and lets the user claim the attribution.

## Configuration

```text
PADDLE_SERIES_PASS_PRICE_ID=
PADDLE_SERIES_PASS_ACCESS_DAYS=3
REFERRAL_ENABLED=false
REFERRAL_CAMPAIGN_KEY=referral-v1
REFERRAL_CLAIM_WINDOW_DAYS=7
REFERRAL_INVITER_REWARD_DAYS=7
REFERRAL_INVITED_REWARD_DAYS=3
REFERRAL_MAX_REWARDS_PER_INVITER=20
```

These settings do not weaken the provider boundary: crypto/stablecoin remains a separate future adapter, and all Paddle purchase grants still require the signed webhook plus a server-owned transaction mapping.
