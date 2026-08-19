# DotaScope product brand

## Canonical public identity

- Product name: **DotaScope**
- Primary domain: **dotascope.com**
- English descriptor: **AI-powered Dota match intelligence**
- Chinese descriptor: **AI 驱动的 Dota 比赛情报与决策分析**

`DotaScope` is the public product brand. New user-facing UI, authentication copy, billing copy, email copy, page metadata, social metadata, and deployment surfaces should use this name instead of `Dota AI Decision Lab`.

## What does not get renamed automatically

The repository remains `Dota-AI-Decision-Lab` for now. Historical experiment identities, database migration names, persisted audit values, API contracts, telemetry/service identifiers, provider User-Agent strings, environment-variable names, and other machine-facing identifiers must not be renamed merely for branding. They are technical or historical contracts and may be changed only through an explicit compatibility review.

## Frontend source of truth

User-facing frontend code should import product identity from `frontend/src/brand.ts` instead of duplicating brand strings.

## Domain rollout

The intended production hierarchy is:

- `https://dotascope.com` — canonical product URL
- `https://www.dotascope.com` — redirect to the canonical product URL
- `https://api.dotascope.com` — reserved for a future separated public API only if deployment architecture needs it

Do not hard-code these production hosts into local-development or test runtime paths. Public origin and OAuth callback configuration remains environment/runtime controlled.

## Migration rule

Brand migration must not weaken access control, billing entitlements, auditability, no-future-leakage guarantees, provider boundaries, or CI gates. Prefer small user-facing changes and keep the existing technical contracts stable.

## Visual identity

The existing geometric product mark may remain during the first migration phase. A dedicated logo/icon/favicon/social-card pass should be reviewed separately so visual changes do not get mixed with access or runtime behavior.
