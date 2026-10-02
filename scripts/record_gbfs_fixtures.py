#!/usr/bin/env python3
"""Manual tool: records GBFS fixtures from the live feeds below.

Not imported or run by pytest. Run this script by hand (from a sandbox that
is allowed to reach the chosen system's host) with ``--system
{nextbike_bn,dott_berlin}`` to (re)populate ``tests/fixtures/gbfs/<system>/*.json``.
It makes a handful of one-shot GET requests: ``gbfs.json``, then every feed
it lists for the system's locale, with no retries and no loop. There is no
default system: the operator must say which one to hit, so a bare invocation
never re-fetches a source that is not part of the current task.

Charter non-goal: ``bike_id`` must never be written to disk. Before saving
``free_bike_status.json`` this script replaces every ``bike_id`` with a
synthetic ``fixture-NNNN`` value.

For nextbike, bikes that are not docked at a station (no ``station_id``)
also carry a real per-bike nextbike place id embedded in ``rental_uris``
(the trailing digits of the URL), so that id is rewritten to the same NNNN.
Docked bikes keep their rental_uris unchanged, because that id is the
station's own public id, already present in station_information.

For Dott, ``rental_uris`` embeds the real ``bike_id`` UUID directly in the
URL path, so the scrub is a literal substring replace of the real UUID with
the synthetic id.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "gbfs"
ENV_EXAMPLE = REPO_ROOT / "deploy" / ".bikes.env.example"

MAX_FREE_BIKES = 600

_TRAILING_DIGITS = re.compile(r"\d+(?!.*\d)")


@dataclass(frozen=True)
class SystemSpec:
    gbfs_url: str
    locale: str
    required_feeds: tuple[str, ...]
    optional_feeds: tuple[str, ...] = ()


SYSTEMS: dict[str, SystemSpec] = {
    "nextbike_bn": SystemSpec(
        gbfs_url="https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json",
        locale="de",
        required_feeds=("station_information", "station_status", "free_bike_status", "vehicle_types"),
        optional_feeds=("system_information",),
    ),
    "dott_berlin": SystemSpec(
        # Dott only publishes a single "en" locale (confirmed against the live
        # feed: no "de" key). It also lists gbfs_versions, geofencing_zones and
        # system_pricing_plans, none of which G1's collector interface needs
        # (station_information/station_status/vehicle_types/free_bike_status),
        # so those three are fetched to confirm their shape but not persisted;
        # see tests/fixtures/gbfs/dott_berlin/README.md.
        gbfs_url="https://gbfs.api.ridedott.com/public/v2/berlin/gbfs.json",
        locale="en",
        required_feeds=("free_bike_status",),
        optional_feeds=(
            "station_information",
            "station_status",
            "vehicle_types",
            "system_information",
            "gbfs_versions",
            "geofencing_zones",
            "system_pricing_plans",
        ),
    ),
}

# Feeds whose shape is only confirmed, never written to tests/fixtures/.
SKIP_PERSISTING = {"gbfs_versions", "geofencing_zones", "system_pricing_plans"}


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


def _pseudonymise_nextbike_bike_ids(free_bike_status: dict[str, Any]) -> dict[str, Any]:
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


def _pseudonymise_dott_bike_ids(free_bike_status: dict[str, Any]) -> dict[str, Any]:
    """Replace every bike_id with 'fixture-NNNN' and scrub it out of rental_uris.

    Dott embeds the real bike_id UUID directly in the rental_uris path
    (unlike nextbike's separate numeric place id), so the scrub is a literal
    substring replace of the real id with the synthetic one.
    """
    bikes = free_bike_status["data"]["bikes"]
    bikes[:] = bikes[:MAX_FREE_BIKES]
    for index, bike in enumerate(bikes, start=1):
        real_id = bike["bike_id"]
        synthetic = f"fixture-{index:04d}"
        bike["bike_id"] = synthetic
        rental_uris = bike.get("rental_uris") or {}
        for key, uri in rental_uris.items():
            rental_uris[key] = uri.replace(real_id, synthetic)
    return free_bike_status


PSEUDONYMISERS = {
    "nextbike_bn": _pseudonymise_nextbike_bike_ids,
    "dott_berlin": _pseudonymise_dott_bike_ids,
}


def _write(system: str, name: str, payload: dict[str, Any]) -> None:
    path = FIXTURE_ROOT / system / name
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    print(f"wrote {path}")


def record(system: str) -> None:
    spec = SYSTEMS[system]
    fixture_dir = FIXTURE_ROOT / system
    fixture_dir.mkdir(parents=True, exist_ok=True)
    user_agent = _user_agent()

    gbfs_payload = _fetch(spec.gbfs_url, user_agent)
    _write(system, "gbfs.json", gbfs_payload)

    feed_urls = _feed_urls(gbfs_payload, spec.locale)
    for name in spec.required_feeds:
        if name not in feed_urls:
            raise RuntimeError(f"required feed {name!r} missing from gbfs.json for locale {spec.locale!r}")

    for name in (*spec.required_feeds, *spec.optional_feeds):
        url = feed_urls.get(name)
        if url is None:
            continue
        payload = _fetch(url, user_agent)
        if name == "free_bike_status":
            payload = PSEUDONYMISERS[system](payload)
        if name in SKIP_PERSISTING:
            continue
        _write(system, f"{name}.json", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", required=True, choices=sorted(SYSTEMS))
    args = parser.parse_args()
    record(args.system)


if __name__ == "__main__":
    main()
