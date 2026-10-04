"""Storage-budget test: one real-scale synthetic day stays under 50 MB of Parquet.

Scale matches the charter's storage constraint: about 1,050 stations and
5,500 bikes per snapshot, 720 snapshots a day.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import pyarrow.parquet as pq

from tests.synthetic import build_dataset

SOURCE = "nextbike_bn"
START_DATE = date(2026, 10, 12)  # a Monday, clear of any DST transition
N_STATIONS = 1050
N_BIKES = 5500
SNAPSHOTS_PER_DAY = 720
BUDGET_BYTES = 50_000_000
REQUIRED_DATASETS = {"station_status", "free_bike_cells", "station_information", "vehicle_types"}


def test_one_real_scale_day_fits_storage_budget(tmp_path):
    build_dataset(
        tmp_path,
        seed=0,
        start_date=START_DATE,
        days=1,
        n_stations=N_STATIONS,
        n_bikes=N_BIKES,
        snapshots_per_day=SNAPSHOTS_PER_DAY,
    )

    source_dir = tmp_path / SOURCE
    parquet_files = list(source_dir.rglob("*.parquet"))
    assert parquet_files, f"no parquet files found under {source_dir}"

    bytes_by_dataset: dict[str, int] = defaultdict(int)
    for path in parquet_files:
        dataset = path.relative_to(source_dir).parts[0]
        bytes_by_dataset[dataset] += path.stat().st_size

    missing = REQUIRED_DATASETS - bytes_by_dataset.keys()
    assert not missing, (
        f"expected datasets {sorted(missing)} to contribute bytes, got {sorted(bytes_by_dataset)}"
    )

    total_bytes = sum(bytes_by_dataset.values())
    breakdown = ", ".join(f"{name}={size:,}B" for name, size in sorted(bytes_by_dataset.items()))
    assert total_bytes < BUDGET_BYTES, (
        f"one real-scale day used {total_bytes:,} bytes of Parquet (budget {BUDGET_BYTES:,}): {breakdown}"
    )

    status_files = [p for p in parquet_files if p.relative_to(source_dir).parts[0] == "station_status"]
    row_count = sum(pq.ParquetFile(p).metadata.num_rows for p in status_files)
    expected_rows = N_STATIONS * SNAPSHOTS_PER_DAY
    assert row_count == expected_rows, (
        f"station_status has {row_count:,} rows, expected {expected_rows:,} for a real-scale day"
    )
