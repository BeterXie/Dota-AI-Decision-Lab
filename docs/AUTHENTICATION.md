# Authentication, Premium Access, and Notification Center

Dota AI Decision Lab uses passwordless email authentication as the identity foundation for user-scoped premium access and notifications. Authentication answers **who the user is**; entitlements answer **what that account may access**.

## Access model

Ordinary match browsing is public. A visitor does not need an account to view match identity, teams, draft/lineup information, market data, live state, or ordinary historical match context.

Authentication is required for account-scoped or operational surfaces. AI decisions for an unsettled map require a valid authenticated session plus either Free group-stage access or the `ai_decisions` entitlement. Once a `MapResultRecord` confirms the map is settled, the map's safe AI decision projection is public. User-level real-time delivery requires the separate `realtime_notifications` entitlement so notification access can evolve independently from page access.

The current HTTP policy is:

- `PUBLIC`: `/health`, `/ready`, `/api/auth/*`, `/api/runtime`, `/api/matches`, ordinary `/api/maps/{id}`, settled `/api/maps/{id}/ai-decisions`, `/api/ai-performance`, `/api/review/*`, and other ordinary match-data APIs.
- `AUTHENTICATED`: `/metrics`, `/api/jobs/summary`, and future `/api/account/*` routes.
- In-progress `/api/maps/{id}/ai-decisions` access is checked by the route; `/api/snapshots/*` remains entitlement-protected.
- Notification Center endpoints under `/api/notifications/*` perform an authenticated-user and `realtime_notifications` entitlement check before reading or mutating user settings.

`/ws/status` remains public because it carries ordinary live-refresh events used by the public match experience. Any future private WebSocket path must require authentication and, where appropriate, an explicit entitlement.

Ordinary public match responses must never contain the premium decision payload. They may expose non-sensitive analysis readiness metadata such as whether a decision snapshot exists, when analysis last updated, and how many models completed. The separate settled-map AI endpoint may expose the normalized decision and post-match evaluation, but never exposes token counts, bankroll/stake diagnostics, snapshot hashes, frozen AI input payloads, or decision-linked future-odds captures to an anonymous viewer.

Authentication does **not** enable remote deployment by itself. The runtime remains loopback-only; TLS, reverse-proxy trust, origin policy, cookie security behind HTTPS, and remote deployment hardening must be designed as a separate explicit mode before non-loopback serving is allowed.

## Passwordless login flow

1. The browser submits an email address to `POST /api/auth/request-code`.
2. The server normalizes the address and creates a six-digit one-time challenge.
3. Only an HMAC-SHA256 digest of the code is persisted. The plaintext code exists only long enough to deliver the login email.
4. The code is valid for 10 minutes by default, has a 60-second resend cooldown, and allows at most five verification attempts by default.
5. `POST /api/auth/verify-code` consumes the challenge on success. A new `user_accounts` row is created on the first successful verification; later successful logins update the same normalized-email identity.
6. The server generates a cryptographically random session token. Only its SHA-256 digest is stored in `auth_sessions`.
7. The browser receives the token only in the `dota_session` cookie with `HttpOnly` and `SameSite=Strict`. `Secure` remains configurable because the current supported runtime is loopback HTTP; it must be enabled for any future HTTPS deployment.
8. `POST /api/auth/logout` revokes the persisted session before deleting the browser cookie.

Wrong-code attempt counts and exhausted/expired challenge state must be committed before an authentication error is returned. Transaction rollback must never restore a consumed attempt.

## Email identity

Email addresses are normalized before persistence: Unicode NFKC normalization, whitespace/control-character rejection, lowercase local/domain representation, and IDNA normalization for the domain. Application code is the only supported writer for user identities.

The system deliberately does not expose whether an email already owns an account. Requesting a code always follows the same login path; account creation is deferred until successful proof of inbox control.

## Configuration

Authentication uses the existing Resend transport but is independent from decision-email notifications. `EMAIL_NOTIFICATIONS_ENABLED` may remain false while login email is enabled.

Required when `AUTH_ENABLED=true`:

- `RESEND_API_KEY`
- `RESEND_FROM`
- `AUTH_SECRET_KEY` of at least 32 bytes

Recommended secret generation:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Relevant settings:

- `AUTH_LOGIN_CODE_TTL_SECONDS` (default 600)
- `AUTH_LOGIN_RESEND_COOLDOWN_SECONDS` (default 60)
- `AUTH_LOGIN_MAX_ATTEMPTS` (default 5)
- `AUTH_SESSION_TTL_DAYS` (default 30)
- `AUTH_COOKIE_SECURE` (false for the current loopback HTTP runtime)
- `AUTH_EMAIL_SUBJECT_PREFIX`

An enabled but incomplete authentication configuration is a startup error rather than a partially working mode.

## Premium entitlements

`user_accounts.id` is the stable identity used by `user_entitlements` and Notification Center bindings. Infrastructure credentials remain installation-scoped: the Resend API key, QQ Bot AppID/AppSecret, and WeChat ClawBot bot credentials belong to the runtime installation and must never be copied into a user record.

Current premium entitlement names are:

- `ai_decisions`: access to live/historical AI decision intelligence.
- `realtime_notifications`: access to user-level Email, QQ, and WeChat AI decision delivery.

Development grants are explicit. After a user has verified an email and created an account, use the local CLI instead of weakening route checks:

```powershell
python -m tools.entitlements grant --email owner@example.com
python -m tools.entitlements revoke --email owner@example.com
```

Omitting `--entitlement` grants or revokes all currently defined premium entitlements. To change only notifications:

```powershell
python -m tools.entitlements grant --email owner@example.com --entitlement realtime_notifications
python -m tools.entitlements revoke --email owner@example.com --entitlement realtime_notifications
```

## Notification Center

Phase 4 adds a user-scoped Notification Center at `/notifications`. The existing notification trigger remains unchanged: fan-out is prepared only after the AI round is complete and a **new BUY decision** exists. Notification Center changes who receives that event, not when an AI event is considered notification-worthy.

The channel-neutral persistence model is:

- `notification_bindings`: verified external destinations owned by one `user_accounts.id`.
- `notification_preferences`: per-user event/channel on/off choices.
- `notification_pairing_codes`: short-lived, one-time proof used to bind bot conversations.
- `notification_deliveries`: an independent durable delivery ledger entry for every user binding, event, snapshot, and AI-decision batch.

For each fan-out, only bindings whose owner has an active `realtime_notifications` entitlement and enabled channel preference are selected. Binding status, preference, and entitlement are checked **again immediately before actual send**, so revoking access or opting out also cancels already queued deliveries.

Each destination receives its own idempotency key and delivery state. A retry for one QQ or WeChat target therefore does not resend an email or another target that already succeeded.

### Notification Center API

The account UI uses:

- `GET /api/notifications`: bindings, preferences, and recent delivery ledger.
- `POST /api/notifications/bindings/email`: bind the current account's verified login email.
- `POST /api/notifications/qr/{channel}/start`: start a per-user QQ or WeChat QR session.
- `POST /api/notifications/qr/{channel}/{session_id}`: poll and confirm that QR session.
- `DELETE /api/notifications/qr/{channel}/{session_id}`: cancel that QR session.
- `PUT /api/notifications/preferences/{channel}`: enable/disable AI decision delivery for that channel.
- `DELETE /api/notifications/bindings/{binding_id}`: disable one owned destination.

These surfaces require an authenticated user with `realtime_notifications`.

### Email binding

Email is not an arbitrary address entered in a form. The user explicitly binds the already verified passwordless-login email from Notification Center. Resend remains the transport provider.

`EMAIL_NOTIFICATIONS_ENABLED=true` enables the decision-email transport. Product recipients come from verified user bindings; legacy `EMAIL_RECIPIENTS` is retained only for compatibility and is no longer required for user-scoped delivery.

### QQ binding

The QQ bridge is infrastructure, but account ownership is per user. Notification Center starts a connector QR
session; the user scans with phone QQ, and the connector returns a dedicated AppID/AppSecret plus
that user's `userOpenid`. Those credentials stay in the local QQ state directory, while the
Notification Center binding stores only the account ID and C2C target. The same user can have only
one active QR-owned QQ account per channel. The older shared-bot share-link/`绑定 <code>` flow is
kept only for legacy installations.

After pairing, `订阅通知` and `退订通知` toggle the preference for the bound QQ destination. Ordinary bot query commands continue to use the existing QQ command behavior.

### WeChat binding

The primary flow is user-owned QR binding. An authenticated user starts a QR session in
Notification Center and scans it with their own WeChat account. After Tencent confirms the login,
the returned `bot_token`, `ilink_bot_id`, and `ilink_user_id` are persisted only in the local
WeChat state directory, with the site user's ID stored as non-secret ownership metadata. A
verified Notification Center binding is created for that account and notifications target the
scanned `ilink_user_id`. No shared administrator account or public contact link is required.

The CLI `tools/wechat_clawbot.py login` path remains available for operator diagnostics and legacy
shared accounts; it is not the normal user onboarding path.

After pairing, `订阅通知` and `退订通知` toggle the WeChat preference. Ordinary bot query commands continue to use the existing WeChat command behavior.

### Pairing-code security

Pairing codes expire after roughly ten minutes. Generating a new code invalidates older unconsumed codes for the same user/channel. Only a SHA-256 digest is persisted; the raw code exists only long enough to display it to the signed-in user and send it back through the bot conversation.

A bot observing a chat contact by itself is **not** proof that a logged-in application user owns that destination. Only successful code consumption creates a verified user binding.

## Billing

Billing/payment processing is deliberately not part of Phases 2-4. Development grants are explicit and auditable. A future billing integration should grant and revoke the same `user_entitlements` records rather than introduce a second authorization model.

## Data retention and secrets

The database does not contain plaintext login codes, plaintext session bearer tokens, or plaintext Notification Center pairing codes. Login challenge rows remain as audit records after consumption; sessions retain revocation/expiry metadata; notification deliveries retain target-independent status/error metadata for audit and retry behavior.

`AUTH_SECRET_KEY`, Resend credentials, QQ Bot credentials, and WeChat bot credentials belong in private runtime configuration/state and must never be returned through the authenticated user API.

## Verification requirements

Changes to authentication, premium authorization, or Notification Center must retain tests for:

- email normalization and malformed-address rejection;
- resend cooldown and challenge replacement;
- persisted failed-attempt counting and maximum-attempt exhaustion;
- successful first-user creation and repeat-login identity reuse;
- session authentication, expiry/revocation behavior, and logout;
- `HttpOnly` + `SameSite=Strict` cookie attributes;
- anonymous ordinary match access;
- `401` for unauthenticated in-progress AI access;
- `403` for authenticated users missing a required entitlement;
- successful in-progress AI access only with Free group-stage access or an active entitlement;
- anonymous settled-map AI access through the redacted post-match projection;
- expired/future/revoked entitlement handling;
- public match payload redaction of AI decisions;
- verified Notification Center destination ownership;
- cross-account destination claim rejection;
- per-target delivery idempotency;
- preference and entitlement rechecks before send;
- Free-user Notification Center lock state and entitled-user pairing flow;
- authentication-disabled behavior for public settled-map AI while unsettled AI remains closed;
- Alembic upgrade/check from a clean PostgreSQL database.

## Phase scope

The current implementation covers public/premium API separation, capability entitlements, one-time competition-pass checkout/webhooks, and the user Notification Center. Production remote-host deployment hardening remains a separate explicit mode. Payment integrations must continue to use the server-owned purchase mapping and entitlement ledger.
