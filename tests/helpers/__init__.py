"""Shared test helpers for replaying recorded GBFS fixtures over httpx.

Reused by the collector poll tests and later by the run-loop, backoff and
Dott tests: every one of them needs the same "serve the committed fixture
file matching the request's feed name" transport, just with different
per-feed overrides for the error cases they're testing.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures" / "gbfs"


def load_fixture(source: str, feed_name: str) -> dict:
    path = FIXTURES_ROOT / source / f"{feed_name}.json"
    return json.loads(path.read_text())


def fixture_replay_transport(
    source: str, overrides: dict[str, httpx.Response] | None = None
) -> httpx.MockTransport:
    """A MockTransport serving the committed fixtures for ``source``.

    Requests are matched by their final path segment (the feed name,
    without ``.json``). ``overrides`` substitutes a canned
    ``httpx.Response`` for specific feed names, for tests that need an
    error or a modified payload instead of the recorded one.
    """
    overrides = overrides or {}

    def handler(request: httpx.Request) -> httpx.Response:
        feed_name = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        if feed_name in overrides:
            return overrides[feed_name]
        return httpx.Response(200, json=load_fixture(source, feed_name))

    return httpx.MockTransport(handler)
