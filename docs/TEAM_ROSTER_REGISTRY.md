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

A maintained `team_profiles.valve_team_id` that conflicts with the existing OpenDota mapping is fail-closed: registry population skips the team and does not attach provider roster data until the identity conflict is reviewed.

## Registry population

Use the registry population command to turn existing canonical/OpenDota team mappings into maintainable team profiles and current player rosters:

```bash
uv run python -m tools.sync_team_registry
```

Populate selected canonical teams only:

```bash
uv run python -m tools.sync_team_registry --team-id <canonical-team-uuid>
```

The population pass:

- reuses the canonical → OpenDota mapping already resolved by the historical identity layer
- creates a stable team slug when one is missing
- fills a missing short tag from the OpenDota team catalog when available
- fills a missing Dota/Valve Team ID from the existing provider mapping
- fills a missing logo URL using the Valve/Steam Dota team-logo CDN pattern
- fills missing provider provenance fields
- synchronizes current players through the same temporal roster service described below
- preserves already maintained slug, tag, logo, website and source fields
- never overwrites a conflicting maintained Valve Team ID

The command is a maintenance operation. It does not imply that every historical Dota team has already been populated in a particular deployment. Run it after identity discovery, or schedule it in the deployment's maintenance workflow as appropriate.

## Player roster synchronization

For a roster-only refresh, run:

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
- never clears a known roster from an empty or incomplete source response

OpenDota is used as an identity/roster discovery source. It is not treated as the official artwork source.

## Coaches and other staff

Staff should be maintained from a reliable announcement, official team page or tournament registration source. Store that source in `source_url` and use membership dates whenever they are known.

Do not infer a coach solely from an old player association or a third-party image filename. Unknown staff remains unknown until a reliable source is recorded.

## Public API and pages

`GET /api/teams`

Returns the team directory used by the frontend visual-identity layer.

`GET /api/teams/{canonical_team_id}`

Returns the maintained team profile plus:

- `current_roster`
- `roster_history`

`GET /api/teams/by-slug/{slug}`

Returns the same detail payload through the stable public team slug used by the product route.

Public team pages live at:

```text
/teams/{slug}
```

They show maintained identity, current players, confirmed coaching/staff records, synced upcoming/recent matches and roster history. Team crests on match/event surfaces link to this page once a registry slug exists.

These APIs and pages are public because team/roster identity is ordinary tournament information; they do not expose AI decisions or paid entitlements.
