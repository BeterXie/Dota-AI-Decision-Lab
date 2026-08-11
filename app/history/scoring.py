from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class EloUpdate:
    rating_a: float
    rating_b: float
    expected_a: float
    expected_b: float


def update_elo(
    rating_a: float,
    rating_b: float,
    winner: str,
    *,
    k: float = 24.0,
) -> EloUpdate:
    if winner not in {"A", "B"}:
        raise ValueError("winner must be A or B")
    expected_a = 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))
    expected_b = 1.0 - expected_a
    score_a = 1.0 if winner == "A" else 0.0
    score_b = 1.0 - score_a
    return EloUpdate(
        rating_a=rating_a + k * (score_a - expected_a),
        rating_b=rating_b + k * (score_b - expected_b),
        expected_a=expected_a,
        expected_b=expected_b,
    )


def weighted_recent_win_form(results: list[bool]) -> float | None:
    if not results:
        return None
    return _weighted_groups([1.0 if result else 0.0 for result in results[:20]], center=True)


def recent_player_form(scores: list[float]) -> float | None:
    return _weighted_groups(scores[:20], center=False) if scores else None


def _weighted_groups(values: list[float], *, center: bool) -> float | None:
    groups = ((values[0:5], 0.50), (values[5:10], 0.30), (values[10:20], 0.20))
    weighted = 0.0
    used_weight = 0.0
    for group, weight in groups:
        if not group:
            continue
        weighted += mean(group) * weight
        used_weight += weight
    if not used_weight:
        return None
    result = weighted / used_weight
    return (result - 0.5) * 2.0 if center else result


def roster_stability(exact_maps: int) -> float:
    if exact_maps < 0:
        raise ValueError("exact_maps cannot be negative")
    return min(exact_maps / 20.0, 1.0)


def role_metric_z(value: float | None, mean_value: float | None, std: float | None) -> float | None:
    if value is None or mean_value is None or std is None or std <= 0:
        return None
    return max(-3.0, min(3.0, (value - mean_value) / std))


def weighted_metric_score(
    metric_z: dict[str, float | None], weights: dict[str, float]
) -> float | None:
    weighted_values: list[float] = []
    used_weights: list[float] = []
    for name, weight in weights.items():
        value = metric_z.get(name)
        if value is None:
            continue
        weighted_values.append(value * weight)
        used_weights.append(abs(weight))
    if not used_weights:
        return None
    return sum(weighted_values) / sum(used_weights)


def sample_confidence(sample: int, target: int = 20) -> float:
    if sample < 0 or target <= 0:
        raise ValueError("sample must be non-negative and target positive")
    return min(sample / target, 1.0)


def player_form_confidence(
    sample: int,
    *,
    data_completeness: float,
    role_identity_confidence: float,
) -> float:
    return (
        0.55 * sample_confidence(sample)
        + 0.25 * _unit(data_completeness)
        + 0.20 * _unit(role_identity_confidence)
    )


def beta_adjusted_win_rate(
    wins: int,
    matches: int,
    *,
    prior_mean: float = 0.50,
    prior_strength: float = 12.0,
) -> float | None:
    if matches < 0 or wins < 0 or wins > matches or not 0 <= prior_mean <= 1:
        return None
    if prior_strength <= 0:
        raise ValueError("prior_strength must be positive")
    alpha = prior_mean * prior_strength
    beta = (1.0 - prior_mean) * prior_strength
    return (wins + alpha) / (matches + alpha + beta)


def combine_supported(values: list[tuple[float | None, float]]) -> float | None:
    available = [(value, weight) for value, weight in values if value is not None and weight > 0]
    if not available:
        return None
    total_weight = sum(weight for _, weight in available)
    return sum(value * weight for value, weight in available) / total_weight


def position_fit(current_position_maps: int, all_recent_player_hero_maps: int) -> float | None:
    if current_position_maps < 0 or all_recent_player_hero_maps < 0:
        raise ValueError("map counts cannot be negative")
    if all_recent_player_hero_maps == 0:
        return None
    return min(current_position_maps / all_recent_player_hero_maps, 1.0)


def player_hero_confidence(
    historical_maps: int,
    recent_maps: int,
    patch_maps: int,
    identity_confidence: float,
) -> float:
    hist = min(max(historical_maps, 0) / 40.0, 1.0)
    recent = min(max(recent_maps, 0) / 15.0, 1.0)
    patch = min(max(patch_maps, 0) / 8.0, 1.0)
    return 0.30 * hist + 0.35 * recent + 0.20 * patch + 0.15 * _unit(identity_confidence)


def _unit(value: float) -> float:
    return min(max(value, 0.0), 1.0)
