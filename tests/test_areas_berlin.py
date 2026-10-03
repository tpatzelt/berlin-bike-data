"""G2 definition of done against the real committed Berlin polygons.

Every station in the recorded nextbike ``station_information`` fixture must
map to exactly one Bezirk and one Ortsteil of ``data/geo/*.geojson``. A
failure lists the offending stations. ``refresh_station_areas`` is then
checked end to end: Parquet in, ``station_areas`` view out.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa

from berlinbikes.analysis.db import connect
from berlinbikes.areas import DEFAULT_GEO_DIR, load_areas, map_stations, refresh_station_areas
from berlinbikes.schemas import SCHEMAS
from berlinbikes.storage import Storage

FIXTURE = Path(__file__).parent / "fixtures" / "gbfs" / "nextbike_bn" / "station_information.json"
SOURCE = "nextbike_bn"


def _fixture_stations() -> list[dict]:
    return json.loads(FIXTURE.read_text())["data"]["stations"]


def test_committed_layers_have_every_bezirk_and_ortsteil():
    bezirke = load_areas(DEFAULT_GEO_DIR / "bezirke.geojson", "name")
    ortsteile = load_areas(DEFAULT_GEO_DIR / "ortsteile.geojson", "name")
    assert len(bezirke) == 12
    assert len(ortsteile) == 97
    assert {"Mitte", "Friedrichshain-Kreuzberg", "Spandau"} <= {a.name for a in bezirke}


def test_every_recorded_station_maps_to_exactly_one_bezirk_and_ortsteil():
    stations = [(SOURCE, s["station_id"], s["lat"], s["lon"]) for s in _fixture_stations()]
    rows, problems = map_stations(
        stations,
        load_areas(DEFAULT_GEO_DIR / "bezirke.geojson", "name"),
        load_areas(DEFAULT_GEO_DIR / "ortsteile.geojson", "name"),
    )
    assert problems == [], "stations outside or between the polygons: " + ", ".join(
        f"{p.station_id} ({p.layer}: {p.reason} {p.matches})" for p in problems
    )
    assert len(rows) == len(stations)


def test_refresh_station_areas_writes_the_view(tmp_path):
    snapshot_ts = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    rows = [
        {"snapshot_ts": snapshot_ts, "source": SOURCE, "station_id": s["station_id"], "name": s["name"],
         "lat": s["lat"], "lon": s["lon"], "capacity": s.get("capacity")}
        for s in _fixture_stations()
    ]
    Storage(tmp_path).write("station_information", SOURCE, pa.Table.from_pylist(rows, schema=SCHEMAS["station_information"]))

    assert refresh_station_areas(tmp_path, SOURCE) == []

    con = connect(tmp_path, SOURCE)
    (n, n_bezirke) = con.execute("SELECT count(*), count(DISTINCT bezirk) FROM station_areas").fetchone()
    assert n == len(rows)
    assert n_bezirke == 12


def test_refresh_station_areas_without_data_writes_nothing(tmp_path):
    assert refresh_station_areas(tmp_path, SOURCE) == []
    assert not (tmp_path / "areas").exists()
