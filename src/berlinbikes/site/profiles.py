"""Builds ``data/profiles.json`` for the interactive map page.

The map page has no build step and no server-side logic, so the nightly
build writes every station's and Ortsteil's weekday x local-hour curve as
one compact JSON file next to the pages. Only station-level fields go in;
no bike ids exist anywhere in the dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

from berlinbikes.analysis.db import connect
from berlinbikes.analysis.profiles import ortsteil_profiles, station_profiles


def _empty_curve() -> list[list[float | None]]:
    return [[None] * 24 for _ in range(7)]


def profiles_payload(data_dir: str | Path) -> dict:
    """The JSON document behind ``map.html``.

    ``{"status": "ok", "full_days": N, "stations": [{"id", "name", "lat",
    "lon", "ortsteil", "curve"}], "ortsteile": [{"name", "curve"}]}`` where
    each ``curve`` is 7 weekday lists (Monday first) of 24 hourly means,
    rounded to 1 decimal, ``null`` where there is no data. Below the
    14-full-day minimum: ``{"status": "insufficient_data", "full_days": N,
    "message": ...}``.
    """
    con = connect(Path(data_dir))
    stations = station_profiles(con)
    if stations.status != "ok":
        return {"status": stations.status, "full_days": stations.full_days, "message": stations.message}
    ortsteile = ortsteil_profiles(con)

    by_station: dict[str, dict] = {}
    for station_id, name, lat, lon, ortsteil, weekday, hour, mean, _n in stations.rows:
        entry = by_station.setdefault(
            station_id,
            {"id": station_id, "name": name, "lat": round(lat, 5), "lon": round(lon, 5), "ortsteil": ortsteil,
             "curve": _empty_curve()},
        )
        entry["curve"][weekday][hour] = round(mean, 1)

    by_ortsteil: dict[str, dict] = {}
    for ortsteil, weekday, hour, mean, _n in ortsteile.rows or []:
        entry = by_ortsteil.setdefault(ortsteil, {"name": ortsteil, "curve": _empty_curve()})
        entry["curve"][weekday][hour] = round(mean, 1)

    return {
        "status": "ok",
        "full_days": stations.full_days,
        "stations": sorted(by_station.values(), key=lambda s: s["name"] or s["id"]),
        "ortsteile": sorted(by_ortsteil.values(), key=lambda o: o["name"]),
    }


def write_profiles_json(data_dir: str | Path, site_dir: str | Path) -> Path:
    path = Path(site_dir) / "data" / "profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profiles_payload(data_dir), ensure_ascii=False, separators=(",", ":")))
    return path
