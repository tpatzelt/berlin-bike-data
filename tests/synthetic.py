"""Seeded synthetic GBFS dataset builder for G3 analysis tests.

Scripts an empty station, a cumulative flow between two Bezirke and a
constant background onto real DST-aligned snapshot timestamps, written
through ``berlinbikes.storage.Storage`` as ordinary Parquet.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import h3
import pyarrow as pa
import pyarrow.parquet as pq

from berlinbikes.cells import H3_RESOLUTION
from berlinbikes.schemas import SCHEMAS
from berlinbikes.storage import Storage

TIMEZONE = ZoneInfo("Europe/Berlin")
UTC = timezone.utc

BEZIRKE = ("BZ-A", "BZ-B", "BZ-C")
ORTSTEILE: dict[str, tuple[str, ...]] = {
    "BZ-A": ("OT-A1", "OT-A2"),
    "BZ-B": ("OT-B1", "OT-B2"),
    "BZ-C": ("OT-C1", "OT-C2"),
}

EMPTY_STATION_ID, EMPTY_BUDDY_ID = "S-EMPTY-0800", "S-BUDDY-0800"
EMPTY_STATION_BEZIRK = "BZ-C"
EMPTY_STATION_ORTSTEIL, EMPTY_BUDDY_ORTSTEIL = "OT-C1", "OT-C2"
EMPTY_STATION_BIKES = 5
EMPTY_BUDDY_BASELINE = 5
EMPTY_WINDOW_LOCAL = (time(7, 45), time(8, 30))  # half-open

FLOW_STATION_A, FLOW_STATION_B = "S-FLOW-A", "S-FLOW-B"
FLOW_STATION_A_BEZIRK, FLOW_STATION_B_BEZIRK = "BZ-A", "BZ-B"
FLOW_STATION_A_ORTSTEIL, FLOW_STATION_B_ORTSTEIL = "OT-A1", "OT-B1"
FLOW_PER_HOUR = 3
FLOW_BASELINE = 2 * FLOW_PER_HOUR + 1  # keeps FLOW_STATION_A >= 1 at all times
FLOW_MORNING_1, FLOW_MORNING_2 = time(7, 30), time(8, 30)
FLOW_EVENING_1, FLOW_EVENING_2 = time(17, 30), time(18, 30)

#: Net bikes per (bezirk, local hour) on a weekday, later-snapshot attribution.
#: Hours/bezirke not listed are 0.
EXPECTED_WEEKDAY_NET_BY_HOUR: dict[tuple[str, int], int] = {
    (FLOW_STATION_A_BEZIRK, 7): -FLOW_PER_HOUR,
    (FLOW_STATION_A_BEZIRK, 8): -FLOW_PER_HOUR,
    (FLOW_STATION_A_BEZIRK, 17): FLOW_PER_HOUR,
    (FLOW_STATION_A_BEZIRK, 18): FLOW_PER_HOUR,
    (FLOW_STATION_B_BEZIRK, 7): FLOW_PER_HOUR,
    (FLOW_STATION_B_BEZIRK, 8): FLOW_PER_HOUR,
    (FLOW_STATION_B_BEZIRK, 17): -FLOW_PER_HOUR,
    (FLOW_STATION_B_BEZIRK, 18): -FLOW_PER_HOUR,
}

VEHICLE_TYPE_EBIKE, VEHICLE_TYPE_PEDAL = "ebike", "pedal"

CAPACITY_SLACK = 5
DEFAULT_BACKGROUND_BIKES = 10
BACKGROUND_EBIKE_DIVISOR = 5
FREE_FLOAT_DIVISOR = 20
FREE_FLOAT_MAX_CELLS = 150

GAP_DAY_OFFSET = 2
GAP_LOCAL_START = time(2, 0)
GAP_DURATION = timedelta(minutes=90)

BERLIN_LAT_RANGE = (52.33, 52.68)
BERLIN_LON_RANGE = (13.08, 13.76)

_FIXED_PEDAL_TOTAL = EMPTY_STATION_BIKES + EMPTY_BUDDY_BASELINE + 2 * FLOW_BASELINE

AREAS_SCHEMA = pa.schema([pa.field(c, pa.string()) for c in ("source", "station_id", "bezirk", "ortsteil")])


def gap_date(start_date: date) -> date:
    """The local date the one scripted gap falls on, for a given build start."""
    return start_date + timedelta(days=GAP_DAY_OFFSET)


def _day_snapshots(d: date, snapshots_per_day: int) -> list[datetime]:
    start_utc = datetime.combine(d, time(0, 0), tzinfo=TIMEZONE).astimezone(UTC)
    end_utc = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=TIMEZONE).astimezone(UTC)
    step = timedelta(hours=24) / snapshots_per_day
    return [start_utc + i * step for i in range(round((end_utc - start_utc) / step))]


def _flow_offset_a(t: time, is_weekday: bool) -> int:
    if not is_weekday:
        return 0
    morning = (t >= FLOW_MORNING_1) + (t >= FLOW_MORNING_2)
    evening = (t >= FLOW_EVENING_1) + (t >= FLOW_EVENING_2)
    return FLOW_PER_HOUR * (evening - morning)


def _empty_in_window(t: time, is_weekday: bool) -> bool:
    start, end = EMPTY_WINDOW_LOCAL
    return is_weekday and start <= t < end


def _split_ebike_pedal(count: int) -> tuple[int, int]:
    ebike = count // BACKGROUND_EBIKE_DIVISOR
    return ebike, count - ebike


def _background_pairs(k: int) -> list[tuple[str, str]]:
    pairs = [(bez, ot) for bez in BEZIRKE for ot in ORTSTEILE[bez]]
    return [pairs[i % len(pairs)] for i in range(k)]


def _allocate(n_stations: int, n_bikes: int | None) -> dict[str, Any]:
    if n_bikes is None:
        n_free = 0
        background_total = DEFAULT_BACKGROUND_BIKES * (n_stations - 4)
    else:
        n_free = n_bikes // FREE_FLOAT_DIVISOR
        background_total = n_bikes - n_free - _FIXED_PEDAL_TOTAL
        if background_total < 0:
            raise ValueError(f"n_bikes={n_bikes} too small for n_stations={n_stations}")
    k = n_stations - 4
    base, rem = divmod(background_total, k)
    counts = [base + (1 if i < rem else 0) for i in range(k)]
    return {"n_free": n_free, "background_counts": counts}


def expected_totals(n_stations: int, n_bikes: int | None) -> dict[str, int]:
    """Expected (stations_ebike, stations_pedal, free_floating) for one build.

    Mirrors :func:`_allocate`, so ``sum(expected_totals(...).values()) ==
    n_bikes`` whenever ``n_bikes`` is given.
    """
    allocation = _allocate(n_stations, n_bikes)
    splits = [_split_ebike_pedal(c) for c in allocation["background_counts"]]
    return {
        "stations_ebike": sum(e for e, _ in splits),
        "stations_pedal": _FIXED_PEDAL_TOTAL + sum(p for _, p in splits),
        "free_floating": allocation["n_free"],
    }


def _station_plan(n_stations: int) -> list[tuple[str, str, str]]:
    """Return (station_id, bezirk, ortsteil) for every station, in write order."""
    assert n_stations >= 6, "n_stations >= 6 is required"
    plan = [
        (EMPTY_STATION_ID, EMPTY_STATION_BEZIRK, EMPTY_STATION_ORTSTEIL),
        (EMPTY_BUDDY_ID, EMPTY_STATION_BEZIRK, EMPTY_BUDDY_ORTSTEIL),
        (FLOW_STATION_A, FLOW_STATION_A_BEZIRK, FLOW_STATION_A_ORTSTEIL),
        (FLOW_STATION_B, FLOW_STATION_B_BEZIRK, FLOW_STATION_B_ORTSTEIL),
    ]
    plan += [(f"S-{i:04d}", bez, ot) for i, (bez, ot) in enumerate(_background_pairs(n_stations - 4))]
    return plan


def _free_float_cells(rng: random.Random, num_cells: int) -> list[str]:
    cells: list[str] = []
    seen: set[str] = set()
    attempts, max_attempts = 0, num_cells * 200 + 1000
    while len(cells) < num_cells and attempts < max_attempts:
        attempts += 1
        cell = h3.latlng_to_cell(rng.uniform(*BERLIN_LAT_RANGE), rng.uniform(*BERLIN_LON_RANGE), H3_RESOLUTION)
        if cell not in seen:
            seen.add(cell)
            cells.append(cell)
    if len(cells) < num_cells:
        raise RuntimeError("could not find enough distinct H3 cells")
    return cells


def build_dataset(
    data_dir: str | Path,
    *,
    seed: int = 0,
    start_date: date,
    days: int,
    n_stations: int = 30,
    n_bikes: int | None = None,
    snapshots_per_day: int = 96,
    source: str = "nextbike_bn",
    gap: bool = True,
) -> None:
    """Deterministically build a synthetic GBFS Parquet dataset under ``data_dir``."""
    rng = random.Random(seed)
    storage = Storage(data_dir)
    plan = _station_plan(n_stations)
    station_ids = [sid for sid, _, _ in plan]
    lat_lon = {sid: (rng.uniform(*BERLIN_LAT_RANGE), rng.uniform(*BERLIN_LON_RANGE)) for sid in station_ids}

    allocation = _allocate(n_stations, n_bikes)
    background_counts = dict(zip(station_ids[4:], allocation["background_counts"]))
    background_splits = {sid: _split_ebike_pedal(c) for sid, c in background_counts.items()}

    capacities = {
        EMPTY_STATION_ID: EMPTY_STATION_BIKES + CAPACITY_SLACK,
        EMPTY_BUDDY_ID: EMPTY_BUDDY_BASELINE + EMPTY_STATION_BIKES + CAPACITY_SLACK,
        FLOW_STATION_A: FLOW_BASELINE + CAPACITY_SLACK,
        FLOW_STATION_B: FLOW_BASELINE + 2 * FLOW_PER_HOUR + CAPACITY_SLACK,
        **{sid: c + CAPACITY_SLACK for sid, c in background_counts.items()},
    }

    n_free = allocation["n_free"]
    num_cells = min(n_free, FREE_FLOAT_MAX_CELLS) if n_free > 0 else 0
    cell_counts: list[tuple[str, int]] = []
    if num_cells > 0:
        base, rem = divmod(n_free, num_cells)
        free_cells = _free_float_cells(rng, num_cells)
        cell_counts = [(cell, base + (1 if i < rem else 0)) for i, cell in enumerate(free_cells)]

    has_gap = gap and days > GAP_DAY_OFFSET
    gap_day = gap_date(start_date)
    gap_start = gap_end = None
    gap_dropped = 0
    if has_gap:
        gap_start = datetime.combine(gap_day, GAP_LOCAL_START, tzinfo=TIMEZONE).astimezone(UTC)
        gap_end = gap_start + GAP_DURATION

    def _bike_counts(ts: datetime, is_weekday: bool) -> dict[str, tuple[int, int]]:
        local_t = ts.astimezone(TIMEZONE).time()
        empty_active = _empty_in_window(local_t, is_weekday)
        offset_a = _flow_offset_a(local_t, is_weekday)
        counts = dict(background_splits)
        counts[EMPTY_STATION_ID] = (0, 0 if empty_active else EMPTY_STATION_BIKES)
        counts[EMPTY_BUDDY_ID] = (0, EMPTY_BUDDY_BASELINE + (EMPTY_STATION_BIKES if empty_active else 0))
        counts[FLOW_STATION_A] = (0, FLOW_BASELINE + offset_a)
        counts[FLOW_STATION_B] = (0, FLOW_BASELINE - offset_a)
        return counts

    def _station_status_rows(ts: datetime, is_weekday: bool) -> list[dict]:
        counts = _bike_counts(ts, is_weekday)
        rows = []
        for sid in station_ids:
            ebike, pedal = counts[sid]
            bikes = ebike + pedal
            rows.append(
                {
                    "snapshot_ts": ts,
                    "fetched_at": ts,
                    "source": source,
                    "station_id": sid,
                    "num_bikes_available": bikes,
                    "num_docks_available": capacities[sid] - bikes,
                    "num_bikes_disabled": 0,
                    "is_installed": True,
                    "is_renting": True,
                    "is_returning": True,
                    "last_reported": ts,
                    "vehicle_types_available": [
                        {"vehicle_type_id": VEHICLE_TYPE_EBIKE, "count": ebike},
                        {"vehicle_type_id": VEHICLE_TYPE_PEDAL, "count": pedal},
                    ],
                }
            )
        return rows

    def _free_bike_cells_rows(ts: datetime) -> list[dict]:
        rows = []
        for cell, count in cell_counts:
            ebike, pedal = _split_ebike_pedal(count)
            for vehicle_type_id, num_bikes in ((VEHICLE_TYPE_EBIKE, ebike), (VEHICLE_TYPE_PEDAL, pedal)):
                rows.append(
                    {
                        "snapshot_ts": ts,
                        "fetched_at": ts,
                        "source": source,
                        "cell": cell,
                        "vehicle_type_id": vehicle_type_id,
                        "at_station": False,
                        "num_bikes": num_bikes,
                        "num_disabled": 0,
                        "num_reserved": 0,
                    }
                )
        return rows

    for day_offset in range(days):
        d = start_date + timedelta(days=day_offset)
        is_weekday = d.weekday() <= 4
        snapshots = _day_snapshots(d, snapshots_per_day)

        station_info_rows = [
            {"snapshot_ts": snapshots[0], "source": source, "station_id": sid, "name": f"Station {sid}",
             "lat": lat_lon[sid][0], "lon": lat_lon[sid][1], "capacity": capacities[sid]}
            for sid in station_ids
        ]
        storage.write("station_information", source,
                       pa.Table.from_pylist(station_info_rows, schema=SCHEMAS["station_information"]))

        vehicle_type_rows = [
            {"snapshot_ts": snapshots[0], "source": source, "vehicle_type_id": VEHICLE_TYPE_EBIKE,
             "form_factor": "bicycle", "propulsion_type": "electric_assist", "name": "E-Bike"},
            {"snapshot_ts": snapshots[0], "source": source, "vehicle_type_id": VEHICLE_TYPE_PEDAL,
             "form_factor": "bicycle", "propulsion_type": "human", "name": "Pedal bike"},
        ]
        storage.write("vehicle_types", source,
                       pa.Table.from_pylist(vehicle_type_rows, schema=SCHEMAS["vehicle_types"]))

        for ts in snapshots:
            if has_gap and d == gap_day and gap_start <= ts < gap_end:
                gap_dropped += 1
            else:
                rows = _station_status_rows(ts, is_weekday)
                storage.write("station_status", source, pa.Table.from_pylist(rows, schema=SCHEMAS["station_status"]))
            if n_bikes is not None and cell_counts:
                storage.write("free_bike_cells", source,
                               pa.Table.from_pylist(_free_bike_cells_rows(ts), schema=SCHEMAS["free_bike_cells"]))

    if has_gap:
        gap_row = {"source": source, "feed": "station_status", "gap_start": gap_start, "gap_end": gap_end,
                   "reason": "fetch_error", "attempts": gap_dropped}
        storage.write("gaps", source, pa.Table.from_pylist([gap_row], schema=SCHEMAS["gaps"]))

    areas_rows = [{"source": source, "station_id": sid, "bezirk": bez, "ortsteil": ot} for sid, bez, ot in plan]
    areas_dir = Path(data_dir) / "areas"
    areas_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(areas_rows, schema=AREAS_SCHEMA), areas_dir / "station_areas.parquet")
