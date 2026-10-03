"""DuckDB connections over the Parquet snapshot datasets.

:func:`connect` wires up one DuckDB connection with one view per dataset
written by :class:`berlinbikes.storage.Storage`
(``{data_dir}/{source}/{dataset}/date=*/*.parquet``, hive-partitioned on the
UTC calendar date) plus ``station_areas``
(``{data_dir}/areas/station_areas.parquet``). A dataset that has not been
written yet (no matching files) gets an empty view with the right columns
instead of a DuckDB error, so downstream queries never need to special-case
"no data yet".
"""

from __future__ import annotations

import glob
from pathlib import Path

import duckdb
import pyarrow as pa

from berlinbikes.schemas import SCHEMAS

_DATASETS = ("station_status", "station_information", "vehicle_types", "free_bike_cells", "gaps")

_AREAS_SCHEMA = pa.schema([pa.field(c, pa.string()) for c in ("source", "station_id", "bezirk", "ortsteil")])


def _quote(path: str) -> str:
    return path.replace("'", "''")


def _create_parquet_view(con: duckdb.DuckDBPyConnection, name: str, pattern: Path, empty_schema: pa.Schema) -> None:
    if glob.glob(str(pattern)):
        con.execute(
            f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{_quote(str(pattern))}', hive_partitioning=true)"
        )
    else:
        con.register(name, empty_schema.empty_table())


def connect(data_dir: str | Path, source: str = "nextbike_bn") -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with views over ``data_dir`` for ``source``.

    Views: ``station_status``, ``station_information``, ``vehicle_types``,
    ``free_bike_cells``, ``gaps`` (each with a hive-derived ``date`` column
    holding the partition's UTC calendar date) and ``station_areas`` (no
    partitioning). Any of them is an empty view, not an error, when the
    underlying file(s) are missing.
    """
    data_dir = Path(data_dir)
    con = duckdb.connect()

    for dataset in _DATASETS:
        pattern = data_dir / source / dataset / "date=*" / "*.parquet"
        empty_schema = SCHEMAS[dataset].append(pa.field("date", pa.date32()))
        _create_parquet_view(con, dataset, pattern, empty_schema)

    areas_path = data_dir / "areas" / "station_areas.parquet"
    if areas_path.is_file():
        con.execute(f"CREATE VIEW station_areas AS SELECT * FROM read_parquet('{_quote(str(areas_path))}')")
    else:
        con.register("station_areas", _AREAS_SCHEMA.empty_table())

    return con
