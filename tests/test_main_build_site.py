"""Tests for ``berlinbikes.__main__``'s ``build-site`` and ``nightly`` commands.

``build-site`` just calls ``berlinbikes.site.build_site`` with the configured
directories. ``nightly`` runs the weather backfill first and always rebuilds
the site afterwards, even when the weather backfill gives up, since a stale
site is worse than one with a known weather gap.

All HTTP is replayed through httpx.MockTransport; nothing here touches the
network (the autouse socket guard in conftest.py would fail the test if it
tried).
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone

import httpx

from berlinbikes.__main__ import main, run_nightly
from berlinbikes.backoff import FakeClock

from tests.helpers import make_settings

NOW = datetime(2026, 1, 10, 3, 0, tzinfo=timezone.utc)


def _data_dir(tmp_path, synthetic_data_dir):
    data_dir = tmp_path / "data"
    shutil.copytree(synthetic_data_dir, data_dir)
    return data_dir


def test_build_site_command_writes_index_and_methodology(tmp_path, synthetic_data_dir, monkeypatch):
    data_dir = _data_dir(tmp_path, synthetic_data_dir)
    site_dir = tmp_path / "site-out"
    monkeypatch.setenv("BIKES_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BIKES_SITE_DIR", str(site_dir))
    monkeypatch.setenv("BIKES_USER_AGENT", "berlinbikes-test/1.0")

    result = main(["build-site"])

    assert result == 0
    assert (site_dir / "index.html").is_file()
    assert (site_dir / "methodology.html").is_file()


def _always_503_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    return httpx.MockTransport(handler)


def _always_200_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": (start.replace(hour=i)).isoformat(),
                "precipitation": 0.0,
                "temperature": float(i),
                "condition": "dry",
            }
            for i in range(24)
        ]
        return httpx.Response(200, json={"weather": records})

    return httpx.MockTransport(handler)


def test_nightly_still_builds_site_and_returns_one_when_weather_fails(
    tmp_path, synthetic_data_dir
):
    data_dir = _data_dir(tmp_path, synthetic_data_dir)
    site_dir = tmp_path / "site-out"
    settings = make_settings(
        tmp_path,
        BIKES_DATA_DIR=str(data_dir),
        BIKES_SITE_DIR=str(site_dir),
    )
    clock = FakeClock(NOW)

    result = run_nightly(
        settings, clock, days_back=7, transport=_always_503_transport()
    )

    assert result == 1
    assert (site_dir / "index.html").is_file()


def test_nightly_returns_zero_when_weather_succeeds(tmp_path, synthetic_data_dir):
    data_dir = _data_dir(tmp_path, synthetic_data_dir)
    site_dir = tmp_path / "site-out"
    settings = make_settings(
        tmp_path,
        BIKES_DATA_DIR=str(data_dir),
        BIKES_SITE_DIR=str(site_dir),
    )
    clock = FakeClock(NOW)

    result = run_nightly(
        settings, clock, days_back=7, transport=_always_200_transport()
    )

    assert result == 0
    assert (site_dir / "index.html").is_file()
