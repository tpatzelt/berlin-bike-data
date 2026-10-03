"""Stdlib point-in-polygon mapping of stations to Bezirk and Ortsteil polygons.

No third-party geometry library: ray casting over GeoJSON ``Polygon`` (with
holes) and ``MultiPolygon`` geometries, coordinates in ``[lon, lat]`` order
as GeoJSON mandates. :func:`load_areas` reads one GeoJSON ``FeatureCollection``
layer (Bezirke or Ortsteile); :func:`map_stations` matches stations against
two such layers and reports any station that is not in exactly one polygon
per layer; :func:`write_station_areas` writes the ADR-0003 file contract
(``{data_dir}/areas/station_areas.parquet``) that
:mod:`berlinbikes.analysis.db` reads as the ``station_areas`` view.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import pyarrow as pa
import pyarrow.parquet as pq

AREAS_SCHEMA = pa.schema([pa.field(c, pa.string()) for c in ("source", "station_id", "bezirk", "ortsteil")])

Ring = list[list[float]]
PolygonCoords = list[Ring]
Station = tuple[str, str, float, float]


class Area(NamedTuple):
    name: str
    geometry: dict


class Problem(NamedTuple):
    source: str
    station_id: str
    layer: str
    reason: str
    matches: tuple[str, ...]


def _point_in_ring(lon: float, lat: float, ring: Ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            x_intersect = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_intersect:
                inside = not inside
    return inside


def _point_in_polygon_coords(lon: float, lat: float, rings: PolygonCoords) -> bool:
    if not rings or not _point_in_ring(lon, lat, rings[0]):
        return False
    return not any(_point_in_ring(lon, lat, hole) for hole in rings[1:])


def point_in_geometry(lon: float, lat: float, geometry: dict) -> bool:
    """True if ``(lon, lat)`` is inside a GeoJSON ``Polygon`` or ``MultiPolygon``."""
    geometry_type = geometry["type"]
    coordinates = geometry["coordinates"]
    if geometry_type == "Polygon":
        return _point_in_polygon_coords(lon, lat, coordinates)
    if geometry_type == "MultiPolygon":
        return any(_point_in_polygon_coords(lon, lat, polygon) for polygon in coordinates)
    raise ValueError(f"unsupported geometry type: {geometry_type!r}")


def load_areas(path: str | Path, name_property: str) -> list[Area]:
    """Read a GeoJSON ``FeatureCollection`` into one :class:`Area` per feature.

    ``name_property`` is the key in each feature's ``properties`` that holds
    the area's name (the Bezirk or Ortsteil name).
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path}: not a GeoJSON FeatureCollection")
    return [
        Area(name=feature["properties"][name_property], geometry=feature["geometry"])
        for feature in data["features"]
    ]


def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    lons = [p[0] for polygon in polygons for p in polygon[0]]
    lats = [p[1] for polygon in polygons for p in polygon[0]]
    return min(lons), min(lats), max(lons), max(lats)


def _matching_names(lat: float, lon: float, areas: Iterable[tuple[Area, tuple[float, float, float, float]]]) -> list[str]:
    # Cheap bounding-box reject first: real Ortsteil rings have thousands of vertices.
    return [
        area.name
        for area, (min_lon, min_lat, max_lon, max_lat) in areas
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat and point_in_geometry(lon, lat, area.geometry)
    ]


def map_stations(
    stations: Iterable[Station],
    bezirke: list[Area],
    ortsteile: list[Area],
) -> tuple[list[dict], list[Problem]]:
    """Match each ``(source, station_id, lat, lon)`` station against both layers.

    A station is written to ``rows`` only if it falls in exactly one Bezirk
    and exactly one Ortsteil; otherwise one :class:`Problem` per offending
    layer is added to ``problems`` instead, with the matched names (empty for
    no match).
    """
    rows: list[dict] = []
    problems: list[Problem] = []
    bezirke_boxed = [(area, _bbox(area.geometry)) for area in bezirke]
    ortsteile_boxed = [(area, _bbox(area.geometry)) for area in ortsteile]

    for source, station_id, lat, lon in stations:
        bezirk_matches = _matching_names(lat, lon, bezirke_boxed)
        ortsteil_matches = _matching_names(lat, lon, ortsteile_boxed)

        layer_matches = (("bezirk", bezirk_matches), ("ortsteil", ortsteil_matches))
        ok = True
        for layer, matches in layer_matches:
            if len(matches) == 0:
                problems.append(Problem(source, station_id, layer, "no match", ()))
                ok = False
            elif len(matches) > 1:
                problems.append(Problem(source, station_id, layer, "multiple matches", tuple(matches)))
                ok = False

        if ok:
            rows.append(
                {
                    "source": source,
                    "station_id": station_id,
                    "bezirk": bezirk_matches[0],
                    "ortsteil": ortsteil_matches[0],
                }
            )

    return rows, problems


def write_station_areas(rows: list[dict], data_dir: str | Path) -> Path:
    """Write ``rows`` to ``{data_dir}/areas/station_areas.parquet`` (ADR-0003)."""
    path = Path(data_dir) / "areas" / "station_areas.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=AREAS_SCHEMA), path)
    return path


#: The committed Bezirk and Ortsteil layers (see data/SOURCES.md).
DEFAULT_GEO_DIR = Path(__file__).resolve().parents[2] / "data" / "geo"


def refresh_station_areas(
    data_dir: str | Path,
    source: str = "nextbike_bn",
    geo_dir: str | Path = DEFAULT_GEO_DIR,
) -> list[Problem]:
    """Map every station's latest known position and rewrite ``station_areas``.

    Reads ``station_information`` for ``source`` from ``data_dir``, maps each
    station against ``geo_dir``'s ``bezirke.geojson`` and ``ortsteile.geojson``
    and writes the result with :func:`write_station_areas`. Stations outside
    the polygons are left out (and returned as problems), so they simply drop
    out of the per-Bezirk and per-Ortsteil metrics. Does nothing when no
    station_information has been collected yet.
    """
    from berlinbikes.analysis.db import connect

    geo_dir = Path(geo_dir)
    con = connect(data_dir, source)
    stations = con.execute(
        """
        SELECT source, station_id, arg_max(lat, snapshot_ts), arg_max(lon, snapshot_ts)
        FROM station_information
        GROUP BY source, station_id
        ORDER BY station_id
        """
    ).fetchall()
    con.close()
    if not stations:
        return []
    rows, problems = map_stations(
        stations,
        load_areas(geo_dir / "bezirke.geojson", "name"),
        load_areas(geo_dir / "ortsteile.geojson", "name"),
    )
    write_station_areas(rows, data_dir)
    return problems
