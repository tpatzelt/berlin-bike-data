"""Command-line entry point: ``python -m berlinbikes``.

Argument parsing happens before any ``Settings`` is built, so ``--help``
works with no environment variables set.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from types import FrameType

from berlinbikes.backoff import SystemClock
from berlinbikes.collector import Collector
from berlinbikes.config import Settings
from berlinbikes.gbfs import GbfsClient
from berlinbikes.sources import NextbikeSource
from berlinbikes.storage import Storage

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="berlinbikes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("collect", help="Run the snapshot collector loop")
    return parser


def run_collect() -> None:
    settings = Settings.from_env()
    clock = SystemClock()
    source = NextbikeSource(settings)
    client = GbfsClient(source.gbfs_url, settings.user_agent, clock=clock)
    storage = Storage(settings.data_dir)
    collector = Collector(source, client, storage, clock)

    stop = threading.Event()

    def _handle_signal(signum: int, frame: FrameType | None) -> None:
        logger.info("received signal %s, stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    collector.run(stop=stop)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "collect":
        run_collect()


if __name__ == "__main__":
    main()
