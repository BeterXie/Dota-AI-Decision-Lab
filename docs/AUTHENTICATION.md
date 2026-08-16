# Email Authentication Contract

Dota AI Decision Lab uses passwordless email authentication as the identity foundation for user-scoped notification bindings. This document is normative for the current authentication implementation.

## Scope

Authentication protects browser access to business APIs and WebSockets. It does **not** enable remote deployment by itself. The runtime remains loopback-only; TLS, reverse-proxy trust, origin policy, cookie security behind HTTPS, and remote deployment hardening must be designed as a separate explicit mode before non-loopback serving is allowed.

`/health`, `/ready`, and `/api/auth/*` remain reachable before login. When authentication is enabled, other `/api/*` routes, `/metrics`, and WebSocket connections require a valid session.

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

## Notification identity boundary

Authentication introduces the stable `user_accounts.id` that future notification bindings use. Infrastructure credentials remain installation-scoped: the Resend API key, QQ Bot AppID/AppSecret, and WeChat ClawBot bot credentials belong to the runtime installation and must never be copied into a user record.

User-scoped bindings instead point from a user to a destination identity, for example:

- Email destination: verified email address.
- QQ destination: C2C OpenID (and, if intentionally supported later, an explicitly authorized group target).
- WeChat destination: verified direct-chat user identity associated with the ClawBot account.

A future Notification Center should read and mutate those user bindings using the authenticated `user_accounts.id`. It must not infer ownership merely because a bot has previously observed a chat contact.

## Data retention and secrets

The database does not contain plaintext login codes or plaintext session bearer tokens. Login challenge rows remain as audit records after consumption; sessions retain revocation/expiry metadata. A later maintenance task may prune expired records, but pruning must not change authentication semantics.

`AUTH_SECRET_KEY`, Resend credentials, QQ Bot credentials, and WeChat bot credentials belong in private runtime configuration/state and must never be returned through the authenticated user API.

## Verification requirements

Changes to authentication must retain tests for:

- email normalization and malformed-address rejection;
- resend cooldown and challenge replacement;
- persisted failed-attempt counting and maximum-attempt exhaustion;
- successful first-user creation and repeat-login identity reuse;
- session authentication, expiry/revocation behavior, and logout;
- `HttpOnly` + `SameSite=Strict` cookie attributes;
- unauthenticated HTTP business-route rejection;
- unauthenticated WebSocket rejection;
- authentication-disabled backward compatibility;
- Alembic upgrade/check from a clean PostgreSQL database.
