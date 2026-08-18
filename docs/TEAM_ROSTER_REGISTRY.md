# Team & Roster Registry

Dota AI Decision Lab keeps tournament match identity separate from maintained team presentation and roster identity.

The public match feed may discover a team before we know its official logo, current players or coaching staff. The registry provides a durable place to enrich that canonical identity without hard-coding presentation data in React.

## Tables

### `canonical_teams`

Existing stable team identity used by matches, markets, results and historical features.

Do not create a second team row only because a team changes its logo, tag or roster.

### `team_profiles`

Maintained presentation and external identity metadata for a canonical team:

- `slug`
- `short_name`
- `valve_team_id`
- `country_code`
- `logo_url`
- `logo_source`
- `website_url`
- `source_url`
- observation/update timestamps

A manually verified profile has priority over provider-derived identity.

When `logo_url` is absent but `valve_team_id` is known, the frontend builds the Valve/Steam Dota team-logo URL. This keeps the rendered asset on Valve's CDN instead of copying third-party artwork into the repository.

### `canonical_players` + `player_profiles`

`canonical_players` remains the stable competitive player identity and already owns the Dota account id. `player_profiles` adds maintained presentation metadata such as real name, country and avatar provenance.

### `canonical_staff`

Coaches, assistant coaches, analysts and managers have their own identity. They are not forced into `canonical_players`, because many staff members have no relevant competitive Dota account identity.

### `team_roster_memberships`

Temporal relationship between a team and a player/staff member.

Important fields:

- exactly one of `player_id` / `staff_id`
- `role` (`PLAYER`, `COACH`, `ASSISTANT_COACH`, `ANALYST`, `MANAGER`, ...)
- optional player `position` 1–5
- `is_standin`
- `valid_from` / `valid_to`
- `source_name` / `source_url`
- `observed_at`
- `confidence`

Never overwrite an old membership when somebody transfers. Close it with `valid_to` and create the new membership. This lets match/review features ask what roster existed at a historical point in time.

## Identity precedence

For team visuals the product uses this order:

1. maintained `team_profiles.logo_url`
2. maintained `team_profiles.valve_team_id` → Valve/Steam team-logo CDN
3. existing `ProviderTeamMapping(provider='opendota')` → Valve/Steam team-logo CDN
4. temporary frontend compatibility mapping
5. generated abbreviation badge

The compatibility mapping is a migration bridge, not the long-term source of truth.

## Player roster synchronization

The existing OpenDota integration already maintains canonical OpenDota team mappings. Run:

```bash
uv run python -m tools.sync_team_rosters
```

or sync selected canonical teams:

```bash
uv run python -m tools.sync_team_rosters --team-id <canonical-team-uuid>
```

The sync:

- fetches `/teams/{team_id}/players` through the existing rate-limited OpenDota client
- stores the raw response for provenance
- creates missing canonical players by Dota `account_id`
- creates current `PLAYER` memberships
- closes stale memberships that were previously created by the OpenDota sync
- never closes manually/officially maintained memberships merely because OpenDota disagrees
- never clears a known roster from an empty source response

OpenDota is used as an identity/roster discovery source. It is not treated as the official artwork source.

## Coaches and other staff

Staff should be maintained from a reliable announcement, official team page or tournament registration source. Store that source in `source_url` and use membership dates whenever they are known.

Do not infer a coach solely from an old player association or a third-party image filename.

## Public API

`GET /api/teams`

Returns the team directory used by the frontend visual-identity layer.

`GET /api/teams/{canonical_team_id}`

Returns the maintained team profile plus:

- `current_roster`
- `roster_history`

This API is public because team/roster identity is ordinary tournament information; it does not expose AI decisions or paid entitlements.
