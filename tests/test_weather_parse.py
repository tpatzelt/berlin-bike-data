"""Tests for berlinbikes.weather: Bright Sky /weather payload -> WEATHER_SCHEMA.

Payloads are built in-test by ``make_payload`` following Bright Sky's
documented ``/weather`` response shape (a top-level ``weather`` list of
hourly records plus a ``sources`` list). No network access and no fixture
files are used; the suite stays fully offline.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pyarrow as pa
import pytest

from berlinbikes.weather import WEATHER_SCHEMA, WeatherParseError, parse_weather

BERLIN_TZ = ZoneInfo("Europe/Berlin")


def make_payload(start_utc: datetime, hours: int, offset: timedelta = timedelta(0)) -> dict:
    """Build a Bright Sky-shaped payload for ``hours`` consecutive UTC hours.

    Each record's ``timestamp`` is rendered at ``offset`` from UTC but
    represents the same instant as ``start_utc + i hours``, so varying
    ``offset`` must not change the parsed UTC hour_ts values.
    """
    tz = timezone(offset)
    records = []
    for i in range(hours):
        hour_utc = start_utc + timedelta(hours=i)
        local_wall_clock = (hour_utc + offset).replace(tzinfo=tz)
        records.append(
            {
                "timestamp": local_wall_clock.isoformat(),
                "source_id": 1,
                "precipitation": 0.0,
                "pressure_msl": 1013.0,
                "sunshine": 0.0,
                "temperature": float(i),
                "wind_direction": 180,
                "wind_speed": 10.0,
                "condition": "dry" if i % 2 == 0 else "rain",
                "icon": "clear-day",
            }
        )
    return {"weather": records, "sources": [{"id": 1, "dwd_station_id": "00430"}]}


def test_72_hours_from_spring_forward_start_are_strictly_consecutive_utc_hours():
    payload = make_payload(datetime(2026, 3, 28, 0, 0, tzinfo=timezone.utc), 72)
    table = parse_weather(payload)
    assert table.num_rows == 72

    hour_ts = table.column("hour_ts").to_pylist()
    for earlier, later in zip(hour_ts, hour_ts[1:]):
        assert later - earlier == timedelta(hours=1)


def test_spring_forward_local_date_has_23_rows():
    payload = make_payload(datetime(2026, 3, 28, 0, 0, tzinfo=timezone.utc), 72)
    table = parse_weather(payload)

    hour_ts = table.column("hour_ts").to_pylist()
    local_dates = [ts.astimezone(BERLIN_TZ) for ts in hour_ts]
    short_day_rows = [ts for ts in local_dates if ts.date() == date(2026, 3, 29)]
    assert len(short_day_rows) == 23


def test_fall_back_local_date_has_25_rows_with_distinct_temperatures_at_local_0200():
    payload = make_payload(datetime(2025, 10, 25, 0, 0, tzinfo=timezone.utc), 72)
    table = parse_weather(payload)

    hour_ts = table.column("hour_ts").to_pylist()
    temperature = table.column("temperature_c").to_pylist()
    local_rows = [
        (ts.astimezone(BERLIN_TZ), temp) for ts, temp in zip(hour_ts, temperature)
    ]
    long_day_rows = [row for row in local_rows if row[0].date() == date(2025, 10, 26)]
    assert len(long_day_rows) == 25

    two_am_temperatures = [temp for local_ts, temp in long_day_rows if local_ts.hour == 2]
    assert len(two_am_temperatures) == 2
    assert two_am_temperatures[0] != two_am_temperatures[1]


def test_offset_rendering_parses_to_same_utc_hours_as_zero_offset():
    start_utc = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    utc_table = parse_weather(make_payload(start_utc, 10))
    offset_table = parse_weather(make_payload(start_utc, 10, offset=timedelta(hours=2)))

    assert utc_table.column("hour_ts").to_pylist() == offset_table.column("hour_ts").to_pylist()


def test_records_out_of_order_come_back_sorted():
    payload = make_payload(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 5)
    payload["weather"] = list(reversed(payload["weather"]))

    table = parse_weather(payload)
    hour_ts = table.column("hour_ts").to_pylist()
    assert hour_ts == sorted(hour_ts)
    assert table.column("temperature_c").to_pylist() == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_null_precipitation_temperature_condition_stay_null():
    payload = make_payload(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1)
    payload["weather"][0]["precipitation"] = None
    payload["weather"][0]["temperature"] = None
    payload["weather"][0]["condition"] = None

    table = parse_weather(payload)
    assert table.column("precipitation_mm").to_pylist() == [None]
    assert table.column("temperature_c").to_pylist() == [None]
    assert table.column("condition").to_pylist() == [None]


def test_schema_equals_weather_schema():
    payload = make_payload(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 3)
    table = parse_weather(payload)
    assert table.schema.equals(WEATHER_SCHEMA)


def _payload_missing_weather_key():
    return {"sources": []}


def _payload_weather_not_a_list():
    return {"weather": "not-a-list", "sources": []}


def _payload_record_without_timestamp():
    payload = make_payload(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1)
    del payload["weather"][0]["timestamp"]
    return payload


def _payload_naive_timestamp():
    payload = make_payload(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1)
    payload["weather"][0]["timestamp"] = "2026-01-01T00:00:00"
    return payload


def _payload_timestamp_not_on_full_hour():
    payload = make_payload(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1)
    payload["weather"][0]["timestamp"] = "2026-01-01T00:15:00+00:00"
    return payload


def _payload_duplicate_hour_ts_after_utc_conversion():
    payload = make_payload(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1)
    duplicate = dict(payload["weather"][0])
    duplicate["timestamp"] = "2026-01-01T02:00:00+02:00"  # same instant as 00:00Z
    payload["weather"].append(duplicate)
    return payload


@pytest.mark.parametrize(
    "build_payload",
    [
        _payload_missing_weather_key,
        _payload_weather_not_a_list,
        _payload_record_without_timestamp,
        _payload_naive_timestamp,
        _payload_timestamp_not_on_full_hour,
        _payload_duplicate_hour_ts_after_utc_conversion,
    ],
    ids=[
        "missing_weather_key",
        "weather_not_a_list",
        "record_without_timestamp",
        "naive_timestamp",
        "timestamp_not_on_full_hour",
        "duplicate_hour_ts_after_utc_conversion",
    ],
)
def test_invalid_payloads_raise_weather_parse_error(build_payload):
    with pytest.raises(WeatherParseError):
        parse_weather(build_payload())
