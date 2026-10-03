"""Bright Sky hourly weather parser.

Bright Sky's ``/weather`` endpoint returns a ``weather`` list of hourly
records for a Berlin lat/lon. ``parse_weather`` reads only the fields this
project needs (timestamp, precipitation, temperature, condition) and
converts each record's timestamp to a UTC, on-the-hour ``hour_ts``. Every
other key in a record (``source_id``, ``wind_speed``, ...) is ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pyarrow as pa

BERLIN_LAT = 52.52
BERLIN_LON = 13.405

TIMESTAMP_UTC = pa.timestamp("us", tz="UTC")

WEATHER_SCHEMA = pa.schema(
    [
        pa.field("hour_ts", TIMESTAMP_UTC, nullable=False),
        pa.field("precipitation_mm", pa.float64(), nullable=True),
        pa.field("temperature_c", pa.float64(), nullable=True),
        pa.field("condition", pa.string(), nullable=True),
    ]
)


class WeatherParseError(ValueError):
    """Raised when a Bright Sky payload does not match the expected shape."""


def _parse_hour_ts(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise WeatherParseError(f"invalid timestamp: {raw!r}") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WeatherParseError(f"timestamp has no UTC offset: {raw!r}")

    hour_ts = parsed.astimezone(timezone.utc)
    if hour_ts.minute or hour_ts.second or hour_ts.microsecond:
        raise WeatherParseError(f"timestamp is not on the full hour: {raw!r}")
    return hour_ts


def parse_weather(payload: dict) -> pa.Table:
    """Parse a Bright Sky ``/weather`` payload into ``WEATHER_SCHEMA``."""
    records = payload.get("weather")
    if not isinstance(records, list):
        raise WeatherParseError("payload is missing a 'weather' list")

    rows = []
    seen_hours = set()
    for record in records:
        if "timestamp" not in record:
            raise WeatherParseError("weather record is missing 'timestamp'")

        hour_ts = _parse_hour_ts(record["timestamp"])
        if hour_ts in seen_hours:
            raise WeatherParseError(f"duplicate hour_ts after UTC conversion: {hour_ts!r}")
        seen_hours.add(hour_ts)

        rows.append(
            {
                "hour_ts": hour_ts,
                "precipitation_mm": record.get("precipitation"),
                "temperature_c": record.get("temperature"),
                "condition": record.get("condition"),
            }
        )

    rows.sort(key=lambda row: row["hour_ts"])
    return pa.Table.from_pylist(rows, schema=WEATHER_SCHEMA)
