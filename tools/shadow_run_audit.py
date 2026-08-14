import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.db import create_engine, create_session_factory
from app.shadow_audit import build_shadow_run_audit
from app.shadow_series_audit import build_shadow_series_audit


async def _run(
    canonical_map_id: UUID | None,
    canonical_series_id: UUID | None,
) -> dict:
    engine = create_engine(get_settings())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            if canonical_map_id is not None:
                return await build_shadow_run_audit(
                    session,
                    canonical_map_id=canonical_map_id,
                )
            if canonical_series_id is not None:
                return await build_shadow_series_audit(
                    session,
                    canonical_series_id=canonical_series_id,
                )
            raise ValueError("canonical map or series is required")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export structured evidence from a real Dota shadow run"
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--canonical-map-id", type=UUID)
    target.add_argument("--canonical-series-id", type=UUID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = asyncio.run(_run(args.canonical_map_id, args.canonical_series_id))
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(encoded)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
