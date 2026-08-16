# Email Authentication Contract

Dota AI Decision Lab uses passwordless email authentication as the identity foundation for user-scoped premium access and notification bindings. Authentication answers **who the user is**; entitlements answer **what that user may access**.

## Access model

Ordinary match browsing is public. A visitor does not need an account to view match identity, teams, draft/lineup information, market data, live state, or ordinary historical match context.

Authentication is required for account-scoped or operational surfaces. Premium AI intelligence requires both a valid authenticated session and the `ai_decisions` entitlement. Real-time delivery channels use the separate `realtime_notifications` entitlement so notification access can evolve independently from page access.

The current HTTP policy is:

- `PUBLIC`: `/health`, `/ready`, `/api/auth/*`, `/api/runtime`, `/api/matches`, ordinary `/api/maps/{id}` and other ordinary match-data APIs.
- `AUTHENTICATED`: `/metrics`, `/api/jobs/summary`, and future `/api/account/*` routes.
- `ENTITLED(ai_decisions)`: `/api/maps/{id}/ai-decisions`, `/api/snapshots/*`, and `/api/review/*`.

`/ws/status` remains public because it carries ordinary live-refresh events used by the public match experience. Any future private WebSocket path must require authentication and, where appropriate, an explicit entitlement.

Public match responses must never contain the premium decision payload. They may expose non-sensitive analysis readiness metadata such as whether a decision snapshot exists, when analysis last updated, and how many models completed. They must not expose BUY/PASS direction, confidence, fair probability, stake, primary reasons, counterarguments, frozen AI input payloads, or decision-linked future-odds captures.

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

## Entitlements and notification identity

`user_accounts.id` is the stable identity used by `user_entitlements` and future notification bindings. Infrastructure credentials remain installation-scoped: the Resend API key, QQ Bot AppID/AppSecret, and WeChat ClawBot bot credentials belong to the runtime installation and must never be copied into a user record.

Current premium entitlement names are:

- `ai_decisions`: access to live/historical AI decision intelligence.
- `realtime_notifications`: eligibility for paid real-time notification delivery once Notification Center bindings are introduced.

Development grants are explicit. After a user has verified an email and created an account, use the local CLI instead of weakening route checks:

```powershell
python -m tools.entitlements grant --email owner@example.com
python -m tools.entitlements revoke --email owner@example.com
```

A future Notification Center should point from the authenticated `user_accounts.id` to verified destination identities such as email, QQ C2C OpenID, WeChat direct-chat identity, Telegram, Discord, push, or webhook destinations. A bot observing a chat contact is not proof that the logged-in user owns that destination.

## Data retention and secrets

The database does not contain plaintext login codes or plaintext session bearer tokens. Login challenge rows remain as audit records after consumption; sessions retain revocation/expiry metadata. A later maintenance task may prune expired records, but pruning must not change authentication semantics.

`AUTH_SECRET_KEY`, Resend credentials, QQ Bot credentials, and WeChat bot credentials belong in private runtime configuration/state and must never be returned through the authenticated user API.

## Verification requirements

Changes to authentication or premium authorization must retain tests for:

- email normalization and malformed-address rejection;
- resend cooldown and challenge replacement;
- persisted failed-attempt counting and maximum-attempt exhaustion;
- successful first-user creation and repeat-login identity reuse;
- session authentication, expiry/revocation behavior, and logout;
- `HttpOnly` + `SameSite=Strict` cookie attributes;
- anonymous ordinary match access;
- `401` for unauthenticated premium access;
- `403` for authenticated users missing a required entitlement;
- successful premium access only with an active entitlement;
- expired/future/revoked entitlement handling;
- public match payload redaction of AI decisions;
- authentication-disabled backward compatibility for public APIs while premium APIs remain closed;
- Alembic upgrade/check from a clean PostgreSQL database.
