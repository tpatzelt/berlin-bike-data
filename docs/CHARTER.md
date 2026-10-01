# Wie Berlin radelt (How Berlin Rides)

Charter  (immutable — agents must not edit)

Fork of toddwschneider/nyc-citibike-data (MIT), adapted to Berlin. NYC publishes
historical trip CSVs; Berlin does not. Berlin's bike-sharing data is a live GBFS
snapshot feed, and bike ids rotate after every rental, so trips cannot be
reconstructed. This project therefore studies **availability**: where and when
bikes run out, how the city's daily rhythm moves bikes around, and what rain does
to it. It builds that history itself by collecting snapshots.

## Goals
- G1: A snapshot collector. A long-running process polls the nextbike Berlin GBFS 2.3
  feed (`https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json`, system
  `nextbike_bn`): `station_status` every 2 minutes, `station_information` and
  `vehicle_types` once a day, and `free_bike_status` every 2 minutes, aggregated
  on the fly to counts per grid cell (H3 resolution 8 or a 500 m grid, an ADR picks
  which). It writes append-only daily Parquet files under `BIKES_DATA_DIR`. It
  respects the feed's `ttl`, sends a descriptive User-Agent taken from config, backs
  off on errors, survives restarts without gaps or duplicate rows, and records feed
  outages as explicit gap rows instead of silently skipping them. The Dott Berlin
  feed (`https://gbfs.api.ridedott.com/public/v2/berlin/gbfs.json`) is a second
  source behind the same interface and is off by default.
- G2: Weather and geography joins. Hourly Berlin weather comes from the Bright Sky API
  (`api.brightsky.dev`, DWD open data), with the same caching and backoff as G1.
  Stations and grid cells are mapped to Bezirk and Ortsteil polygons from Berlin
  open data. These are committed as small GeoJSON files with their source and
  license noted in `data/SOURCES.md`, the way upstream ships NYC census tracts.
- G3: The analysis. DuckDB queries over the Parquet files produce the metrics behind
  every chart: bikes available by hour and weekday, citywide and per Bezirk; "empty
  station minutes" (a station with 0 bikes) ranked by station and Ortsteil, with the
  8:00 morning shortage as the headline; net flow between Bezirke inferred from
  station-level gains and losses by hour; availability on rainy versus dry hours,
  and cold versus warm hours; and the system's daily footprint (stations, bikes,
  e-bikes versus pedal bikes from `vehicle_types`). Every metric reports how many
  days of data it is based on and refuses to publish (it says "not enough data
  yet") below a minimum the charter sets at 14 full days.
- G4: The public site, in the spirit of Todd Schneider's write-ups. A static site is
  regenerated nightly from G3: one long-form, German+English article page with the
  charts and short text that updates its numbers automatically; an interactive map
  where you pick a station or Ortsteil and see its typical availability curve for
  each weekday ("will there be a bike at my station at 8:00 on Monday?"); and a
  methodology page that explains the snapshot approach, the rotating-id limitation
  and the data sources. Charts use Vega-Lite or plain SVG and a map library from a
  CDN, and no build step. The site is mobile-first, works at 360px width, and
  supports light and dark themes.
- G5: Deployable in Tim's homelab and ready for a Reddit post. A Dockerfile (non-root,
  healthcheck) runs the collector, the nightly rebuild and a static file server. Also
  required: `deploy/compose.yaml` and `deploy/.bikes.env.example` following the
  homelab conventions (external `caddy_network`, data at `/opt/dockerdata/bikes`,
  pinned base images, `env_file` secrets, no host ports); a GitHub Actions workflow
  that runs the tests and publishes `ghcr.io/tpatzelt/berlin-bike-data:latest` and
  `sha-<short>`; and a DEPLOY.md with the exact Caddy route and cloudflared ingress
  lines to add. Add an Impressum and a Datenschutzerklärung page with placeholders for
  Tim's details, and a draft r/berlin post in `docs/REDDIT_POST.md` (German and
  English) with the 3–4 strongest findings left as placeholders filled by G3.

## Non-goals
- No trip reconstruction, rider tracking or per-bike history. `bike_id` from
  `free_bike_status` is never written to disk, logged or used as a join key.
- No scraping of nextbike.de, the nextbike app API (`api.nextbike.net`) or any site.
  Only the published GBFS feeds, Bright Sky and Berlin open data files.
- No user accounts, notifications, payments, ads or analytics trackers.
- No other cities and no national bike-sharing comparison.
- No edits to the homelab repo. G5 produces files inside this repo only.
- Upstream NYC code (`*.sql`, `*.sh`, `*.rb`, `analysis/`, `nyct2010_15b/`,
  `taxi_zones/`) moves unchanged into `upstream-nyc/`. It is not rewritten, ported or
  deleted. `LICENSE` keeps Todd W. Schneider's copyright, and the README credits the
  original and says what changed.
- No reformatting or restructuring not required by a specific task.

## Constraints
- Python >= 3.12, uv: `uv sync`, `uv run pytest -q`. Dependencies are allowed but must
  be justified in the commit message. Prefer stdlib + httpx + duckdb + pyarrow +
  jinja2, plus h3 or shapely only if G1/G2 need them.
- Berlin code lives under `src/berlinbikes/`. Generated site output goes to
  `BIKES_SITE_DIR` and is never committed.
- `uv run pytest -q` must stay green and fully offline. HTTP is replayed from fixtures
  under `tests/fixtures/**`, and a test that touches the network is a failing test.
  Analysis tests run on a synthetic multi-week Parquet dataset generated by a
  seeded fixture builder, with known answers (for example a station that is
  scripted to be empty every weekday 7:45–8:30).
- The sandbox has open egress. Live calls are allowed only to the two GBFS hosts above
  and `api.brightsky.dev`, only to learn real response shapes and record fixtures, a
  handful of requests per task, and never in a loop. Do not run the collector
  against the live feed during the run; it runs in the homelab after deploy.
- No secrets, tokens, real domains, LAN IPs or personal data in the repository.
  Configuration comes from environment variables documented in `.bikes.env.example`.
- Times are stored in UTC and presented in Europe/Berlin. DST transitions are tested
  (the 25-hour and 23-hour days must not double-count or drop an hour).
- Storage budget: one day of collected data must fit in under 50 MB of Parquet
  (tested against the fixture builder at real Berlin scale: about 1,050 stations and
  about 5,500 bikes per snapshot, at 720 snapshots a day).

## Definition of done per goal
- G1: Against recorded fixtures, the collector writes the expected Parquet rows. A test
  simulates a restart mid-day and proves there are no duplicates and no gap. A test
  simulates a feed outage and proves gap rows are written and backoff is applied. A
  test proves no `bike_id` reaches disk. The Dott source passes the same tests behind
  the interface.
- G2: Weather joins are correct across a DST boundary (tested). Every Berlin station in
  the recorded `station_information` fixture maps to exactly one Bezirk and Ortsteil,
  and a test lists any station that falls outside the polygons.
- G3: Each metric has a table-driven test against the synthetic dataset with known
  expected values. The "not enough data yet" guard is tested at 13 and 14 days.
- G4: The site generator renders all pages from the synthetic dataset. An
  HTML-structure test covers the 360px layout (viewport meta, no fixed widths) and
  theme tokens. Every chart has a text or table fallback (an accessibility test
  checks it). The methodology page names every data source and license.
- G5: `docker build .` succeeds, and the container answers its healthcheck in a test or
  script run inside the sandbox. `docker compose -f deploy/compose.yaml config`
  validates with the example env. The workflow file is valid YAML. DEPLOY.md lists
  every step, including how long to collect before posting (at least 14 days, 28
  recommended). The legal pages exist and are linked in the footer.

## Priority order
G1 > G3 > G2 > G4 > G5

## Allowed idle work (when the backlog is empty)
Tests, fixtures, documentation, accessibility, chart clarity and small refactors
strictly within G1–G5. Nothing new.

## Projects
- repo: berlin-bike-data   goals: [G1, G2, G3, G4, G5]   test_cmd: "uv run pytest -q"
