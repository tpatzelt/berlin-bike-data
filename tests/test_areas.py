"""Tests for berlinbikes.areas: stdlib point-in-polygon station mapping.

Builds tiny synthetic GeoJSON FeatureCollections in ``tmp_path`` -- two
adjacent Bezirke (one with a hole, one a MultiPolygon split in two), each
with two Ortsteile -- and checks map_stations against them: a clean match,
a point inside a hole, a point outside every polygon, a MultiPolygon match,
overlapping polygons, and a round trip through berlinbikes.analysis.db so
the station_areas view sees exactly the rows write_station_areas wrote.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from berlinbikes.analysis.db import connect
from berlinbikes.areas import AREAS_SCHEMA, load_areas, map_stations, write_station_areas

SOURCE = "nextbike_bn"


def _square(lon0: float, lat0: float, lon1: float, lat1: float) -> list[list[float]]:
    """A closed square ring in [lon, lat] order."""
    return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]


def _feature(name: str, name_property: str, geometry_type: str, coordinates: list) -> dict:
    return {
        "type": "Feature",
        "properties": {name_property: name},
        "geometry": {"type": geometry_type, "coordinates": coordinates},
    }


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


# BZ-A: a square with a hole. BZ-B: a MultiPolygon split into two squares.
# Adjacent along lon=2, both spanning lat 0-2.
_HOLE = _square(0.5, 0.3, 1.0, 0.7)

BEZIRKE_FEATURES = [
    _feature("BZ-A", "bezirk", "Polygon", [_square(0.0, 0.0, 2.0, 2.0), _HOLE]),
    _feature("BZ-B", "bezirk", "MultiPolygon", [[_square(2.0, 0.0, 3.0, 2.0)], [_square(3.0, 0.0, 4.0, 2.0)]]),
]

ORTSTEILE_FEATURES = [
    _feature("OT-A1", "ortsteil", "Polygon", [_square(0.0, 0.0, 2.0, 1.0)]),
    _feature("OT-A2", "ortsteil", "Polygon", [_square(0.0, 1.0, 2.0, 2.0)]),
    _feature("OT-B1", "ortsteil", "Polygon", [_square(2.0, 0.0, 3.0, 2.0)]),
    _feature("OT-B2", "ortsteil", "Polygon", [_square(3.0, 0.0, 4.0, 2.0)]),
]


def _load_main_areas(tmp_path):
    bezirke_path = tmp_path / "bezirke.geojson"
    ortsteile_path = tmp_path / "ortsteile.geojson"
    _write_geojson(bezirke_path, BEZIRKE_FEATURES)
    _write_geojson(ortsteile_path, ORTSTEILE_FEATURES)
    bezirke = load_areas(bezirke_path, "bezirk")
    ortsteile = load_areas(ortsteile_path, "ortsteil")
    return bezirke, ortsteile


def test_load_areas_reads_names_and_geometry(tmp_path):
    bezirke, _ = _load_main_areas(tmp_path)
    names = sorted(area.name for area in bezirke)
    assert names == ["BZ-A", "BZ-B"]


def test_station_inside_one_bezirk_and_ortsteil_is_a_clean_row(tmp_path):
    bezirke, ortsteile = _load_main_areas(tmp_path)
    stations = [(SOURCE, "S-INSIDE", 1.5, 0.5)]  # lat, lon

    rows, problems = map_stations(stations, bezirke, ortsteile)

    assert problems == []
    assert rows == [{"source": SOURCE, "station_id": "S-INSIDE", "bezirk": "BZ-A", "ortsteil": "OT-A2"}]


def test_station_inside_a_hole_is_excluded_from_its_bezirk(tmp_path):
    bezirke, ortsteile = _load_main_areas(tmp_path)
    # lon=0.75, lat=0.5 is inside the hole cut out of BZ-A, but still inside OT-A1.
    stations = [(SOURCE, "S-HOLE", 0.5, 0.75)]

    rows, problems = map_stations(stations, bezirke, ortsteile)

    assert rows == []
    assert len(problems) == 1
    problem = problems[0]
    assert (problem.source, problem.station_id, problem.layer, problem.reason) == (
        SOURCE,
        "S-HOLE",
        "bezirk",
        "no match",
    )
    assert problem.matches == ()


def test_station_outside_every_polygon_is_reported_for_both_layers(tmp_path):
    bezirke, ortsteile = _load_main_areas(tmp_path)
    stations = [(SOURCE, "S-OUTSIDE", 52.5, 13.4)]  # far outside the tiny synthetic squares

    rows, problems = map_stations(stations, bezirke, ortsteile)

    assert rows == []
    layers_and_reasons = {(p.layer, p.reason) for p in problems}
    assert layers_and_reasons == {("bezirk", "no match"), ("ortsteil", "no match")}
    assert all(p.station_id == "S-OUTSIDE" for p in problems)


def test_station_in_multipolygon_bezirk_matches_its_part(tmp_path):
    bezirke, ortsteile = _load_main_areas(tmp_path)
    # Inside the second square of BZ-B's MultiPolygon and inside OT-B2.
    stations = [(SOURCE, "S-MULTI", 1.0, 3.5)]

    rows, problems = map_stations(stations, bezirke, ortsteile)

    assert problems == []
    assert rows == [{"source": SOURCE, "station_id": "S-MULTI", "bezirk": "BZ-B", "ortsteil": "OT-B2"}]


def test_station_in_overlapping_bezirke_is_reported_as_multiple_matches(tmp_path):
    overlap_bezirke_path = tmp_path / "overlap_bezirke.geojson"
    overlap_ortsteile_path = tmp_path / "overlap_ortsteile.geojson"
    _write_geojson(
        overlap_bezirke_path,
        [
            _feature("BZ-X", "bezirk", "Polygon", [_square(0.0, 0.0, 2.0, 2.0)]),
            _feature("BZ-Y", "bezirk", "Polygon", [_square(1.0, 1.0, 3.0, 3.0)]),
        ],
    )
    _write_geojson(
        overlap_ortsteile_path,
        [_feature("OT-XY", "ortsteil", "Polygon", [_square(0.0, 0.0, 3.0, 3.0)])],
    )
    bezirke = load_areas(overlap_bezirke_path, "bezirk")
    ortsteile = load_areas(overlap_ortsteile_path, "ortsteil")
    stations = [(SOURCE, "S-OVERLAP", 1.5, 1.5)]  # inside both BZ-X and BZ-Y

    rows, problems = map_stations(stations, bezirke, ortsteile)

    assert rows == []
    assert len(problems) == 1
    problem = problems[0]
    assert (problem.layer, problem.reason) == ("bezirk", "multiple matches")
    assert set(problem.matches) == {"BZ-X", "BZ-Y"}


def test_write_station_areas_round_trips_through_analysis_db(tmp_path):
    bezirke, ortsteile = _load_main_areas(tmp_path)
    stations = [
        (SOURCE, "S-INSIDE", 1.5, 0.5),
        (SOURCE, "S-MULTI", 1.0, 3.5),
        (SOURCE, "S-OUTSIDE", 52.5, 13.4),
    ]

    rows, problems = map_stations(stations, bezirke, ortsteile)
    assert len(rows) == 2
    assert len(problems) == 2  # S-OUTSIDE, once per layer

    data_dir = tmp_path / "data"
    out_path = write_station_areas(rows, data_dir)

    assert out_path == data_dir / "areas" / "station_areas.parquet"
    written = pq.read_table(out_path)
    assert written.schema.equals(AREAS_SCHEMA)

    con = connect(data_dir)
    db_rows = con.execute(
        "SELECT source, station_id, bezirk, ortsteil FROM station_areas ORDER BY station_id"
    ).fetchall()
    assert db_rows == [
        (SOURCE, "S-INSIDE", "BZ-A", "OT-A2"),
        (SOURCE, "S-MULTI", "BZ-B", "OT-B2"),
    ]
