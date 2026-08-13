import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.db import create_engine, create_session_factory
from app.shadow_audit import build_shadow_run_audit


async def _run(canonical_map_id: UUID) -> dict:
    engine = create_engine(get_settings())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            return await build_shadow_run_audit(
                session,
                canonical_map_id=canonical_map_id,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export structured evidence from a real Dota shadow run"
    )
    parser.add_argument("--canonical-map-id", required=True, type=UUID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = asyncio.run(_run(args.canonical_map_id))
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(encoded)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
