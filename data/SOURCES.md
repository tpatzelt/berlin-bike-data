# Data sources

Files in `data/` that the Berlin code reads. (`*.csv` at the top level belong to the
upstream NYC project and are not used.)

| File | Source | License |
|---|---|---|
| `geo/bezirke.geojson` | Geoportal Berlin, ALKIS Bezirke, WFS `https://gdi.berlin.de/services/wfs/alkis_bezirke` (layer `bezirksgrenzen`) | [Datenlizenz Deutschland – Zero – Version 2.0](https://www.govdata.de/dl-de/zero-2-0) |
| `geo/ortsteile.geojson` | Geoportal Berlin, ALKIS Ortsteile, WFS `https://gdi.berlin.de/services/wfs/alkis_ortsteile` (layer `ortsteile`) | [Datenlizenz Deutschland – Zero – Version 2.0](https://www.govdata.de/dl-de/zero-2-0) |

Both were fetched with `uv run python scripts/fetch_berlin_areas.py` on 2026-10-03,
reprojected to WGS84 (EPSG:4326) by the WFS, and reduced to a `name` property (plus
`bezirk` on each Ortsteil). Coordinates are rounded to 5 decimals (about 1 m).

Live sources fetched at runtime (not committed): the nextbike Berlin GBFS feed
(CC0-1.0), optionally the Dott Berlin GBFS feed, and hourly weather from Bright Sky
(`api.brightsky.dev`, Deutscher Wetterdienst open data). The methodology page on the
site lists all of them.
