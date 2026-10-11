"""Shared test fixtures.

An autouse fixture blocks real network access so ``uv run pytest -q`` can
never depend on, or accidentally hit, a live feed.
"""

import socket
from datetime import date

import pytest

from tests.synthetic import build_dataset


class NetworkBlockedError(RuntimeError):
    """Raised when test code attempts to open a real network connection."""


def _blocked(*_args, **_kwargs):
    raise NetworkBlockedError("network access is blocked during tests")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


@pytest.fixture(params=["nextbike_bn", "dott_berlin"], ids=lambda p: p)
def source_name(request):
    return request.param


@pytest.fixture(scope="session")
def synthetic_data_dir(tmp_path_factory):
    """A 28-day synthetic dataset spanning the 2026-10-25 DST fall-back day."""
    data_dir = tmp_path_factory.mktemp("synthetic")
    build_dataset(data_dir, start_date=date(2026, 10, 12), days=28)
    return data_dir


@pytest.fixture(scope="session")
def built_empty_site(tmp_path_factory):
    """Site built once from an empty data dir; tests must treat it as read-only."""
    from berlinbikes.site import build_site

    data_dir = tmp_path_factory.mktemp("shared_empty_data")
    site_dir = tmp_path_factory.mktemp("shared_empty_site")
    build_site(data_dir, site_dir)
    return site_dir


@pytest.fixture(scope="session")
def built_synthetic_site(tmp_path_factory, synthetic_data_dir):
    """Site built once from the synthetic dataset (no operator); read-only."""
    from berlinbikes.site import build_site

    site_dir = tmp_path_factory.mktemp("shared_synthetic_site")
    build_site(synthetic_data_dir, site_dir)
    return site_dir
