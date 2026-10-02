#!/usr/bin/env python3
"""Manual tool: records the nextbike_bn GBFS 2.3 fixtures from the live feed.

Not imported or run by pytest. Run this script by hand (from a sandbox that
is allowed to reach gbfs.nextbike.net) to (re)populate
``tests/fixtures/gbfs/nextbike_bn/*.json``. It makes a handful of one-shot
GET requests: ``gbfs.json``, then every feed it lists for LOCALE (plus
``system_information`` if present), with no retries and no loop.

Charter non-goal: ``bike_id`` must never be written to disk. Before saving
``free_bike_status.json`` this script replaces every ``bike_id`` with a
synthetic ``fixture-NNNN`` value. For bikes that are not docked at a station
(no ``station_id``), ``rental_uris`` also carries a real per-bike nextbike
place id embedded in the URL, so that numeric id is rewritten to the same
NNNN as well. Bikes docked at a station keep their rental_uris unchanged,
because that id is the station's public id, already present in
station_information.
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "gbfs" / "nextbike_bn"
ENV_EXAMPLE = REPO_ROOT / "deploy" / ".bikes.env.example"

GBFS_ROOT_URL = "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json"
LOCALE = "de"
REQUIRED_FEEDS = ("station_information", "station_status", "free_bike_status", "vehicle_types")
OPTIONAL_FEEDS = ("system_information",)

_TRAILING_DIGITS = re.compile(r"\d+(?!.*\d)")


def _user_agent() -> str:
    for line in ENV_EXAMPLE.read_text().splitlines():
        if line.startswith("BIKES_USER_AGENT="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"BIKES_USER_AGENT not found in {ENV_EXAMPLE}")


def _fetch(url: str, user_agent: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _feed_urls(gbfs_payload: dict[str, Any], locale: str) -> dict[str, str]:
    feeds = gbfs_payload["data"][locale]["feeds"]
    return {feed["name"]: feed["url"] for feed in feeds}


def _pseudonymise_bike_ids(free_bike_status: dict[str, Any]) -> dict[str, Any]:
    """Replace every bike_id with 'fixture-NNNN' and scrub rental_uris.

    Idempotent and offline: operates only on the already-parsed payload, so
    it can be re-run against a saved fixture (no new live calls) if the
    rental_uris scrub ever needs to be redone.
    """
    bikes = free_bike_status["data"]["bikes"]
    for index, bike in enumerate(bikes, start=1):
        suffix = f"{index:04d}"
        bike["bike_id"] = f"fixture-{suffix}"
        station_id = bike.get("station_id")
        if station_id:
            continue  # docked: rental_uris carry the station's public id, not a per-bike id
        rental_uris = bike.get("rental_uris") or {}
        for key, uri in rental_uris.items():
            rental_uris[key] = _TRAILING_DIGITS.sub(suffix, uri)
    return free_bike_status


def _write(name: str, payload: dict[str, Any]) -> None:
    path = FIXTURE_DIR / name
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    print(f"wrote {path}")


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    user_agent = _user_agent()

    gbfs_payload = _fetch(GBFS_ROOT_URL, user_agent)
    _write("gbfs.json", gbfs_payload)

    feed_urls = _feed_urls(gbfs_payload, LOCALE)
    for name in REQUIRED_FEEDS:
        if name not in feed_urls:
            raise RuntimeError(f"required feed {name!r} missing from gbfs.json for locale {LOCALE!r}")

    for name in (*REQUIRED_FEEDS, *OPTIONAL_FEEDS):
        url = feed_urls.get(name)
        if url is None:
            continue
        payload = _fetch(url, user_agent)
        if name == "free_bike_status":
            payload = _pseudonymise_bike_ids(payload)
        _write(f"{name}.json", payload)


if __name__ == "__main__":
    main()
