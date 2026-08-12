import json
from datetime import UTC, datetime
from pathlib import Path

from app.canonical import content_digest
from app.providers.opendota.normalizer import normalize_match as normalize_opendota
from app.providers.stratz.history_queries import MATCH_QUERY, TEAM_MATCHES_QUERY
from app.providers.stratz.history_queries import normalize_match as normalize_stratz

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_opendota_match_normalizes_professional_fact_without_fake_metrics() -> None:
    fetched_at = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
    bundle = normalize_opendota(_fixture("opendota_match.json"), fetched_at=fetched_at)

    assert bundle.match.provider_match_id == "8940730389"
    assert bundle.match.radiant_team_id == "100"
    assert bundle.match.winner_team_id == "100"
    assert bundle.match.first_usable_at == fetched_at
    assert bundle.players[0].won is True
    assert bundle.players[1].won is False
    assert bundle.players[1].gpm is None
    assert bundle.players[1].position == 5
    assert bundle.advanced_available is True


def test_stratz_match_normalizes_imp_and_same_match_identity() -> None:
    fetched_at = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
    bundle = normalize_stratz(_fixture("stratz_match.json"), fetched_at=fetched_at)

    assert bundle.match.provider_match_id == "8940730389"
    assert bundle.match.started_at.tzinfo is UTC
    assert bundle.match.winner_team_id == "100"
    assert bundle.players[0].impact == 24.5
    assert bundle.players[1].gpm is None
    assert bundle.players[1].won is False


def test_stratz_queries_use_current_team_and_player_contract() -> None:
    assert "team(teamId: $teamId)" in TEAM_MATCHES_QUERY
    assert "skip: $skip" in TEAM_MATCHES_QUERY
    assert "imp" in MATCH_QUERY
    assert "stats { imp }" not in MATCH_QUERY


def test_raw_digest_preserves_large_integer_deterministically() -> None:
    payload = {"steamAccountId": 13_143_526_280_079_059_000}
    assert content_digest(payload) == content_digest({"steamAccountId": "13143526280079059000"})
