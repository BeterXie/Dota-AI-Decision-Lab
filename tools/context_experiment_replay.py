import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.ai import (
    AiCoordinator,
    AnthropicDecisionProvider,
    DeepSeekDecisionProvider,
    GeminiDecisionProvider,
    OpenAiDecisionProvider,
)
from app.ai.context_replay import ContextReplayExecutor, ContextReplayPlanner
from app.ai.context_runner import AiContextExperimentRunner
from app.config import Settings, get_settings
from app.db import create_engine, create_session_factory


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _run(args: argparse.Namespace) -> dict:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            plan = await ContextReplayPlanner().build_plan(
                session,
                provider=args.provider,
                profiles=args.profile,
                max_maps=args.max_maps,
                max_calls=args.max_calls,
                since=args.since,
                until=args.until,
            )
        payload: dict = {
            "mode": "EXECUTE" if args.execute else "DRY_RUN",
            "plan": plan.as_dict(),
        }
        if not args.execute:
            return payload
        if args.confirm_calls is None:
            raise ValueError("--execute requires --confirm-calls matching the fresh plan")

        provider = _configured_frozen_provider(settings, plan.provider, plan.model)
        coordinator = AiCoordinator(
            [provider],
            timeout_seconds=settings.ai_timeout_seconds,
            portfolio=None,
        )
        try:
            payload["execution"] = await ContextReplayExecutor(
                factory,
                AiContextExperimentRunner(coordinator),
            ).execute(plan, confirm_calls=args.confirm_calls)
        finally:
            await coordinator.close()
        return payload
    finally:
        await engine.dispose()


def _configured_frozen_provider(settings: Settings, provider: str, model: str):
    if provider == "openai":
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required to execute openai replay")
        return OpenAiDecisionProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=model,
            base_url=settings.openai_base_url,
            reasoning_effort=settings.openai_reasoning_effort,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    if provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required to execute anthropic replay")
        return AnthropicDecisionProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=model,
            base_url=settings.anthropic_base_url,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    if provider == "gemini":
        if settings.gemini_api_key is None:
            raise ValueError("GEMINI_API_KEY is required to execute gemini replay")
        return GeminiDecisionProvider(
            api_key=settings.gemini_api_key.get_secret_value(),
            model=model,
            base_url=settings.gemini_base_url,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    if provider == "deepseek":
        if settings.deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required to execute deepseek replay")
        return DeepSeekDecisionProvider(
            api_key=settings.deepseek_api_key.get_secret_value(),
            model=model,
            base_url=settings.deepseek_base_url,
            reasoning_effort=settings.deepseek_reasoning_effort,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    raise ValueError(f"unsupported replay provider: {provider}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute matched historical AI context replay. Dry-run is the default; "
            "provider APIs are called only with --execute and an exact --confirm-calls value."
        )
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=("openai", "anthropic", "gemini", "deepseek"),
    )
    parser.add_argument(
        "--profile",
        action="append",
        required=True,
        help="Context profile to test. Repeat for multiple profiles.",
    )
    parser.add_argument("--max-maps", type=int, default=20)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--since", type=_parse_datetime)
    parser.add_argument("--until", type=_parse_datetime)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-calls", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = asyncio.run(_run(args))
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(encoded)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
