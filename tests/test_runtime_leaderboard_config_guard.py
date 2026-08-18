from types import SimpleNamespace

from app.evaluation.leaderboard import _runtime_position_config_signatures


def test_runtime_position_signatures_detect_two_config_fingerprints() -> None:
    account = SimpleNamespace(id="account-1")
    positions = {
        "account-1": [
            SimpleNamespace(ai_decision_id="decision-1"),
            SimpleNamespace(ai_decision_id="decision-2"),
        ]
    }
    signatures = _runtime_position_config_signatures(
        [(account, object())],
        positions,
        {
            "decision-1": "gpt-5.6-terra@cfg:aaaaaaaaaaaa",
            "decision-2": "gpt-5.6-terra@cfg:bbbbbbbbbbbb",
        },
    )
    assert signatures == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}


def test_runtime_position_signatures_treat_legacy_plus_runtime_as_mixed() -> None:
    account = SimpleNamespace(id="account-1")
    positions = {
        "account-1": [
            SimpleNamespace(ai_decision_id="decision-1"),
            SimpleNamespace(ai_decision_id="decision-2"),
        ]
    }
    signatures = _runtime_position_config_signatures(
        [(account, object())],
        positions,
        {
            "decision-1": "gpt-5.6-terra",
            "decision-2": "gpt-5.6-terra@cfg:aaaaaaaaaaaa",
        },
    )
    assert signatures == {"LEGACY_UNFINGERPRINTED", "aaaaaaaaaaaa"}
