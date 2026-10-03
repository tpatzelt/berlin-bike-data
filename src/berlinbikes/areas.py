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


def _matching_names(lat: float, lon: float, areas: Iterable[Area]) -> list[str]:
    return [area.name for area in areas if point_in_geometry(lon, lat, area.geometry)]


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

    for source, station_id, lat, lon in stations:
        bezirk_matches = _matching_names(lat, lon, bezirke)
        ortsteil_matches = _matching_names(lat, lon, ortsteile)

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
