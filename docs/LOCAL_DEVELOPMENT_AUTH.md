# Local Development Login

The normal application keeps passwordless login tied to Resend. For local feature verification, use the explicit loopback-only development mode instead of configuring a real mail provider or weakening route authorization.

## One-click start on Windows

Run:

```cmd
start-local-auth.cmd
```

The wrapper starts the normal `app.main` runtime with:

- `AUTH_ENABLED=true`
- a persistent local `AUTH_SECRET_KEY` stored under the ignored `.runtime` directory
- `AUTH_COOKIE_SECURE=false` for loopback HTTP
- `DOTA_LOCAL_AUTH_ENABLED=true`
- `DOTA_LOCAL_AUTH_EMAIL=dev@localhost` by default

No Resend API key or sender address is required in this mode.

## Login as the local Pro account

1. Open the application on the normal loopback URL.
2. Choose **Login** and enter `dev@localhost`.
3. Request the login code.
4. Read the generated code:

```cmd
type .runtime\local-login-code.txt
```

5. Enter the six-digit `code=` value in the login form.

This still runs the real challenge verification and creates the normal HttpOnly `dota_session` cookie. The `dev@localhost` account is then granted both current GLOBAL premium entitlements through the existing entitlement table:

- `ai_decisions`
- `realtime_notifications`

That makes local verification of `/performance`, AI decision views, review surfaces, and Notification Center use the same backend authorization checks as an entitled production account.

## Test the Free-user path too

While local development auth is enabled, another address such as `free@localhost` can also request a code. The runtime file is overwritten with that address's current code, but only `DOTA_LOCAL_AUTH_EMAIL` is automatically granted Pro entitlements.

This makes it easy to verify both sides locally:

- `dev@localhost` -> authenticated + GLOBAL Pro
- `free@localhost` -> authenticated + no automatic premium entitlement

Use logout before switching accounts.

## Safety boundaries

Local development auth is deliberately separate from production email delivery:

- it is off unless `DOTA_LOCAL_AUTH_ENABLED` is explicitly enabled in the process environment;
- it refuses to run unless normal auth is enabled;
- it refuses non-loopback hosts;
- it refuses `AUTH_COOKIE_SECURE=true`, because the supported local URL is loopback HTTP;
- the plaintext one-time code is written only into `.runtime`, which is git-ignored;
- the normal Resend sender remains unchanged when local development auth is off.

The mode does not create a frontend authentication mock and does not bypass entitlement middleware. It only substitutes local OTP delivery and an explicit development entitlement allowlist.

## Use a different local Pro email

Set the environment variable before launching the wrapper:

```cmd
set DOTA_LOCAL_AUTH_EMAIL=owner@localhost
start-local-auth.cmd
```

The value is normalized by the same email-normalization code as normal login.

## Return to normal email login

Use the ordinary launcher:

```cmd
start-app.cmd
```

and configure `AUTH_ENABLED`, `AUTH_SECRET_KEY`, `RESEND_API_KEY`, and `RESEND_FROM` in `.env` as documented in `docs/AUTHENTICATION.md`. The local-only process environment set by `start-local-auth.cmd` does not persist after the wrapper exits.
