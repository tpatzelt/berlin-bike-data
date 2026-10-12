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
    license_de: str
    license_en: str
    used_for_en: str
    used_for_de: str
    # Prose shown beside the bare URL, outside the break-anywhere URL span.
    url_note_de: str = ""
    url_note_en: str = ""


DATA_SOURCES: tuple[DataSource, ...] = (
    DataSource(
        name="nextbike Berlin GBFS 2.3",
        url="https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json",
        license_de="CC0-1.0",
        license_en="CC0-1.0",
        used_for_en=(
            "station_status, station_information, vehicle_types and "
            "free_bike_status availability snapshots (G1)"
        ),
        used_for_de="station_status-, station_information-, vehicle_types- und free_bike_status-Verfügbarkeits-Momentaufnahmen (G1)",
    ),
    DataSource(
        name="Dott Berlin GBFS",
        url="https://gbfs.api.ridedott.com/public/v2/berlin/gbfs.json",
        # The dott_berlin system_information fixture carries no license_id,
        # unlike nextbike's; this is the recorded assumption until Dott
        # publishes one (see T-0054 notes).
        license_de="siehe Nutzungsbedingungen des Betreibers",
        license_en="see operator terms",
        used_for_en="the same snapshot feeds as nextbike, as a second source behind the same interface (G1)",
        used_for_de="dieselben Momentaufnahme-Feeds wie bei nextbike, als zweite Quelle hinter derselben Schnittstelle (G1)",
    ),
    DataSource(
        name="Bright Sky / Deutscher Wetterdienst",
        url="https://api.brightsky.dev",
        license_de="Open Data des Deutschen Wetterdienstes",
        license_en="Deutscher Wetterdienst open data",
        used_for_en="hourly Berlin precipitation and temperature (G2)",
        used_for_de="stündlicher Niederschlag und Temperatur für Berlin (G2)",
    ),
    DataSource(
        name="Berlin Bezirk/Ortsteil polygons",
        url="https://gdi.berlin.de/services/wfs/alkis_ortsteile",
        url_note_de="Geoportal Berlin, ALKIS Bezirke und Ortsteile",
        url_note_en="Geoportal Berlin, ALKIS Bezirke and Ortsteile",
        license_de="Datenlizenz Deutschland - Zero - Version 2.0 (dl-de/zero-2-0)",
        license_en="Datenlizenz Deutschland - Zero - Version 2.0 (dl-de/zero-2-0)",
        used_for_en="mapping stations and grid cells to Bezirk and Ortsteil (G2)",
        used_for_de="Zuordnung von Stationen und Rasterzellen zu Bezirk und Ortsteil (G2)",
    ),
    DataSource(
        name="toddwschneider/nyc-citibike-data",
        url="https://github.com/toddwschneider/nyc-citibike-data",
        license_de="MIT",
        license_en="MIT",
        used_for_en="the upstream project this repository is forked from and adapts to Berlin",
        used_for_de="das Upstream-Projekt, von dem dieses Repository abgespalten ist und das es an Berlin anpasst",
    ),
)
