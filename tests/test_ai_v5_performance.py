from app.ai.base import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ai_prompt_cache_key,
    extract_provider_usage,
)


def test_v5_prompt_preserves_safety_semantics_and_is_compact() -> None:
    assert PROMPT_VERSION == "decision-analyst-v5-performance"
    normalized_prompt = " ".join(SYSTEM_PROMPT.split()).casefold()
    for phrase in (
        "UNKNOWN/null",
        "blockers override model judgment",
        "Never assume Team A is",
        "not independent evidence",
        "vig adjustment",
        "delayed_live_excluded=true",
        "live_sync",
        "never as independent current evidence",
        "Simplified Chinese",
        "stake <= virtual_bankroll.bankroll_before",
    ):
        assert phrase.casefold() in normalized_prompt
    assert len(SYSTEM_PROMPT) < 5000


def test_prompt_cache_key_is_stable_per_experiment() -> None:
    first = ai_prompt_cache_key("openai", "gpt-test")
    assert first == ai_prompt_cache_key("openai", "gpt-test")
    assert first != ai_prompt_cache_key("openai", "gpt-other")
    assert first.startswith("dota-ai-decision:")


def test_usage_extraction_supports_provider_shapes() -> None:
    openai = extract_provider_usage(
        {
            "usage": {
                "input_tokens": 1000,
                "input_tokens_details": {"cached_tokens": 700},
                "output_tokens": 220,
                "output_tokens_details": {"reasoning_tokens": 140},
                "total_tokens": 1220,
            }
        }
    )
    assert openai is not None
    assert (openai.input_tokens, openai.cached_input_tokens, openai.reasoning_tokens) == (
        1000,
        700,
        140,
    )

    anthropic = extract_provider_usage(
        {
            "usage": {
                "input_tokens": 200,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 600,
                "output_tokens": 120,
            }
        }
    )
    assert anthropic is not None
    assert (anthropic.input_tokens, anthropic.cached_input_tokens) == (900, 600)

    gemini = extract_provider_usage(
        {
            "usage": {
                "total_input_tokens": 900,
                "total_cached_tokens": 650,
                "total_output_tokens": 180,
                "total_thought_tokens": 80,
                "total_tokens": 1160,
            }
        }
    )
    assert gemini is not None
    assert (gemini.cached_input_tokens, gemini.reasoning_tokens) == (650, 80)

    deepseek = extract_provider_usage(
        {
            "usage": {
                "prompt_tokens": 800,
                "prompt_cache_hit_tokens": 500,
                "completion_tokens": 200,
                "completion_tokens_details": {"reasoning_tokens": 110},
                "total_tokens": 1000,
            }
        }
    )
    assert deepseek is not None
    assert (deepseek.cached_input_tokens, deepseek.reasoning_tokens) == (500, 110)
