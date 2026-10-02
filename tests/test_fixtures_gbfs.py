"""Offline shape checks for the recorded nextbike_bn GBFS fixtures.

These fixtures are recorded once from the live feed by
``scripts/record_gbfs_fixtures.py`` (a manual tool; pytest never imports or
runs it). These tests only replay the files already committed under
``tests/fixtures/gbfs/nextbike_bn/``.
"""

import json
import re
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gbfs" / "nextbike_bn"

REQUIRED_FEED_FILES = [
    "gbfs.json",
    "station_information.json",
    "station_status.json",
    "free_bike_status.json",
    "vehicle_types.json",
]

_TRAILING_DIGITS = re.compile(r"\d+(?!.*\d)")


def _load(filename: str) -> dict:
    return json.loads((FIXTURE_DIR / filename).read_text())


@pytest.mark.parametrize("filename", REQUIRED_FEED_FILES)
def test_feed_file_is_present_and_nonempty(filename):
    path = FIXTURE_DIR / filename
    assert path.is_file()
    assert path.stat().st_size > 0


@pytest.mark.parametrize("filename", REQUIRED_FEED_FILES)
def test_feed_file_has_gbfs_envelope(filename):
    data = _load(filename)
    assert "last_updated" in data
    assert "ttl" in data
    assert "data" in data
    assert data["data"]


def test_station_information_has_stations():
    data = _load("station_information.json")
    assert data["data"]["stations"]


def test_free_bike_status_bike_ids_are_pseudonymised():
    data = _load("free_bike_status.json")
    bikes = data["data"]["bikes"]
    assert bikes
    for bike in bikes:
        assert bike["bike_id"].startswith("fixture-")


def test_free_bike_status_rental_uris_carry_no_real_per_bike_id():
    """Charter non-goal: no per-bike identifier may reach disk.

    A bike's rental_uris embed a numeric place id. For bikes docked at a
    station that id is the station's own public id (already present in
    station_information). For free-floating bikes it is otherwise a real,
    per-bike nextbike identifier, so it must have been rewritten to the
    bike's own synthetic suffix.
    """
    data = _load("free_bike_status.json")
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
