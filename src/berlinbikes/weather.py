"""Bright Sky hourly weather parser.

Bright Sky's ``/weather`` endpoint returns a ``weather`` list of hourly
records for a Berlin lat/lon. ``parse_weather`` reads only the fields this
project needs (timestamp, precipitation, temperature, condition) and
converts each record's timestamp to a UTC, on-the-hour ``hour_ts``. Every
other key in a record (``source_id``, ``wind_speed``, ...) is ignored.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from berlinbikes.backoff import Backoff, Clock, SystemClock, parse_retry_after

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


BRIGHT_SKY_BASE_URL = "https://api.brightsky.dev"


class WeatherFetchError(Exception):
    """Raised by ``WeatherClient.fetch_day`` on an HTTP error, timeout or parse error.

    Never carries the response body, so it is always safe to log or print.
    """

    def __init__(self, status: int | None, retry_after: float | None, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.retry_after = retry_after
        self.reason = reason


class WeatherClient:
    """A single-shot Bright Sky ``/weather`` client for one UTC day at a time.

    Does not retry; a failure raises ``WeatherFetchError`` for the caller
    (``WeatherCache``) to back off on.
    """

    def __init__(
        self,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        clock: Clock | None = None,
        backoff_factory=Backoff,
        base_url: str = BRIGHT_SKY_BASE_URL,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            headers={"User-Agent": user_agent},
        )
        self._clock = clock if clock is not None else SystemClock()
        self.backoff_factory = backoff_factory

    def fetch_day(self, day: date) -> pa.Table:
        params = {
            "lat": BERLIN_LAT,
            "lon": BERLIN_LON,
            "date": day.isoformat(),
            "last_date": (day + timedelta(days=1)).isoformat(),
            "tz": "UTC",
        }
        try:
            response = self._http.get("/weather", params=params)
        except httpx.TimeoutException as exc:
            raise WeatherFetchError(None, None, "request timed out") from exc
        except httpx.HTTPError as exc:
            raise WeatherFetchError(None, None, "request failed") from exc

        if response.status_code != 200:
            retry_after = None
            header = response.headers.get("Retry-After")
            if header is not None:
                retry_after = parse_retry_after(header, self._clock.now())
            raise WeatherFetchError(
                response.status_code, retry_after, "unexpected status code"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherFetchError(response.status_code, None, "invalid JSON body") from exc

        try:
            table = parse_weather(payload)
        except WeatherParseError as exc:
            raise WeatherFetchError(
                response.status_code, None, "invalid weather payload"
            ) from exc

        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        hour_ts = table.column("hour_ts").to_pylist()
        mask = pa.array([start <= ts < end for ts in hour_ts], type=pa.bool_())
        return table.filter(mask)


class WeatherCache:
    """Write-once daily weather cache under ``{data_dir}/weather/date=YYYY-MM-DD/``."""

    def __init__(self, data_dir: str | Path, client: WeatherClient, clock: Clock) -> None:
        self._data_dir = Path(data_dir)
        self._client = client
        self._clock = clock
        self._backoff = client.backoff_factory()

    def _cache_path(self, day: date) -> Path:
        return self._data_dir / "weather" / f"date={day.isoformat()}" / "weather.parquet"

    def _write_cache_file(self, path: Path, table: pa.Table) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.parent / f".tmp-{uuid.uuid4().hex}.parquet"
        pq.write_table(table, tmp_path)
        try:
            os.link(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def collect_missing(self, days_back: int = 7) -> float | None:
        today = self._clock.now().date()
        day = today - timedelta(days=days_back)
        last_day = today - timedelta(days=2)

        while day <= last_day:
            path = self._cache_path(day)
            if not path.exists():
                try:
                    table = self._client.fetch_day(day)
                except WeatherFetchError as exc:
                    return self._backoff.next_delay(exc.retry_after)
                self._write_cache_file(path, table)
                self._backoff.reset()
            day += timedelta(days=1)

        return None
