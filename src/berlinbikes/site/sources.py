"""Single source of truth for every upstream data source and its license.

The G4 methodology page renders :data:`DATA_SOURCES` so the charter's
definition of done ("names every data source and license") stays true even
as sources are added or a pending license is filled in.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataSource:
    name: str
    url: str
    license: str
    used_for: str


DATA_SOURCES: tuple[DataSource, ...] = (
    DataSource(
        name="nextbike Berlin GBFS 2.3",
        url="https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json",
        license="CC0-1.0",
        used_for=(
            "station_status, station_information, vehicle_types and "
            "free_bike_status availability snapshots (G1)"
        ),
    ),
    DataSource(
        name="Dott Berlin GBFS",
        url="https://gbfs.api.ridedott.com/public/v2/berlin/gbfs.json",
        # The dott_berlin system_information fixture carries no license_id,
        # unlike nextbike's; this is the recorded assumption until Dott
        # publishes one (see T-0054 notes).
        license="see operator terms",
        used_for="the same snapshot feeds as nextbike, as a second source behind the same interface (G1)",
    ),
    DataSource(
        name="Bright Sky / Deutscher Wetterdienst",
        url="https://api.brightsky.dev",
        license="Deutscher Wetterdienst open data",
        used_for="hourly Berlin precipitation and temperature (G2)",
    ),
    DataSource(
        name="Berlin Bezirk/Ortsteil polygons",
        url="https://gdi.berlin.de/services/wfs/alkis_ortsteile (Geoportal Berlin, ALKIS Bezirke and Ortsteile)",
        license="Datenlizenz Deutschland - Zero - Version 2.0 (dl-de/zero-2-0)",
        used_for="mapping stations and grid cells to Bezirk and Ortsteil (G2)",
    ),
    DataSource(
        name="toddwschneider/nyc-citibike-data",
        url="GitHub: toddwschneider/nyc-citibike-data",
        license="MIT",
        used_for="the upstream project this repository is forked from and adapts to Berlin",
    ),
)
