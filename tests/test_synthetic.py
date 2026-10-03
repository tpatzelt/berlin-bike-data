"""Structural tests for the synthetic dataset builder.

Covers determinism, DST-aligned snapshot counts, the station_areas shape,
the one scripted gap row, and bike conservation. Literal known-answer
checks against the scripted values land in T-0042.
"""

from __future__ import annotations

from datetime import date, timedelta

import pyarrow.parquet as pq
import pytest

from tests.synthetic import (
    EMPTY_STATION_ID,
    GAP_DURATION,
    GAP_LOCAL_START,
    TIMEZONE,
    build_dataset,
    expected_totals,
    gap_date,
)

SOURCE = "nextbike_bn"


def _read_dataset(data_dir, dataset, source=SOURCE):
    rows = []
    for path in sorted((data_dir / source / dataset).glob("date=*/part-*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def _station_status_count(data_dir, d):
    # Storage partitions by UTC date, so one local day can straddle two
    # partitions; filter on the local timestamp after reading instead.
    rows = _read_dataset(data_dir, "station_status")
    return sum(1 for row in rows if row["snapshot_ts"].astimezone(TIMEZONE).date() == d)


def test_determinism(tmp_path):
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    build_dataset(dir_a, seed=7, start_date=date(2026, 10, 12), days=2, n_stations=6, n_bikes=120)
    build_dataset(dir_b, seed=7, start_date=date(2026, 10, 12), days=2, n_stations=6, n_bikes=120)

    assert _read_dataset(dir_a, "station_status") == _read_dataset(dir_b, "station_status")
    assert _read_dataset(dir_a, "free_bike_cells") == _read_dataset(dir_b, "free_bike_cells")
    areas_a = pq.read_table(dir_a / "areas" / "station_areas.parquet").to_pylist()
    areas_b = pq.read_table(dir_b / "areas" / "station_areas.parquet").to_pylist()
    assert areas_a == areas_b


@pytest.mark.parametrize(
    "d, expected", [(date(2026, 3, 29), 92), (date(2026, 10, 12), 96), (date(2026, 10, 25), 100)]
)
def test_snapshot_counts_across_dst(tmp_path, d, expected):
    build_dataset(tmp_path, start_date=d, days=1, n_stations=6, gap=False)
    assert _station_status_count(tmp_path, d) == expected * 6


def test_station_areas_shape(tmp_path):
    build_dataset(tmp_path, start_date=date(2026, 10, 12), days=2, n_stations=8, gap=False)
    table = pq.read_table(tmp_path / "areas" / "station_areas.parquet")
    rows = table.to_pylist()

    bezirke = {row["bezirk"] for row in rows}
    assert bezirke == {"BZ-A", "BZ-B", "BZ-C"}
    for bezirk in bezirke:
        assert len({row["ortsteil"] for row in rows if row["bezirk"] == bezirk}) >= 2
    for column in ("source", "station_id", "bezirk", "ortsteil"):
        assert table.schema.field(column).type == "string"
    assert {row["source"] for row in rows} == {SOURCE}


def test_gap_row_written_and_snapshots_dropped(tmp_path):
    start = date(2026, 10, 12)
    build_dataset(tmp_path, start_date=start, days=4, n_stations=6, snapshots_per_day=96, gap=True)

    gaps = _read_dataset(tmp_path, "gaps")
    assert len(gaps) == 1
    row = gaps[0]
    assert row["feed"] == "station_status"
    assert row["reason"] == "fetch_error"
    assert row["gap_end"] - row["gap_start"] == GAP_DURATION
    assert row["gap_start"].astimezone(TIMEZONE).time() == GAP_LOCAL_START

    step = timedelta(hours=24) / 96
    dropped = GAP_DURATION // step
    assert _station_status_count(tmp_path, gap_date(start)) == (96 - dropped) * 6


def test_no_gap_row_when_disabled(tmp_path):
    start = date(2026, 10, 12)
    build_dataset(tmp_path, start_date=start, days=4, n_stations=6, snapshots_per_day=96, gap=False)
    assert _read_dataset(tmp_path, "gaps") == []
    assert _station_status_count(tmp_path, gap_date(start)) == 96 * 6


def test_conservation_with_n_bikes(tmp_path):
    n_stations, n_bikes = 8, 200
    build_dataset(
        tmp_path, start_date=date(2026, 10, 12), days=1, n_stations=n_stations, n_bikes=n_bikes, gap=False
    )

    assert sum(expected_totals(n_stations, n_bikes).values()) == n_bikes

    status_by_ts: dict = {}
    for row in _read_dataset(tmp_path, "station_status"):
        status_by_ts[row["snapshot_ts"]] = status_by_ts.get(row["snapshot_ts"], 0) + row["num_bikes_available"]
    free_by_ts: dict = {}
    for row in _read_dataset(tmp_path, "free_bike_cells"):
        free_by_ts[row["snapshot_ts"]] = free_by_ts.get(row["snapshot_ts"], 0) + row["num_bikes"]

    assert status_by_ts.keys() == free_by_ts.keys()
    for ts, station_total in status_by_ts.items():
        assert station_total + free_by_ts[ts] == n_bikes

    empty_rows = [r for r in _read_dataset(tmp_path, "station_status") if r["station_id"] == EMPTY_STATION_ID]
    assert any(r["num_bikes_available"] == 0 for r in empty_rows)


def test_synthetic_data_dir_fixture(synthetic_data_dir):
    status_rows = _read_dataset(synthetic_data_dir, "station_status")
    station_ids = {row["station_id"] for row in status_rows}
    fallback_day = date(2026, 10, 25)
    on_fallback_day = [r for r in status_rows if r["snapshot_ts"].astimezone(TIMEZONE).date() == fallback_day]
    assert len(on_fallback_day) == 100 * len(station_ids)

    local_days = {row["snapshot_ts"].astimezone(TIMEZONE).date() for row in status_rows}
    assert len(local_days) == 28
