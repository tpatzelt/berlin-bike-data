"""In-memory aggregation of ``free_bike_status`` payloads to H3 grid cells.

The ADR for this batch picks H3 resolution 8 for G1's "counts per grid cell"
requirement. Aggregation happens entirely in :func:`aggregate_free_bikes`:
``bike_id`` is read only to drop duplicate bikes within one payload and never
appears in the returned table, in a raised exception, or in a log record —
the charter's non-goal forbids a rotating per-bike identifier from reaching
disk, logs or serving as a join key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import h3
import pyarrow as pa

from berlinbikes.schemas import FREE_BIKE_CELLS_SCHEMA

H3_RESOLUTION = 8


def aggregate_free_bikes(
    payload: dict[str, Any],
    snapshot_ts: datetime,
    fetched_at: datetime,
    source: str,
) -> pa.Table:
    """Aggregate one ``free_bike_status`` payload into per-cell counts.

    Groups bikes by ``(H3 res-8 cell, vehicle_type_id, at_station)``, where
    ``at_station`` is True when the bike carries a ``station_id``. Within
    one payload, a repeated ``bike_id`` is counted once. Returns a table
    matching ``schemas.FREE_BIKE_CELLS_SCHEMA``.
    """
    counts: dict[tuple[str, str, bool], list[int]] = {}
    seen_bike_ids: set[str] = set()

    for bike in payload["bikes"]:
        bike_id = bike.get("bike_id")
        if bike_id is not None:
            if bike_id in seen_bike_ids:
                continue
            seen_bike_ids.add(bike_id)

        cell = h3.latlng_to_cell(bike["lat"], bike["lon"], H3_RESOLUTION)
        key = (cell, bike["vehicle_type_id"], bool(bike.get("station_id")))

        bucket = counts.setdefault(key, [0, 0, 0])
        bucket[0] += 1
        bucket[1] += int(bool(bike.get("is_disabled")))
        bucket[2] += int(bool(bike.get("is_reserved")))

    rows = sorted(counts.items())
    timestamp_type = FREE_BIKE_CELLS_SCHEMA.field("snapshot_ts").type

    return pa.table(
        {
            "snapshot_ts": pa.array([snapshot_ts] * len(rows), type=timestamp_type),
            "fetched_at": pa.array([fetched_at] * len(rows), type=timestamp_type),
            "source": pa.array([source] * len(rows), type=pa.string()),
            "cell": pa.array([key[0] for key, _ in rows], type=pa.string()),
            "vehicle_type_id": pa.array([key[1] for key, _ in rows], type=pa.string()),
            "at_station": pa.array([key[2] for key, _ in rows], type=pa.bool_()),
            "num_bikes": pa.array([v[0] for _, v in rows], type=pa.int32()),
            "num_disabled": pa.array([v[1] for _, v in rows], type=pa.int32()),
            "num_reserved": pa.array([v[2] for _, v in rows], type=pa.int32()),
        },
        schema=FREE_BIKE_CELLS_SCHEMA,
    )
