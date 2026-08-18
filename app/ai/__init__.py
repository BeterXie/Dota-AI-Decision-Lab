from app.ai.anthropic import AnthropicDecisionProvider
from app.ai.chat_completions import KimiDecisionProvider
from app.ai.deepseek import DeepSeekDecisionProvider
from app.ai.gemini import GeminiDecisionProvider
from app.ai.openai import LocalOpenAiDecisionProvider, OpenAiDecisionProvider


class AiCoordinator:
    """Construct the DB-aware coordinator lazily to avoid import cycles."""

    def __new__(cls, *args, **kwargs):
        from app.runtime_config.ai_coordinator import RuntimeAiCoordinator

        return RuntimeAiCoordinator(*args, **kwargs)


__all__ = [
    "AiCoordinator",
    "AnthropicDecisionProvider",
    "DeepSeekDecisionProvider",
    "GeminiDecisionProvider",
    "KimiDecisionProvider",
    "LocalOpenAiDecisionProvider",
    "OpenAiDecisionProvider",
]
