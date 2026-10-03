"""Tests for berlinbikes.serve: rebuild scheduling, /healthz routing and the
static handler. Fully offline: the handler is driven through a fake socket,
never a real server (the conftest guard blocks every connect).
"""

from __future__ import annotations

import io
import threading
from datetime import datetime, timezone
from functools import partial

from berlinbikes.serve import SiteHandler, next_rebuild_at, rebuild_loop, route

UTC = timezone.utc


def test_next_rebuild_on_an_ordinary_summer_day():
    # 03:30 CEST = 01:30 UTC
    assert next_rebuild_at(datetime(2026, 7, 1, 0, 0, tzinfo=UTC)) == datetime(2026, 7, 1, 1, 30, tzinfo=UTC)
    assert next_rebuild_at(datetime(2026, 7, 1, 1, 30, tzinfo=UTC)) == datetime(2026, 7, 2, 1, 30, tzinfo=UTC)


def test_next_rebuild_on_an_ordinary_winter_day():
    # 03:30 CET = 02:30 UTC
    assert next_rebuild_at(datetime(2026, 1, 10, 12, 0, tzinfo=UTC)) == datetime(2026, 1, 11, 2, 30, tzinfo=UTC)


def test_next_rebuild_on_the_23_hour_day():
    # 2026-03-29: clocks jump 02:00 CET -> 03:00 CEST, so 03:30 is CEST = 01:30 UTC
    assert next_rebuild_at(datetime(2026, 3, 28, 23, 0, tzinfo=UTC)) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)


def test_next_rebuild_on_the_25_hour_day():
    # 2026-10-25: clocks fall back 03:00 CEST -> 02:00 CET, so 03:30 is CET = 02:30 UTC
    assert next_rebuild_at(datetime(2026, 10, 25, 0, 0, tzinfo=UTC)) == datetime(2026, 10, 25, 2, 30, tzinfo=UTC)


def test_route_healthz():
    assert route("/healthz", healthy=True) == (200, b"ok")
    assert route("/healthz?x=1", healthy=False) == (503, b"collector down")
    assert route("/index.html", healthy=True) is None


class _FakeSocket:
    def __init__(self, request: bytes) -> None:
        self._rfile = io.BytesIO(request)
        self.wfile = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        return self._rfile if "r" in mode else _KeepOpen(self.wfile)

    def sendall(self, data):  # used by some Python versions' wfile
        self.wfile.write(data)


class _KeepOpen(io.RawIOBase):
    def __init__(self, target: io.BytesIO) -> None:
        self._target = target

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        return self._target.write(b)


def _get(path: str, site_dir, healthy: bool = True) -> bytes:
    sock = _FakeSocket(f"GET {path} HTTP/1.1\r\nHost: test\r\n\r\n".encode())
    handler = partial(SiteHandler, directory=str(site_dir), health=lambda: healthy)
    handler(sock, ("127.0.0.1", 1234), server=None)
    return sock.wfile.getvalue()


def test_handler_serves_healthz_and_static_files(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Wie Berlin radelt</h1>")

    healthy = _get("/healthz", tmp_path)
    assert healthy.startswith(b"HTTP/1.0 200") and healthy.endswith(b"ok")

    assert _get("/healthz", tmp_path, healthy=False).startswith(b"HTTP/1.0 503")

    page = _get("/index.html", tmp_path)
    assert page.startswith(b"HTTP/1.0 200")
    assert page.endswith(b"<h1>Wie Berlin radelt</h1>")


def test_rebuild_loop_runs_at_0330_and_survives_a_failing_rebuild():
    stop = threading.Event()
    times = iter(
        [
            # first pass: now -> due 01:30 UTC; the wait elapses, rebuild raises
            datetime(2026, 7, 1, 1, 29, 59, tzinfo=UTC),
            datetime(2026, 7, 1, 1, 29, 59, 999000, tzinfo=UTC),
            # second pass: next night, the rebuild succeeds and stops the loop
            datetime(2026, 7, 2, 1, 29, 59, 999000, tzinfo=UTC),
            datetime(2026, 7, 2, 1, 29, 59, 999000, tzinfo=UTC),
        ]
    )
    calls = []

    def rebuild():
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("bright sky down")
        stop.set()

    rebuild_loop(stop, now=lambda: next(times), rebuild=rebuild)
    assert calls == [0, 1]
