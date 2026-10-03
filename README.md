# Wie Berlin radelt (How Berlin Rides)

Where and when do Berlin's shared bikes run out? This project collects snapshots of
the nextbike Berlin bike-share system every two minutes and turns them into a
nightly-updated, German and English write-up with charts, an interactive map ("will
there be a bike at my station at 8:00 on Monday?") and a methodology page.

It is a fork of Todd Schneider's
[nyc-citibike-data](https://github.com/toddwschneider/nyc-citibike-data), adapted to
Berlin. NYC publishes historical trip files; Berlin does not. Berlin's data is a live
[GBFS](https://gbfs.org/) feed, and bike ids rotate after every rental, so trips cannot
be reconstructed. The project therefore studies **availability**, not trips, and
builds its own history by collecting snapshots. **Bike ids are never written to disk,
logged or used as a join key.**

## What it does

- **Collector**: polls the nextbike Berlin GBFS 2.3 feed (`station_status` and
  `free_bike_status` every 2 minutes, `station_information` and `vehicle_types` daily),
  respects the feed's `ttl`, backs off on errors, survives restarts without gaps or
  duplicates, records outages as explicit gap rows, and writes append-only daily
  Parquet files. Free-floating bikes are aggregated to H3 cells on the fly. A Dott
  Berlin source sits behind the same interface and is off by default.
- **Joins**: hourly Berlin weather from [Bright Sky](https://brightsky.dev/) (DWD open
  data); stations mapped to Bezirk and Ortsteil polygons from Berlin's Geoportal
  (`data/geo/`, see [data/SOURCES.md](data/SOURCES.md)).
- **Analysis**: DuckDB over the Parquet files: availability by hour and weekday,
  citywide and per Bezirk; empty-station minutes with the 8:00 morning shortage as the
  headline; net flow between Bezirke; rain and cold effects; the daily system
  footprint; per-station and per-Ortsteil curves for the map. Every metric reports how
  many days it is based on and says "not enough data yet" below 14 full days.
- **Site**: static HTML, plain SVG charts with table fallbacks, Leaflet map, no build
  step, mobile-first, light and dark.

## Run it

Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest -q                     # fully offline

cp deploy/.bikes.env.example .bikes.env   # then edit
set -a; . ./.bikes.env; set +a

uv run python -m berlinbikes collect      # snapshot collector loop
uv run python -m berlinbikes weather      # backfill Bright Sky weather
uv run python -m berlinbikes build-site   # render the site into BIKES_SITE_DIR
uv run python -m berlinbikes nightly      # weather backfill, then site build
uv run python -m berlinbikes serve        # all of the above + static server on :8080
```

Configuration is environment variables only, documented in
[deploy/.bikes.env.example](deploy/.bikes.env.example). Deployment (Docker image,
compose file, reverse proxy) is described in [DEPLOY.md](DEPLOY.md).

## Credits

This project is built on Todd W. Schneider's
[nyc-citibike-data](https://github.com/toddwschneider/nyc-citibike-data) and his post
["A Tale of Twenty-Two Million Citi Bike Rides"](https://toddwschneider.com/posts/a-tale-of-twenty-two-million-citi-bikes-analyzing-the-nyc-bike-share-system/).
It is MIT licensed, and [LICENSE](LICENSE) keeps his copyright.

What changed:

- Berlin GBFS availability snapshots instead of NYC trip CSVs.
- Python, DuckDB and Parquet instead of PostgreSQL/PostGIS and R.
- A static, self-updating website instead of a one-off analysis.
- The original NYC code is preserved unchanged in [upstream-nyc/](upstream-nyc/),
  with its README.
