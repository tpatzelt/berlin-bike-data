"""Tests for the crash-safe, append-only Parquet storage layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from berlinbikes.schemas import SCHEMAS
from berlinbikes.storage import (
    DuplicateSnapshotError,
    SnapshotFileCollisionError,
    Storage,
)

SOURCE = "nextbike_bn"


def _ts(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def _station_status_table(snapshot_ts, source=SOURCE, station_ids=("S1", "S2")):
    fetched_at = snapshot_ts + timedelta(seconds=1)
    rows = [
        {
            "snapshot_ts": snapshot_ts,
            "fetched_at": fetched_at,
            "source": source,
            "station_id": station_id,
            "num_bikes_available": 3,
            "num_docks_available": 5,
            "num_bikes_disabled": None,
            "is_installed": True,
            "is_renting": True,
            "is_returning": True,
            "last_reported": snapshot_ts,
            "vehicle_types_available": [{"vehicle_type_id": "bike", "count": 3}],
        }
        for station_id in station_ids
    ]
    return pa.Table.from_pylist(rows, schema=SCHEMAS["station_status"])


def _station_information_table(snapshot_ts, source=SOURCE, station_ids=("S1", "S2")):
    rows = [
        {
            "snapshot_ts": snapshot_ts,
            "source": source,
            "station_id": station_id,
            "name": f"Station {station_id}",
            "lat": 52.5,
            "lon": 13.4,
            "capacity": 10,
        }
        for station_id in station_ids
    ]
    return pa.Table.from_pylist(rows, schema=SCHEMAS["station_information"])


def _vehicle_types_table(snapshot_ts, source=SOURCE):
    rows = [
        {
            "snapshot_ts": snapshot_ts,
            "source": source,
            "vehicle_type_id": "bike",
            "form_factor": "bicycle",
            "propulsion_type": "human",
            "name": "Classic bike",
        }
    ]
    return pa.Table.from_pylist(rows, schema=SCHEMAS["vehicle_types"])


def _free_bike_cells_table(snapshot_ts, source=SOURCE, cells=("8", "9")):
    fetched_at = snapshot_ts + timedelta(seconds=1)
    rows = [
        {
            "snapshot_ts": snapshot_ts,
            "fetched_at": fetched_at,
            "source": source,
            "cell": cell,
            "vehicle_type_id": "bike",
            "at_station": False,
            "num_bikes": 2,
            "num_disabled": 0,
            "num_reserved": 0,
        }
        for cell in cells
    ]
    return pa.Table.from_pylist(rows, schema=SCHEMAS["free_bike_cells"])


def _gaps_table(gap_start, feed="station_status", source=SOURCE, reason="fetch_error"):
    rows = [
        {
            "source": source,
            "feed": feed,
            "gap_start": gap_start,
            "gap_end": gap_start + timedelta(minutes=10),
            "reason": reason,
            "attempts": 3,
        }
    ]
    return pa.Table.from_pylist(rows, schema=SCHEMAS["gaps"])


SNAPSHOT_BUILDERS = {
    "station_status": _station_status_table,
    "station_information": _station_information_table,
    "vehicle_types": _vehicle_types_table,
    "free_bike_cells": _free_bike_cells_table,
}


@pytest.mark.parametrize("dataset", sorted(SNAPSHOT_BUILDERS))
def test_round_trip_for_every_snapshot_dataset(tmp_path, dataset):
    store = Storage(tmp_path)
    snapshot_ts = _ts(2024, 5, 1, 12, 0, 0)
    table = SNAPSHOT_BUILDERS[dataset](snapshot_ts)

    path = store.write(dataset, SOURCE, table)

    assert path.is_file()
    assert path.name == f"part-{snapshot_ts.strftime('%H%M%S%f')}.parquet"
    read_back = pq.read_table(path)
    assert read_back.schema.equals(SCHEMAS[dataset])
    assert read_back.num_rows == table.num_rows
    assert store.existing_snapshots(SOURCE, dataset, snapshot_ts.date()) == {snapshot_ts}
    assert store.latest_snapshot(SOURCE, dataset) == snapshot_ts


def test_round_trip_for_gaps(tmp_path):
    store = Storage(tmp_path)
    gap_start = _ts(2024, 5, 1, 12, 0, 0)
    table = _gaps_table(gap_start)

    path = store.write("gaps", SOURCE, table)

    assert path.is_file()
    assert path.name == f"part-station_status-{gap_start.strftime('%H%M%S%f')}.parquet"
    read_back = pq.read_table(path)
    assert read_back.schema.equals(SCHEMAS["gaps"])
    assert store.existing_snapshots(SOURCE, "gaps", gap_start.date()) == {
        ("station_status", gap_start)
    }
    assert store.latest_snapshot(SOURCE, "gaps") == gap_start


def test_duplicate_snapshot_is_rejected(tmp_path):
    store = Storage(tmp_path)
    snapshot_ts = _ts(2024, 5, 1, 12, 0, 0)
    store.write("station_status", SOURCE, _station_status_table(snapshot_ts))

    with pytest.raises(DuplicateSnapshotError):
        store.write("station_status", SOURCE, _station_status_table(snapshot_ts))


def test_snapshots_differing_only_by_microsecond_both_write_and_first_stays_intact(tmp_path):
    store = Storage(tmp_path)
    first_ts = _ts(2024, 5, 1, 12, 0, 0, microsecond=100000)
    second_ts = _ts(2024, 5, 1, 12, 0, 0, microsecond=200000)

    first_path = store.write("station_status", SOURCE, _station_status_table(first_ts))
    first_bytes = first_path.read_bytes()

    second_path = store.write("station_status", SOURCE, _station_status_table(second_ts))

    assert first_path != second_path
    assert first_path.read_bytes() == first_bytes
    assert store.existing_snapshots(SOURCE, "station_status", first_ts.date()) == {
        first_ts,
        second_ts,
    }


def test_gaps_for_different_feeds_at_same_instant_both_write(tmp_path):
    store = Storage(tmp_path)
    gap_start = _ts(2024, 5, 1, 12, 0, 0)

    status_path = store.write(
        "gaps", SOURCE, _gaps_table(gap_start, feed="station_status")
    )
    bikes_path = store.write(
        "gaps", SOURCE, _gaps_table(gap_start, feed="free_bike_status")
    )

    assert status_path != bikes_path
    assert store.existing_snapshots(SOURCE, "gaps", gap_start.date()) == {
        ("station_status", gap_start),
        ("free_bike_status", gap_start),
    }


def test_atomic_write_leaves_no_part_file_on_exception(tmp_path, monkeypatch):
    store = Storage(tmp_path)
    snapshot_ts = _ts(2024, 5, 1, 12, 0, 0)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr("berlinbikes.storage.pq.write_table", _boom)

    with pytest.raises(RuntimeError):
        store.write("station_status", SOURCE, _station_status_table(snapshot_ts))

    partition_dir = tmp_path / SOURCE / "station_status" / f"date={snapshot_ts.date()}"
    assert list(partition_dir.glob("part-*.parquet")) == []
    assert list(partition_dir.glob(".tmp-*")) == []


def test_hard_crash_leftovers_do_not_block_reads_or_the_next_write(tmp_path):
    store = Storage(tmp_path)
    snapshot_ts = _ts(2024, 5, 1, 12, 0, 0)
    partition_dir = tmp_path / SOURCE / "station_status" / f"date={snapshot_ts.date()}"
    partition_dir.mkdir(parents=True)

    (partition_dir / ".tmp-empty.partial").write_bytes(b"")
    (partition_dir / ".tmp-truncated.partial").write_bytes(b"PAR1garbage-not-a-full-file")
    (partition_dir / ".tmp-stale.parquet").write_bytes(b"")

    assert store.existing_snapshots(SOURCE, "station_status", snapshot_ts.date()) == set()
    assert store.latest_snapshot(SOURCE, "station_status") is None

    path = store.write("station_status", SOURCE, _station_status_table(snapshot_ts))

    assert path.is_file()
    assert store.latest_snapshot(SOURCE, "station_status") == snapshot_ts
    assert list(partition_dir.glob(".tmp-*")) == []


def test_source_mismatch_is_rejected(tmp_path):
    store = Storage(tmp_path)
    snapshot_ts = _ts(2024, 5, 1, 12, 0, 0)
    table = _station_status_table(snapshot_ts, source="dott_berlin")

    with pytest.raises(ValueError):
        store.write("station_status", SOURCE, table)


def test_invalid_gap_reason_is_rejected(tmp_path):
    store = Storage(tmp_path)
    gap_start = _ts(2024, 5, 1, 12, 0, 0)
    table = _gaps_table(gap_start, reason="not_a_real_reason")

    with pytest.raises(ValueError):
        store.write("gaps", SOURCE, table)


def test_latest_gap_end_is_none_with_no_gaps(tmp_path):
    store = Storage(tmp_path)
    assert store.latest_gap_end(SOURCE, "station_status") is None


def test_latest_gap_end_is_max_gap_end_for_that_feed_only(tmp_path):
    store = Storage(tmp_path)
    gap_start = _ts(2024, 5, 1, 12, 0, 0)

    store.write("gaps", SOURCE, _gaps_table(gap_start, feed="station_status"))
    later_start = gap_start + timedelta(hours=1)
    store.write("gaps", SOURCE, _gaps_table(later_start, feed="station_status"))
    # A different feed's later gap_end must not affect station_status's.
    store.write(
        "gaps",
        SOURCE,
        _gaps_table(gap_start + timedelta(hours=5), feed="free_bike_status"),
    )

    assert store.latest_gap_end(SOURCE, "station_status") == later_start + timedelta(minutes=10)


def test_latest_gap_end_reads_across_the_two_newest_partitions(tmp_path):
    store = Storage(tmp_path)
    # gap_end lands on the day after gap_start's partition date.
    gap_start = _ts(2024, 5, 1, 23, 55, 0)
    table = _gaps_table(gap_start, feed="station_status")
    assert table.column("gap_end")[0].as_py().date().isoformat() == "2024-05-02"

    store.write("gaps", SOURCE, table)

    assert store.latest_gap_end(SOURCE, "station_status") == gap_start + timedelta(minutes=10)


def test_duplicate_check_does_not_read_existing_part_files(tmp_path, monkeypatch):
    store = Storage(tmp_path)
    base_ts = _ts(2024, 5, 1, 12, 0, 0)
    for i in range(20):
        store.write(
            "station_status", SOURCE, _station_status_table(base_ts + timedelta(seconds=i))
        )

    def _boom(*_args, **_kwargs):
        raise AssertionError("read_table must not be called for the duplicate check")

    monkeypatch.setattr("berlinbikes.storage.pq.read_table", _boom)

    new_ts = base_ts + timedelta(seconds=20)
    path = store.write("station_status", SOURCE, _station_status_table(new_ts))
    assert path.is_file()

    with pytest.raises(DuplicateSnapshotError):
        store.write("station_status", SOURCE, _station_status_table(base_ts))


def test_gaps_duplicate_check_does_not_read_existing_part_files(tmp_path, monkeypatch):
    store = Storage(tmp_path)
    base_start = _ts(2024, 5, 1, 12, 0, 0)
    for i in range(20):
        store.write(
            "gaps", SOURCE, _gaps_table(base_start + timedelta(minutes=i))
        )

    def _boom(*_args, **_kwargs):
        raise AssertionError("read_table must not be called for the duplicate check")

    monkeypatch.setattr("berlinbikes.storage.pq.read_table", _boom)

    new_start = base_start + timedelta(minutes=20)
    path = store.write("gaps", SOURCE, _gaps_table(new_start))
    assert path.is_file()

    with pytest.raises(DuplicateSnapshotError):
        store.write("gaps", SOURCE, _gaps_table(base_start))


def test_utc_partitioning_near_midnight_uses_real_berlin_offset_not_a_fixed_one(tmp_path):
    store = Storage(tmp_path)
    berlin = ZoneInfo("Europe/Berlin")
    # 2024-06-15 is CEST (UTC+2): 00:30 local is 2024-06-14 22:30 UTC, the
    # *previous* UTC day. A fixed +1 offset would wrongly keep it on the 15th.
    local_midnight = datetime(2024, 6, 15, 0, 30, tzinfo=berlin)
    snapshot_ts = local_midnight.astimezone(timezone.utc)
    assert snapshot_ts.date().isoformat() == "2024-06-14"

    path = store.write("station_status", SOURCE, _station_status_table(snapshot_ts))

    assert path.parent.name == "date=2024-06-14"
