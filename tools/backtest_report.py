import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.db import create_engine, create_session_factory
from app.evaluation.backtest import BacktestService


async def _run(
    *,
    provider: str | None,
    model: str | None,
    prompt_version: str | None,
    ai_view_version: str | None,
    calibration_bins: int,
    include_snapshot_payload: bool,
) -> dict:
    engine = create_engine(get_settings())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            return await BacktestService().build_report(
                session,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                ai_view_version=ai_view_version,
                calibration_bins=calibration_bins,
                include_snapshot_payload=include_snapshot_payload,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export settled AI decision ROI, calibration and CLV by experiment version"
    )
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--prompt-version")
    parser.add_argument("--ai-view-version")
    parser.add_argument("--calibration-bins", type=int, default=10)
    parser.add_argument("--include-snapshot-payload", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = asyncio.run(
        _run(
            provider=args.provider,
            model=args.model,
            prompt_version=args.prompt_version,
            ai_view_version=args.ai_view_version,
            calibration_bins=args.calibration_bins,
            include_snapshot_payload=args.include_snapshot_payload,
        )
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(encoded)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
