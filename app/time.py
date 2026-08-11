from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def earliest(first: datetime, second: datetime) -> datetime:
    return first if ensure_utc(first) <= ensure_utc(second) else second


def elapsed_seconds(later: datetime, earlier: datetime) -> float:
    return (ensure_utc(later) - ensure_utc(earlier)).total_seconds()
