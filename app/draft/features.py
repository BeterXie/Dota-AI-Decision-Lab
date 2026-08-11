from collections.abc import Sequence
from datetime import datetime
from statistics import mean

from app.domain.draft import DraftCurve, DraftDerivedFeatures, DraftMinutePoint


def build_draft_curve(
    rosh_result: dict,
    *,
    current_minute: int | None,
    statistics_cutoff: datetime,
    data_version: str,
) -> DraftCurve:
    pure = {row["minute"]: row for row in rosh_result.get("pure_minute_table", [])}
    adjusted = {row["minute"]: row for row in rosh_result.get("minute_table", [])}
    minutes = sorted(set(pure) | set(adjusted))
    points = tuple(
        DraftMinutePoint(
            minute=minute,
            pure_radiant_edge=_edge(pure.get(minute)),
            adjusted_radiant_edge=_edge(adjusted.get(minute)),
            support=_support(adjusted.get(minute) or pure.get(minute)),
            confidence=_confidence(adjusted.get(minute) or pure.get(minute)),
        )
        for minute in minutes
        if 20 <= minute <= 60
    )
    return DraftCurve(
        points=points,
        features=derive_features(points, current_minute=current_minute),
        statistics_cutoff=statistics_cutoff,
        model_version=rosh_result["model_version"],
        data_version=data_version,
    )


def derive_features(
    points: Sequence[DraftMinutePoint], *, current_minute: int | None
) -> DraftDerivedFeatures:
    adjusted = {
        point.minute: point.adjusted_radiant_edge
        for point in points
        if point.adjusted_radiant_edge is not None
    }
    current = current_minute if current_minute is not None and current_minute >= 20 else None
    current_edge = _nearest(adjusted, current) if current is not None else None
    peak_minute = max(adjusted, key=lambda minute: abs(adjusted[minute])) if adjusted else None
    peak_edge = adjusted.get(peak_minute) if peak_minute is not None else None
    return DraftDerivedFeatures(
        current_minute=current,
        current_edge=current_edge,
        next_5m_edge=_window_average(adjusted, current, 5),
        next_10m_edge=_window_average(adjusted, current, 10),
        peak_minute=peak_minute,
        peak_edge=peak_edge,
        cross_over_minute=_cross_over(adjusted),
        early_average=_range_average(adjusted, 20, 29),
        mid_average=_range_average(adjusted, 30, 39),
        late_average=_range_average(adjusted, 40, 49),
        ultra_late_average=_range_average(adjusted, 50, 60),
        curve_slope_5m=_slope(adjusted, current, 5),
        curve_slope_10m=_slope(adjusted, current, 10),
    )


def _edge(row: dict | None) -> float | None:
    value = row.get("win_rate_graph") if row is not None else None
    return float(value) if isinstance(value, (int, float)) else None


def _support(row: dict | None) -> int | None:
    if row is None:
        return None
    support = row.get("support")
    return support if isinstance(support, int) and not isinstance(support, bool) else None


def _confidence(row: dict | None) -> float | None:
    if row is None:
        return None
    confidence = row.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None
    return min(max(float(confidence), 0.0), 1.0)


def _nearest(values: dict[int, float], minute: int) -> float | None:
    if not values:
        return None
    nearest_minute = min(values, key=lambda value: abs(value - minute))
    return values[nearest_minute]


def _window_average(values: dict[int, float], start: int | None, width: int) -> float | None:
    if start is None:
        return None
    selected = [value for minute, value in values.items() if start <= minute <= start + width]
    return mean(selected) if selected else None


def _range_average(values: dict[int, float], start: int, end: int) -> float | None:
    selected = [value for minute, value in values.items() if start <= minute <= end]
    return mean(selected) if selected else None


def _slope(values: dict[int, float], start: int | None, width: int) -> float | None:
    if start is None:
        return None
    first = _nearest(values, start)
    last = _nearest(values, min(start + width, 60))
    return (last - first) / width if first is not None and last is not None else None


def _cross_over(values: dict[int, float]) -> int | None:
    previous: float | None = None
    for minute in sorted(values):
        value = values[minute]
        if previous is not None and ((previous < 0 < value) or (previous > 0 > value)):
            return minute
        previous = value
    return None
