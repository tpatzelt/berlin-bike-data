# syntax=docker/dockerfile:1

# uv, pinned by a version tag (not a digest).
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv

# Matches .python-version.
FROM python:3.14.7-slim-bookworm

COPY --from=uv /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BIKES_DATA_DIR=/data/parquet \
    BIKES_SITE_DIR=/data/site

WORKDIR /app

COPY pyproject.toml uv.lock README.md .python-version ./
COPY src ./src
# Bezirk/Ortsteil polygons, read by berlinbikes.areas at /app/data/geo.
COPY data/geo ./data/geo

# --locked fails the build if uv.lock is stale; --no-dev keeps pytest out.
RUN uv sync --locked --no-dev

RUN groupadd --gid 10001 bikes \
    && useradd --uid 10001 --gid bikes --system --home-dir /app --shell /usr/sbin/nologin bikes \
    && mkdir -p /data \
    && chown -R bikes:bikes /data

USER 10001

VOLUME /data
EXPOSE 8080

# start-period covers the startup site build, which runs before the server binds.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=3 \
    CMD /app/.venv/bin/python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"

# The venv binary directly, not `uv run`, which would re-sync on every start.
CMD ["/app/.venv/bin/python", "-m", "berlinbikes", "serve"]
