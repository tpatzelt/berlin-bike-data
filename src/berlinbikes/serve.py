"""``python -m berlinbikes serve``: everything the container runs, in one process.

- the snapshot collector, one supervised thread per enabled source;
- the nightly rebuild (weather backfill, then site build) at 03:30
  Europe/Berlin, plus one site build at startup so the site is never empty;
- a stdlib static file server for ``BIKES_SITE_DIR`` on port 8080, with
  ``/healthz`` answering 200 while every collector thread is alive and 503
  otherwise.

Port 8080 and the 03:30 rebuild time are fixed choices, not configuration.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
REBUILD_AT = time(3, 30)
DEFAULT_PORT = 8080


def next_rebuild_at(now_utc: datetime, clock_time: time = REBUILD_AT, tz: ZoneInfo = BERLIN) -> datetime:
    """The first UTC instant strictly after ``now_utc`` whose local time is ``clock_time``.

    03:30 exists exactly once on both DST days in Europe/Berlin (the jumps are
    at 02:00 and 03:00), so building the local wall time and converting is
    enough.
    """
    local_now = now_utc.astimezone(tz)
    for days in range(3):
        candidate = datetime.combine(local_now.date() + timedelta(days=days), clock_time, tzinfo=tz)
        candidate_utc = candidate.astimezone(timezone.utc)
        if candidate_utc > now_utc:
            return candidate_utc
    raise AssertionError("unreachable: a later 03:30 always exists within two days")


def route(path: str, healthy: bool) -> tuple[int, bytes] | None:
    """Status and body for the routes the handler answers itself, or ``None``
    to fall through to static files from the site directory.
    """
    if path.split("?", 1)[0] == "/healthz":
        return (200, b"ok") if healthy else (503, b"collector down")
    return None


class SiteHandler(SimpleHTTPRequestHandler):
    """Serves ``directory`` and ``/healthz``. ``health`` is set via ``partial``."""

    health: Callable[[], bool] = staticmethod(lambda: True)

    def __init__(self, *args, health: Callable[[], bool] | None = None, **kwargs) -> None:
        if health is not None:
            self.health = health
        super().__init__(*args, **kwargs)

    def _own_route(self) -> bool:
        answer = route(self.path, self.health())
        if answer is None:
            return False
        status, body = answer
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return True

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        if not self._own_route():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if not self._own_route():
            super().do_HEAD()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Healthchecks every 30 s would drown the log; visitor IPs are not logged at all.
        pass


def rebuild_loop(
    stop: threading.Event,
    now: Callable[[], datetime],
    rebuild: Callable[[], object],
) -> None:
    """Call ``rebuild`` at every :func:`next_rebuild_at` until ``stop`` is set.

    A failing rebuild is logged and the loop carries on to the next night.
    """
    while not stop.is_set():
        due = next_rebuild_at(now())
        wait_s = (due - now()).total_seconds()
        if stop.wait(max(wait_s, 0.0)):
            return
        try:
            rebuild()
        except Exception:
            logger.exception("nightly rebuild failed")


def serve(
    site_dir: str,
    collector_threads: list[threading.Thread],
    initial_build: Callable[[], object],
    nightly: Callable[[], object],
    now: Callable[[], datetime],
    stop: threading.Event,
    port: int = DEFAULT_PORT,
) -> None:
    """Start the collectors, build once, then serve and rebuild nightly until ``stop``."""
    for thread in collector_threads:
        thread.start()

    try:
        initial_build()
    except Exception:
        logger.exception("startup site build failed; serving whatever is in %s", site_dir)

    rebuilder = threading.Thread(target=rebuild_loop, args=(stop, now, nightly), name="nightly", daemon=True)
    rebuilder.start()

    def healthy() -> bool:
        return all(thread.is_alive() for thread in collector_threads)

    handler = partial(SiteHandler, directory=site_dir, health=healthy)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    server_thread.start()
    logger.info("serving %s on :%d", site_dir, port)

    stop.wait()
    server.shutdown()
    server.server_close()
    for thread in collector_threads:
        thread.join(timeout=30)
