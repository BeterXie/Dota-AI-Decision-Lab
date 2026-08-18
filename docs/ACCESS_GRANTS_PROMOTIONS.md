# Access grants and competition passes

The product uses independently revocable capability grants. A grant has an entitlement, a
source, an optional validity window, and a competition scope.

## Scope model

- `GLOBAL`: site-wide operational access, used for explicit development or admin grants.
- `EVENT`: every series and map in one `canonical_event.id`.
- `SERIES`: one `canonical_series.id`, including all maps in that BO series.
- `MAP`: one `canonical_map.id`; the authorization layer supports it even though current commerce
  sells series and event passes.

`EntitlementService.active_entitlements()` returns GLOBAL rows only. Resource grants are exposed
through `active_grants()` and checked through `access_scope()` / `has_resource_entitlement()`.

## Product behavior

### Free Access

`CanonicalSeries.stage_key == GROUP_STAGE` provides Free AI decision access. AI Performance and
Review are public across the product. Free Access does not create a database grant and never
includes realtime notifications.

Unknown stages are not treated as group stage. Liquipedia observations are normalized into
`GROUP_STAGE`, `PAID_STAGE`, or `UNKNOWN`; only the first is free.

After a `MapResultRecord` exists, that individual map's normalized AI decisions and post-match
evaluation are public regardless of stage or purchase status. This historical projection does not
grant live or unsettled-map access and never enables realtime notifications.

### Series Pass

`PADDLE_SERIES_PASS_PRICE_ID` configures a one-time, non-expiring product. The authenticated
checkout endpoint binds the transaction to one canonical BO series before returning the Paddle URL.
A verified `transaction.completed` event grants `ai_decisions` and `realtime_notifications` with
`SERIES` scope.

### Event Pass

`PADDLE_EVENT_PASS_PRICE_ID` configures a one-time, non-expiring product. The authenticated
checkout endpoint binds the transaction to one canonical event. A verified `transaction.completed`
event grants both premium entitlements with `EVENT` scope; authorization resolves that grant
through every series and map in the event.

Both passes keep historical AI decisions available after the event ends, while settled individual
maps expose their normalized AI decisions publicly even without a pass. Realtime notifications
are never replayed for historical snapshots.

Full approved refunds, chargebacks, and chargeback warnings revoke only the affected purchase
source and permanently block that purchase from automatic reactivation. Partial refunds do not
remove the whole purchase.

## Notification enforcement

A scoped realtime grant is checked twice:

1. when a delivery row is created, by resolving `snapshot -> map -> series -> event`;
2. immediately before the provider sends the delivery.

A refund, disabled account, binding change, or preference change therefore cancels a queued
delivery that no longer has permission.

## API and UI

```text
GET  /api/access/maps/{canonical_map_id}
POST /api/billing/series/{canonical_series_id}/checkout
POST /api/billing/events/{canonical_event_id}/checkout
GET  /api/promotions/referral
POST /api/promotions/referral/claim
```

The UI uses `/billing?series=<canonical_series_id>` for a Series Pass and
`/billing?event=<canonical_event_id>` for an Event Pass.

## Configuration

```text
PADDLE_ENABLED=true
PADDLE_ENVIRONMENT=sandbox
PADDLE_API_KEY=<sandbox API key>
PADDLE_WEBHOOK_SECRET=<notification destination secret>
PADDLE_SERIES_PASS_PRICE_ID=<one-time Series Pass price id>
PADDLE_EVENT_PASS_PRICE_ID=<one-time Event Pass price id>
```

Paddle webhooks remain the only source that provisions paid access. Frontend payment state never
grants an entitlement directly.
