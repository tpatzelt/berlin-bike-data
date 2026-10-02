"""Source protocol and the nextbike_bn source definition.

A ``Source`` is just the identity and feed list a :class:`Collector` needs
to poll a GBFS root; it carries no HTTP state (that lives in
``GbfsClient``), so adding a second provider like Dott means adding another
small class behind this same protocol.
"""

from __future__ import annotations

from typing import Protocol

from berlinbikes.config import Settings
from berlinbikes.gbfs import REQUIRED_FEEDS


class Source(Protocol):
    name: str
    gbfs_url: str
    feeds: tuple[str, ...]


class NextbikeSource:
    name = "nextbike_bn"
    feeds = REQUIRED_FEEDS

    def __init__(self, settings: Settings) -> None:
        self.gbfs_url = settings.nextbike_gbfs_url


class DottSource:
    name = "dott_berlin"
    feeds = REQUIRED_FEEDS

    def __init__(self, settings: Settings) -> None:
        self.gbfs_url = settings.dott_gbfs_url


def enabled_sources(settings: Settings) -> list[Source]:
    """The sources a collector should poll: nextbike always, Dott when enabled."""
    sources: list[Source] = [NextbikeSource(settings)]
    if settings.dott_enabled:
        sources.append(DottSource(settings))
    return sources
