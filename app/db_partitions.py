from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

PARTITIONED_TABLES: dict[str, str] = {
    "provider_raw_events": "received_at",
    "odds_observations": "received_at",
    "dltv_live_observations": "received_at",
    "decision_future_odds": "due_at",
}


def week_start(value: datetime | date) -> date:
    day = value.date() if isinstance(value, datetime) else value
    return day - timedelta(days=day.weekday())


async def ensure_weekly_partitions(
    engine: AsyncEngine,
    *,
    reference_time: datetime | None = None,
    weeks_behind: int = 1,
    weeks_ahead: int = 8,
) -> int:
    if engine.dialect.name != "postgresql":
        return 0
    reference = reference_time or datetime.now(UTC)
    first_week = week_start(reference) - timedelta(weeks=weeks_behind)
    created = 0
    async with engine.begin() as connection:
        for table, timestamp_column in PARTITIONED_TABLES.items():
            for offset in range(weeks_behind + weeks_ahead + 1):
                start = first_week + timedelta(weeks=offset)
                end = start + timedelta(weeks=1)
                created += await _ensure_partition(
                    connection,
                    table=table,
                    timestamp_column=timestamp_column,
                    start=start,
                    end=end,
                )
    return created


async def _ensure_partition(
    connection: AsyncConnection,
    *,
    table: str,
    timestamp_column: str,
    start: date,
    end: date,
) -> int:
    if PARTITIONED_TABLES.get(table) != timestamp_column:
        raise ValueError("partition table/column is not allowlisted")
    partition = f"{table}_{start:%Y%m%d}"
    exists = await connection.scalar(
        text("select to_regclass(:partition_name) is not null"),
        {"partition_name": partition},
    )
    if exists:
        return 0

    default_partition = f"{table}_default"
    temporary = f"moving_{table}_{start:%Y%m%d}"
    await connection.execute(text(f"CREATE TEMP TABLE {temporary} AS TABLE {table} WITH NO DATA"))
    await connection.execute(
        text(
            f"WITH moved AS ("  # noqa: S608 - identifiers are allowlisted above
            f"DELETE FROM {default_partition} "
            f"WHERE {timestamp_column} >= :start AND {timestamp_column} < :end RETURNING *"
            f") INSERT INTO {temporary} SELECT * FROM moved"
        ),
        {"start": start, "end": end},
    )
    await connection.execute(
        text(
            f"CREATE TABLE {partition} PARTITION OF {table} "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )
    )
    await connection.execute(
        text(f"INSERT INTO {table} SELECT * FROM {temporary}")  # noqa: S608 - allowlisted identifiers
    )
    await connection.execute(text(f"DROP TABLE {temporary}"))
    return 1
