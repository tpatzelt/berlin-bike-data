"""Offline shape checks for the recorded GBFS fixtures.

These fixtures are recorded once from the live feeds by
``scripts/record_gbfs_fixtures.py`` (a manual tool; pytest never imports or
runs it). These tests only replay the files already committed under
``tests/fixtures/gbfs/<system>/``.
"""

import json
import re
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "gbfs"

REQUIRED_FEED_FILES = {
    "nextbike_bn": [
        "gbfs.json",
        "station_information.json",
        "station_status.json",
        "free_bike_status.json",
        "vehicle_types.json",
    ],
    "dott_berlin": [
        "gbfs.json",
        "station_information.json",
        "station_status.json",
        "free_bike_status.json",
        "vehicle_types.json",
    ],
}
SYSTEMS = sorted(REQUIRED_FEED_FILES)

_TRAILING_DIGITS = re.compile(r"\d+(?!.*\d)")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _load(system: str, filename: str) -> dict:
    return json.loads((FIXTURE_ROOT / system / filename).read_text())


def _feed_file_params():
    return [(system, filename) for system in SYSTEMS for filename in REQUIRED_FEED_FILES[system]]


@pytest.mark.parametrize("system,filename", _feed_file_params())
def test_feed_file_is_present_and_nonempty(system, filename):
    path = FIXTURE_ROOT / system / filename
    assert path.is_file()
    assert path.stat().st_size > 0


@pytest.mark.parametrize("system,filename", _feed_file_params())
def test_feed_file_has_gbfs_envelope(system, filename):
    data = _load(system, filename)
    assert "last_updated" in data
    assert "ttl" in data
    assert "data" in data
    assert data["data"]


@pytest.mark.parametrize("system", SYSTEMS)
def test_station_information_has_stations(system):
    data = _load(system, "station_information.json")
    assert data["data"]["stations"]


@pytest.mark.parametrize("system", SYSTEMS)
def test_free_bike_status_bike_ids_are_pseudonymised(system):
    data = _load(system, "free_bike_status.json")
    bikes = data["data"]["bikes"]
    assert bikes
    for bike in bikes:
        assert bike["bike_id"].startswith("fixture-")


def test_nextbike_free_bike_status_rental_uris_carry_no_real_per_bike_id():
    """Charter non-goal: no per-bike identifier may reach disk.

    A bike's rental_uris embed a numeric place id. For bikes docked at a
    station that id is the station's own public id (already present in
    station_information). For free-floating bikes it is otherwise a real,
    per-bike nextbike identifier, so it must have been rewritten to the
    bike's own synthetic suffix.
    """
    data = _load("nextbike_bn", "free_bike_status.json")
    bikes = data["data"]["bikes"]
    checked_free_floating = 0
    for bike in bikes:
        rental_uris = bike.get("rental_uris") or {}
        station_id = bike.get("station_id")
        synthetic_suffix = bike["bike_id"].removeprefix("fixture-")
        for uri in rental_uris.values():
            match = _TRAILING_DIGITS.search(uri)
            assert match, f"no numeric id found in rental_uris value: {uri!r}"
            found_id = match.group(0)
            if station_id:
                assert found_id == str(station_id), (
                    f"docked bike {bike['bike_id']} rental_uris id {found_id!r} "
                    f"does not match its station_id {station_id!r}"
                )
            else:
                checked_free_floating += 1
                assert found_id == synthetic_suffix, (
                    f"free-floating bike {bike['bike_id']} rental_uris still carries "
                    f"a real per-bike id: {uri!r}"
                )
    assert checked_free_floating > 0


def test_dott_free_bike_status_rental_uris_carry_no_real_bike_id():
    """Charter non-goal: no per-bike identifier may reach disk.

    Dott embeds the real bike_id UUID directly in rental_uris, so once
    scrubbed no UUID should remain there at all, only the synthetic id.
    """
    data = _load("dott_berlin", "free_bike_status.json")
    bikes = data["data"]["bikes"]
    checked = 0
    for bike in bikes:
        rental_uris = bike.get("rental_uris") or {}
        for uri in rental_uris.values():
            checked += 1
            assert not _UUID.search(uri), f"rental_uris still carries a real bike_id UUID: {uri!r}"
            assert bike["bike_id"] in uri, f"rental_uris lost the pseudonymised id: {uri!r}"
    assert checked > 0


def test_dott_free_bike_status_is_trimmed_to_600():
    data = _load("dott_berlin", "free_bike_status.json")
    assert len(data["data"]["bikes"]) <= 600
