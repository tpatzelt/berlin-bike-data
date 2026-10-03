"""Fetch Berlin's Bezirk and Ortsteil polygons into data/geo/ (G2).

Run by hand, not by tests or the collector:

    uv run python scripts/fetch_berlin_areas.py

Source: Geoportal Berlin WFS (ALKIS Bezirke / Ortsteile), licensed under
Datenlizenz Deutschland - Zero - Version 2.0. Coordinates are rounded to 5
decimals (about 1 m). Rounding is applied to every vertex the same way, so
borders shared by neighbouring polygons stay identical and a station on one
side never ends up in zero or two areas because of the rounding.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

WFS = "https://gdi.berlin.de/services/wfs/{service}"
PARAMS = {
    "SERVICE": "WFS",
    "VERSION": "2.0.0",
    "REQUEST": "GetFeature",
    "OUTPUTFORMAT": "application/json",
    "SRSNAME": "EPSG:4326",
}
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "geo"


def _round_rings(geometry: dict) -> dict:
    def ring(points: list) -> list:
        out: list[list[float]] = []
        for lon, lat, *_ in points:
            point = [round(lon, 5), round(lat, 5)]
            if not out or out[-1] != point:
                out.append(point)
        return out

    if geometry["type"] == "Polygon":
        coordinates = [ring(r) for r in geometry["coordinates"]]
    else:
        coordinates = [[ring(r) for r in polygon] for polygon in geometry["coordinates"]]
    return {"type": geometry["type"], "coordinates": coordinates}


def _fetch(service: str, typename: str) -> list[dict]:
    response = httpx.get(WFS.format(service=service), params={**PARAMS, "TYPENAMES": typename}, timeout=120)
    response.raise_for_status()
    return response.json()["features"]


def _write(path: Path, features: list[dict]) -> None:
    features.sort(key=lambda f: f["properties"]["name"])
    collection = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{path}: {len(features)} features, {path.stat().st_size / 1e6:.2f} MB")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    bezirke = _fetch("alkis_bezirke", "alkis_bezirke:bezirksgrenzen")
    bezirk_by_code = {f["properties"]["gem"]: f["properties"]["namgem"] for f in bezirke}
    _write(
        OUT_DIR / "bezirke.geojson",
        [
            {"type": "Feature", "properties": {"name": f["properties"]["namgem"]}, "geometry": _round_rings(f["geometry"])}
            for f in bezirke
        ],
    )

    ortsteile = _fetch("alkis_ortsteile", "alkis_ortsteile:ortsteile")
    _write(
        OUT_DIR / "ortsteile.geojson",
        [
            {
                "type": "Feature",
                # sch is the 12-digit municipal key: 11 000 BBB OOOO, BBB = Bezirk code.
                "properties": {"name": f["properties"]["nam"], "bezirk": bezirk_by_code[f["properties"]["sch"][5:8]]},
                "geometry": _round_rings(f["geometry"]),
            }
            for f in ortsteile
        ],
    )


if __name__ == "__main__":
    main()
