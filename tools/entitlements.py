import argparse
import asyncio

from sqlalchemy import select

from app.auth.models import UserAccountRecord
from app.auth.service import normalize_email
from app.config import get_settings
from app.db import create_engine, create_session_factory
from app.entitlements import PREMIUM_ENTITLEMENTS, EntitlementService

_DEVELOPMENT_SOURCE = "development-cli"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grant or revoke development premium entitlements for a verified user."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("grant", "revoke"):
        item = subparsers.add_parser(command)
        item.add_argument("--email", required=True)
        item.add_argument(
            "--entitlement",
            choices=sorted(PREMIUM_ENTITLEMENTS),
            action="append",
            help="Repeat to select specific entitlements; omitted means all premium entitlements.",
        )
    return parser


async def _run(command: str, raw_email: str, requested: list[str] | None) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        email = normalize_email(raw_email)
        async with factory() as session:
            user = await session.scalar(
                select(UserAccountRecord).where(UserAccountRecord.email == email).limit(1)
            )
        if user is None:
            raise SystemExit(f"No verified user account exists for {email}")

        service = EntitlementService(factory)
        entitlements = tuple(requested or sorted(PREMIUM_ENTITLEMENTS))
        for entitlement in entitlements:
            if command == "grant":
                await service.grant(user.id, entitlement, source=_DEVELOPMENT_SOURCE)
            else:
                await service.revoke(user.id, entitlement, source=_DEVELOPMENT_SOURCE)

        active = await service.active_entitlements(user.id)
        print(f"{email}: {', '.join(active) if active else 'no active premium entitlements'}")
    finally:
        await engine.dispose()


def main() -> None:
    args = _parser().parse_args()
    asyncio.run(_run(args.command, args.email, args.entitlement))


if __name__ == "__main__":
    main()
