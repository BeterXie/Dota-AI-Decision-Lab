# Dota AI Decision Lab Access Model

This context defines the product language for competition data, AI insight access, and event-bound commerce. Access is tied to a competition resource rather than to a recurring calendar membership.

## Competition Structure

**Event**:
A single edition of a tournament, such as TI 2026, containing stages and series.
_Avoid_: tournament when referring to one BO series; season when no season boundary exists.

**Stage**:
A named competitive phase within an event, such as group stage or playoffs, with an authoritative stage classification for its series.
_Avoid_: page section; display label.

**Group Stage**:
The event stage whose AI decisions are available to every user for discovery.
_Avoid_: free match; preview stage.

**Series**:
One BO matchup between teams, containing one or more maps and serving as the unit for a single-match purchase.
_Avoid_: map; single map; generic match when a BO series is meant.

**Map**:
One game inside a series. A map is not a commercial product in the current access model.
_Avoid_: match when the individual game is meant.

## AI Content

**AI Decision**:
The model's decision intelligence for a series or map checkpoint, including direction, confidence, probability, and reasoning where the data is eligible.

**AI Performance**:
Post-hoc measurement of AI decisions against resolved match outcomes and preserved decision snapshots.
_Avoid_: prediction accuracy when the broader performance view is meant.

**Review**:
The post-match analytical workspace for comparing outcomes, decisions, model behavior, and supporting market evidence.
_Avoid_: premium review; replay parser.

**Realtime Notification**:
A user-directed delivery of a new eligible decision or live update through a configured channel. It is always a member-gated capability.
_Avoid_: alert when the persisted delivery and authorization lifecycle is meant.

## Access And Commerce

**Free Access**:
Every user may read all Group Stage AI Decisions, AI Performance, and Review content. Free access does not include Realtime Notifications or paid-stage AI Decisions.

**Series Pass**:
A one-time, non-expiring purchase bound to one Series. It unlocks paid-stage AI Decisions and Realtime Notifications for that Series, including historical decisions after the Series ends.
_Avoid_: 30-day pass; monthly pass; single-map pass.

**Event Pass**:
A one-time, non-expiring purchase bound to one Event. It unlocks paid-stage AI Decisions and Realtime Notifications for all Series in that Event, including historical decisions after the Event ends.
_Avoid_: global Pro; annual membership; site-wide subscription.

**Access Grant**:
An entitlement for a named capability and competition scope. A grant may come from Free Access, a Series Pass, an Event Pass, or an explicit operational source; its scope must never be inferred from a product label alone.

**Historical Access**:
Purchased access to eligible past AI Decisions remains available after the bound Series or Event ends. Historical access does not create or replay Realtime Notifications.

## Confirmed Product Rules

- Group Stage AI Decisions are open to Free Access.
- AI Performance and Review are open to Free Access across the product.
- Realtime Notifications require an active Series Pass or Event Pass for the relevant scope.
- Paid-stage AI Decisions require an active Series Pass or Event Pass for the relevant scope.
- Series and Event Passes are bound to competition identity, not to a duration in days.
- An Event Pass covers every Series in its Event; a Series Pass covers only its selected Series.
