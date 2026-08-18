from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db import create_engine, create_session_factory
from app.identity.roster_sync import TeamRosterSyncService
from app.models import ProviderTeamMapping
from app.providers.opendota.client import OpenDotaClient
from app.repositories.raw import RawEventRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync current player rosters into the maintained team registry."
    )
    parser.add_argument(
        "--team-id",
        action="append",
        default=[],
        help="Canonical team UUID to sync. Repeat for multiple teams; omitted syncs all mapped teams.",
    )
    return parser.parse_args()


async def run(team_ids: list[str]) -> list[dict]:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    client = OpenDotaClient(
        settings.opendota_base_url,
        settings.opendota_api_key.get_secret_value() if settings.opendota_api_key else None,
    )
    service = TeamRosterSyncService(RawEventRepository())
    try:
        requested = [UUID(value) for value in team_ids]
        if requested:
            canonical_team_ids = requested
        else:
            async with session_factory() as session:
                canonical_team_ids = list(
                    dict.fromkeys(
                        (
                            await session.scalars(
                                select(ProviderTeamMapping.canonical_team_id).where(
                                    ProviderTeamMapping.provider == "opendota"
                                )
                            )
                        ).all()
                    )
                )

        results: list[dict] = []
        for canonical_team_id in canonical_team_ids:
            async with session_factory.begin() as session:
                result = await service.sync_team(
                    session,
                    client,
                    canonical_team_id=canonical_team_id,
                )
            results.append(
                {
                    "team_id": str(result.team_id),
                    "source_team_id": result.source_team_id,
                    "current_players": result.current_players,
                    "created_players": result.created_players,
                    "created_memberships": result.created_memberships,
                    "closed_memberships": result.closed_memberships,
                    "skipped": result.skipped,
                }
            )
        return results
    finally:
        await client.close()
        await engine.dispose()


def main() -> None:
    args = parse_args()
    results = asyncio.run(run(args.team_id))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
