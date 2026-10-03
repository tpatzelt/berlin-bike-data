"""Command-line entry point: ``python -m berlinbikes``.

Argument parsing happens before any ``Settings`` is built, so ``--help``
works with no environment variables set.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from types import FrameType
from typing import Sequence

import httpx

from berlinbikes.backoff import Clock, SystemClock
from berlinbikes.collector import Collector
from berlinbikes.config import Settings
from berlinbikes.gbfs import GbfsClient
from berlinbikes.sources import enabled_sources
from berlinbikes.storage import Storage
from berlinbikes.weather import WeatherCache, WeatherClient

logger = logging.getLogger(__name__)

#: How long the supervisor waits, via ``stop.wait`` rather than a blind
#: sleep, before restarting a source whose collector loop raised. A plain
#: ``time.sleep`` here would make shutdown wait out the whole delay even
#: though ``stop`` was already set.
RESTART_DELAY_S = 120.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="berlinbikes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("collect", help="Run the snapshot collector loop")
    weather_parser = subparsers.add_parser(
        "weather", help="Fill missing Bright Sky weather days into the cache"
    )
    weather_parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="How many days back from today to backfill (default: 7)",
    )
    return parser


def build_collectors(settings: Settings, clock: Clock) -> list[Collector]:
    """One Collector per enabled source, each with its own GbfsClient but
    sharing one Storage (partitioned by source name, so concurrent writers
    from different sources never collide).
    """
    storage = Storage(settings.data_dir)
    collectors = []
    for source in enabled_sources(settings):
        client = GbfsClient(source.gbfs_url, settings.user_agent, clock=clock)
        collectors.append(Collector(source, client, storage, clock))
    return collectors


def _supervise(collector: Collector, stop: threading.Event, restart_delay_s: float) -> None:
    """Run one Collector forever, restarting it after a crash.

    Decided behaviour (ADR-style): if ``Collector.run`` raises, this logs the
    exception (source name only, never feed payloads) with
    ``logger.exception``, waits ``restart_delay_s`` via ``stop.wait`` so a
    shutdown request cuts the wait short, and calls ``run`` again on the same
    Collector. This repeats until ``stop`` is set. A crash in one source's
    loop therefore never stops, or blocks writes from, any other source's
    thread.
    """
    while not stop.is_set():
        try:
            collector.run(stop=stop)
        except Exception:
            logger.exception("source %s: collector loop crashed, restarting", collector.source.name)
            stop.wait(restart_delay_s)


def run_sources(
    collectors: Sequence[Collector],
    stop: threading.Event,
    restart_delay_s: float = RESTART_DELAY_S,
) -> None:
    """Poll every collector concurrently, each in its own thread, isolated
    from the others, until ``stop`` is set.
    """
    threads = [
        threading.Thread(
            target=_supervise,
            args=(collector, stop, restart_delay_s),
            name=f"collector-{collector.source.name}",
        )
        for collector in collectors
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def run_collect() -> None:
    settings = Settings.from_env()
    clock = SystemClock()
    collectors = build_collectors(settings, clock)

    stop = threading.Event()

    def _handle_signal(signum: int, frame: FrameType | None) -> None:
        logger.info("received signal %s, stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    run_sources(collectors, stop)


def run_weather(
    settings: Settings,
    clock: Clock,
    days_back: int = 7,
    transport: httpx.BaseTransport | None = None,
    max_rounds: int = 5,
) -> int:
    """Fill missing days into the weather cache, retrying with backoff.

    Each round calls ``WeatherCache.collect_missing``, which returns ``None``
    once every day in range is cached, or a delay to sleep (via ``clock``)
    before the next round. After ``max_rounds`` rounds without catching up,
    this gives up and returns 1 so the nightly rebuild can flag it.
    """
    client = WeatherClient(settings.user_agent, transport=transport, clock=clock)
    cache = WeatherCache(settings.data_dir, client, clock)
    for _ in range(max_rounds):
        delay = cache.collect_missing(days_back)
        if delay is None:
            return 0
        clock.sleep(delay)
    logger.warning("weather: giving up after %d rounds, cache still incomplete", max_rounds)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "collect":
        run_collect()
        return 0
    if args.command == "weather":
        settings = Settings.from_env()
        clock = SystemClock()
        return run_weather(settings, clock, days_back=args.days_back)
    return 0


if __name__ == "__main__":
    sys.exit(main())
