"""Pyarrow schemas for the Berlin bike-share snapshot datasets.

All timestamp columns are ``timestamp[us, tz=UTC]``. Two kinds of dataset:

- Snapshot datasets (``station_status``, ``station_information``,
  ``vehicle_types``, ``free_bike_cells``) hold one row per entity observed at
  a single ``snapshot_ts``; that column is the dedupe key.
- ``gaps`` holds one row per recorded feed outage; the dedupe key is
  ``(feed, gap_start)``.

``free_bike_cells`` is the on-the-fly aggregation of ``free_bike_status`` to
grid cells. It has no ``bike_id`` and no per-bike coordinate, so a rotating
bike id never reaches disk.
"""

from __future__ import annotations

import pyarrow as pa

TIMESTAMP_UTC = pa.timestamp("us", tz="UTC")

VEHICLE_TYPES_AVAILABLE = pa.list_(
    pa.struct(
        [
            pa.field("vehicle_type_id", pa.string()),
            pa.field("count", pa.int32()),
        ]
    )
)

STATION_STATUS_SCHEMA = pa.schema(
    [
        pa.field("snapshot_ts", TIMESTAMP_UTC),
        pa.field("fetched_at", TIMESTAMP_UTC),
        pa.field("source", pa.string()),
        pa.field("station_id", pa.string()),
        pa.field("num_bikes_available", pa.int32()),
        pa.field("num_docks_available", pa.int32(), nullable=True),
        pa.field("num_bikes_disabled", pa.int32(), nullable=True),
        pa.field("is_installed", pa.bool_()),
        pa.field("is_renting", pa.bool_()),
        pa.field("is_returning", pa.bool_()),
        pa.field("last_reported", TIMESTAMP_UTC),
        pa.field("vehicle_types_available", VEHICLE_TYPES_AVAILABLE, nullable=True),
    ]
)

STATION_INFORMATION_SCHEMA = pa.schema(
    [
        pa.field("snapshot_ts", TIMESTAMP_UTC),
        pa.field("source", pa.string()),
        pa.field("station_id", pa.string()),
        pa.field("name", pa.string()),
        pa.field("lat", pa.float64()),
        pa.field("lon", pa.float64()),
        pa.field("capacity", pa.int32(), nullable=True),
    ]
)

VEHICLE_TYPES_SCHEMA = pa.schema(
    [
        pa.field("snapshot_ts", TIMESTAMP_UTC),
        pa.field("source", pa.string()),
        pa.field("vehicle_type_id", pa.string()),
        pa.field("form_factor", pa.string()),
        pa.field("propulsion_type", pa.string()),
        pa.field("name", pa.string(), nullable=True),
    ]
)

FREE_BIKE_CELLS_SCHEMA = pa.schema(
    [
        pa.field("snapshot_ts", TIMESTAMP_UTC),
        pa.field("fetched_at", TIMESTAMP_UTC),
        pa.field("source", pa.string()),
        pa.field("cell", pa.string()),
        pa.field("vehicle_type_id", pa.string()),
        pa.field("at_station", pa.bool_()),
        pa.field("num_bikes", pa.int32()),
        pa.field("num_disabled", pa.int32()),
        pa.field("num_reserved", pa.int32()),
    ]
)

GAPS_SCHEMA = pa.schema(
    [
        pa.field("source", pa.string()),
        pa.field("feed", pa.string()),
        pa.field("gap_start", TIMESTAMP_UTC),
        pa.field("gap_end", TIMESTAMP_UTC),
        pa.field("reason", pa.string()),
        pa.field("attempts", pa.int32()),
    ]
)

SCHEMAS: dict[str, pa.Schema] = {
    "station_status": STATION_STATUS_SCHEMA,
    "station_information": STATION_INFORMATION_SCHEMA,
    "vehicle_types": VEHICLE_TYPES_SCHEMA,
    "free_bike_cells": FREE_BIKE_CELLS_SCHEMA,
    "gaps": GAPS_SCHEMA,
}

SNAPSHOT_DATASETS = frozenset(
    {"station_status", "station_information", "vehicle_types", "free_bike_cells"}
)

GAP_REASONS = frozenset({"fetch_error", "collector_down", "stale_feed"})
