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
