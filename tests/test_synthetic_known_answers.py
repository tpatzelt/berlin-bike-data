"""Known-answer tests for the synthetic dataset builder.

Every assertion here checks a literal expected value (a timestamp, an
offset, a count) scripted into ``tests/synthetic.py``'s module docstring and
``tests/.nightshift`` task notes, not a value recomputed via the builder's
own internal helpers. This is what pins the builder's scripted convention
for the metric tests in T-0013..T-0016.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import h3
import pyarrow.parquet as pq
import pytest

from berlinbikes.cells import H3_RESOLUTION
from tests.synthetic import (
    BEZIRKE,
    EMPTY_STATION_ID,
    EXPECTED_WEEKDAY_NET_BY_HOUR,
    FLOW_PER_HOUR,
    FLOW_STATION_A_BEZIRK,
    FLOW_STATION_B_BEZIRK,
    TIMEZONE,
    UTC,
    VEHICLE_TYPE_EBIKE,
    VEHICLE_TYPE_PEDAL,
    build_dataset,
    gap_date,
)

SOURCE = "nextbike_bn"
WEEK_START = date(2026, 10, 5)  # a Monday


def _read_dataset(data_dir, dataset, source=SOURCE):
    rows = []
    for path in sorted((data_dir / source / dataset).glob("date=*/part-*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def _read_areas(data_dir, source=SOURCE):
    table = pq.read_table(data_dir / "areas" / "station_areas.parquet")
    return {row["station_id"]: row["bezirk"] for row in table.to_pylist() if row["source"] == source}


def _bezirk_totals_by_ts(status_rows, areas):
    totals: dict[tuple[str, datetime], int] = {}
    for row in status_rows:
        key = (areas[row["station_id"]], row["snapshot_ts"])
        totals[key] = totals.get(key, 0) + row["num_bikes_available"]
    return totals


@pytest.fixture(scope="module")
def week_dataset(tmp_path_factory):
    """A Mon-Sun week, 6 stations, 96 snapshots/day, no gap."""
    data_dir = tmp_path_factory.mktemp("known_answers_week")
    build_dataset(data_dir, start_date=WEEK_START, days=7, n_stations=6, snapshots_per_day=96, gap=False)
    return data_dir


@pytest.fixture(scope="module")
def free_float_dataset(tmp_path_factory):
    """A 1-day, 96/day build with enough free-floating bikes to populate many cells."""
    data_dir = tmp_path_factory.mktemp("known_answers_free_float")
    build_dataset(data_dir, start_date=WEEK_START, days=1, n_bikes=5500, snapshots_per_day=96, gap=False)
    return data_dir


def test_empty_window_exact_snapshots(week_dataset):
    status_rows = _read_dataset(week_dataset, "station_status")
    empty_rows = [r for r in status_rows if r["station_id"] == EMPTY_STATION_ID]
    other_rows = [r for r in status_rows if r["station_id"] != EMPTY_STATION_ID]

    zero_local_times = {time(7, 45), time(8, 0), time(8, 15)}
    by_day: dict[date, list[int]] = {}
    for row in empty_rows:
        local = row["snapshot_ts"].astimezone(TIMEZONE)
        by_day.setdefault(local.date(), []).append(row["num_bikes_available"])
        is_weekday = local.date().weekday() <= 4
        if is_weekday and local.time() in zero_local_times:
            assert row["num_bikes_available"] == 0, (local.date(), local.time())
        else:
            assert row["num_bikes_available"] != 0, (local.date(), local.time())

    for d, counts in by_day.items():
        zero_count = sum(1 for c in counts if c == 0)
        assert zero_count == (3 if d.weekday() <= 4 else 0), d

    assert all(row["num_bikes_available"] != 0 for row in other_rows)


def test_per_bezirk_flow_weekday_checkpoints(week_dataset):
    status_rows = _read_dataset(week_dataset, "station_status")
    areas = _read_areas(week_dataset)
    totals = _bezirk_totals_by_ts(status_rows, areas)

    # (local time, BZ-A's offset from its own 06:45 total). BZ-B is the mirror.
    checkpoints = [
        (time(6, 45), 0),
        (time(7, 0), 0),
        (time(7, 30), -FLOW_PER_HOUR),
        (time(8, 0), -FLOW_PER_HOUR),
        (time(8, 30), -2 * FLOW_PER_HOUR),
        (time(9, 0), -2 * FLOW_PER_HOUR),
        (time(12, 0), -2 * FLOW_PER_HOUR),
        (time(17, 0), -2 * FLOW_PER_HOUR),
        (time(17, 30), -FLOW_PER_HOUR),
        (time(18, 0), -FLOW_PER_HOUR),
        (time(18, 30), 0),
        (time(19, 0), 0),
    ]

    for i in range(5):  # Mon-Fri
        d = WEEK_START + timedelta(days=i)
        for bezirk, sign in ((FLOW_STATION_A_BEZIRK, 1), (FLOW_STATION_B_BEZIRK, -1)):
            baseline = totals[(bezirk, datetime.combine(d, time(6, 45), tzinfo=TIMEZONE).astimezone(UTC))]
            for t, offset in checkpoints:
                ts = datetime.combine(d, t, tzinfo=TIMEZONE).astimezone(UTC)
                assert totals[(bezirk, ts)] - baseline == sign * offset, (d, bezirk, t)


def test_bezirk_c_and_citywide_constant_every_snapshot(week_dataset):
    status_rows = _read_dataset(week_dataset, "station_status")
    areas = _read_areas(week_dataset)
    totals = _bezirk_totals_by_ts(status_rows, areas)

    bz_c_values = {v for (bez, _ts), v in totals.items() if bez == "BZ-C"}
    assert len(bz_c_values) == 1

    citywide: dict[datetime, int] = {}
    for (_bez, ts), v in totals.items():
        citywide[ts] = citywide.get(ts, 0) + v
    assert len(set(citywide.values())) == 1


def test_bezirk_totals_constant_on_weekends(week_dataset):
    status_rows = _read_dataset(week_dataset, "station_status")
    areas = _read_areas(week_dataset)
    totals = _bezirk_totals_by_ts(status_rows, areas)

    weekend_days = {WEEK_START + timedelta(days=i) for i in range(5, 7)}
    for bezirk in BEZIRKE:
        values = {
            v
            for (bez, ts), v in totals.items()
            if bez == bezirk and ts.astimezone(TIMEZONE).date() in weekend_days
        }
        assert len(values) == 1, (bezirk, values)


def test_weekday_net_delta_by_hour(week_dataset):
    status_rows = _read_dataset(week_dataset, "station_status")
    areas = _read_areas(week_dataset)
    totals = _bezirk_totals_by_ts(status_rows, areas)

    d = WEEK_START
    for bezirk in (FLOW_STATION_A_BEZIRK, FLOW_STATION_B_BEZIRK):
        day_points = sorted(
            (ts, v) for (bez, ts), v in totals.items() if bez == bezirk and ts.astimezone(TIMEZONE).date() == d
        )
        net_by_hour: dict[int, int] = {}
        for (_ts_prev, v_prev), (ts_cur, v_cur) in zip(day_points, day_points[1:]):
            hour = ts_cur.astimezone(TIMEZONE).hour
            net_by_hour[hour] = net_by_hour.get(hour, 0) + (v_cur - v_prev)
        for hour in range(24):
            assert net_by_hour.get(hour, 0) == EXPECTED_WEEKDAY_NET_BY_HOUR.get((bezirk, hour), 0), (bezirk, hour)


def test_capacity_bounds(week_dataset):
    status_rows = _read_dataset(week_dataset, "station_status")
    info_rows = _read_dataset(week_dataset, "station_information")

    capacity_by_day_station = {
        (row["snapshot_ts"].astimezone(TIMEZONE).date(), row["station_id"]): row["capacity"]
        for row in info_rows
    }

    assert status_rows
    for row in status_rows:
        d = row["snapshot_ts"].astimezone(TIMEZONE).date()
        capacity = capacity_by_day_station[(d, row["station_id"])]
        bikes = row["num_bikes_available"]
        assert bikes <= capacity, row
        assert row["num_docks_available"] == capacity - bikes
        assert row["num_docks_available"] >= 0


def test_vehicle_types_consistent(week_dataset):
    status_rows = _read_dataset(week_dataset, "station_status")
    assert status_rows

    total_by_ts: dict[datetime, list[int]] = {}
    for row in status_rows:
        by_type = {v["vehicle_type_id"]: v["count"] for v in row["vehicle_types_available"]}
        ebike, pedal = by_type[VEHICLE_TYPE_EBIKE], by_type[VEHICLE_TYPE_PEDAL]
        assert ebike + pedal == row["num_bikes_available"], row

        bucket = total_by_ts.setdefault(row["snapshot_ts"], [0, 0])
        bucket[0] += ebike
        bucket[1] += pedal

    assert len({tuple(v) for v in total_by_ts.values()}) == 1


def test_free_bike_cells(free_float_dataset):
    rows = _read_dataset(free_float_dataset, "free_bike_cells")
    assert rows
    assert all(row["at_station"] is False for row in rows)

    cells = {row["cell"] for row in rows}
    assert len(cells) >= 100
    for cell in cells:
        assert h3.is_valid_cell(cell)
        assert h3.get_resolution(cell) == H3_RESOLUTION

    totals_by_ts: dict[datetime, int] = {}
    for row in rows:
        totals_by_ts[row["snapshot_ts"]] = totals_by_ts.get(row["snapshot_ts"], 0) + row["num_bikes"]
    assert len(set(totals_by_ts.values())) == 1


def test_gap_row_literal_window(tmp_path):
    start = date(2026, 10, 12)
    build_dataset(tmp_path, start_date=start, days=4, n_stations=6, snapshots_per_day=96, gap=True)

    gaps = _read_dataset(tmp_path, "gaps")
    assert len(gaps) == 1
    row = gaps[0]
    local_start = row["gap_start"].astimezone(TIMEZONE)
    assert local_start.date() == gap_date(start)
    assert local_start.time() == time(2, 0)
    assert row["gap_end"] - row["gap_start"] == timedelta(minutes=90)

    status_rows = _read_dataset(tmp_path, "station_status")
    gap_start, gap_end = row["gap_start"], row["gap_end"]
    assert all(not (gap_start <= r["snapshot_ts"] < gap_end) for r in status_rows)
