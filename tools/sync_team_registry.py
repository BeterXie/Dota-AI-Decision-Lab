from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db import create_engine, create_session_factory
from app.identity.team_registry_population import TeamRegistryPopulationService
from app.models import ProviderTeamMapping
from app.providers.opendota.client import OpenDotaClient
from app.repositories.raw import RawEventRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate maintained team profiles and current player rosters."
    )
    parser.add_argument(
        "--team-id",
        action="append",
        default=[],
        help="Canonical team UUID to populate. Repeat for multiple teams; omitted populates all mapped teams.",
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
    service = TeamRegistryPopulationService(RawEventRepository())
    try:
        requested = [UUID(value) for value in team_ids]
        if not requested:
            async with session_factory() as session:
                requested = list(
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
        async with session_factory.begin() as session:
            results = await service.populate(
                session,
                client,
                canonical_team_ids=requested,
            )
        return [
            {
                "team_id": str(result.team_id),
                "valve_team_id": result.valve_team_id,
                "slug": result.slug,
                "profile_created": result.profile_created,
                "skipped": result.skipped,
                "roster": (
                    {
                        "current_players": result.roster.current_players,
                        "created_players": result.roster.created_players,
                        "created_memberships": result.roster.created_memberships,
                        "closed_memberships": result.roster.closed_memberships,
                        "skipped": result.roster.skipped,
                    }
                    if result.roster is not None
                    else None
                ),
            }
            for result in results
        ]
    finally:
        await client.close()
        await engine.dispose()


def main() -> None:
    args = parse_args()
    results = asyncio.run(run(args.team_id))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
