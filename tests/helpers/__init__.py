"""Shared test helpers for replaying recorded GBFS fixtures over httpx.

Reused by the collector poll tests and later by the run-loop, backoff and
Dott tests: every one of them needs the same "serve the committed fixture
file matching the request's feed name" transport, just with different
per-feed overrides for the error cases they're testing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Union

import httpx

from berlinbikes.config import Settings

if TYPE_CHECKING:
    from berlinbikes.backoff import Clock
    from berlinbikes.collector import Collector

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures" / "gbfs"

#: A per-feed override: either a canned response, or a callable that gets
#: the request and the number of prior requests for that feed (0 on the
#: first call), for tests that need responses to change over time (for
#: example: succeed once, then fail on every later call).
FeedOverride = Union[httpx.Response, Callable[[httpx.Request, int], httpx.Response]]


def load_fixture(source: str, feed_name: str) -> dict:
    path = FIXTURES_ROOT / source / f"{feed_name}.json"
    return json.loads(path.read_text())


def fixture_replay_transport(
    source: str, overrides: dict[str, FeedOverride] | None = None
) -> httpx.MockTransport:
    """A MockTransport serving the committed fixtures for ``source``.

    Requests are matched by their final path segment (the feed name,
    without ``.json``). ``overrides`` substitutes a canned ``httpx.Response``
    or a ``(request, call_count) -> httpx.Response`` callable for specific
    feed names, for tests that need an error, a modified payload, or a
    response that changes across calls instead of the recorded one.
    """
    overrides = overrides or {}
    call_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        feed_name = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        call_count = call_counts.get(feed_name, 0)
        call_counts[feed_name] = call_count + 1

        override = overrides.get(feed_name)
        if override is not None:
            if callable(override):
                return override(request, call_count)
            return override
        return httpx.Response(200, json=load_fixture(source, feed_name))

    return httpx.MockTransport(handler)


@dataclass
class StubSource:
    """A minimal Source stub for tests that want to poll fewer than all four feeds."""

    name: str
    gbfs_url: str
    feeds: tuple[str, ...]


def make_settings(tmp_path) -> Settings:
    return Settings.from_env(
        {
            "BIKES_DATA_DIR": str(tmp_path),
            "BIKES_USER_AGENT": "berlinbikes-test/1.0",
        }
    )


def make_collector(
    tmp_path,
    source,
    transport: httpx.BaseTransport,
    clock: "Clock",
) -> "Collector":
    """A Collector wired to a fixture-replay transport and the given clock."""
    from berlinbikes.collector import Collector
    from berlinbikes.gbfs import GbfsClient
    from berlinbikes.storage import Storage

    settings = make_settings(tmp_path)
    client = GbfsClient(source.gbfs_url, settings.user_agent, transport=transport, clock=clock)
    storage = Storage(tmp_path)
    return Collector(source, client, storage, clock)
