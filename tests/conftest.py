"""Shared test fixtures.

An autouse fixture blocks real network access so ``uv run pytest -q`` can
never depend on, or accidentally hit, a live feed.
"""

import socket

import pytest


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
