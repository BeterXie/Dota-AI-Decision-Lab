import os

from app.ai.anthropic import AnthropicDecisionProvider
from app.ai.chat_completions import KimiDecisionProvider
from app.ai.coordinator import AiCoordinator as StaticAiCoordinator
from app.ai.deepseek import DeepSeekDecisionProvider
from app.ai.gemini import GeminiDecisionProvider
from app.ai.openai import LocalOpenAiDecisionProvider, OpenAiDecisionProvider

if os.environ.get("DOTA_RUNTIME_CONFIG_MASTER_KEY"):
    from app.runtime_config.ai_coordinator import RuntimeAiCoordinator as AiCoordinator
else:
    AiCoordinator = StaticAiCoordinator

__all__ = [
    "AiCoordinator",
    "AnthropicDecisionProvider",
    "DeepSeekDecisionProvider",
    "GeminiDecisionProvider",
    "KimiDecisionProvider",
    "LocalOpenAiDecisionProvider",
    "OpenAiDecisionProvider",
]
