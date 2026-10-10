"""String catalog for the site shell: every key carries both languages."""

from __future__ import annotations

from markupsafe import Markup

LANGS = ("de", "en")

STRINGS: dict[str, dict[str, str]] = {
    "site.title": {"de": "Wie Berlin radelt", "en": "How Berlin Rides"},
    "nav.label": {"de": "Hauptnavigation", "en": "Main navigation"},
    "nav.home": {"de": "Start", "en": "Home"},
    "nav.map": {"de": "Karte", "en": "Map"},
    "nav.methodology": {"de": "Methodik", "en": "Methodology"},
    "nav.impressum": {"de": "Impressum", "en": "Legal notice"},
    "nav.privacy": {"de": "Datenschutz", "en": "Privacy"},
    "lang.switch": {"de": "English", "en": "Deutsch"},
    "title.index": {"de": "Wie Berlin radelt", "en": "How Berlin Rides"},
    "title.map": {"de": "Karte – Wie Berlin radelt", "en": "Map – How Berlin Rides"},
    "title.methodology": {"de": "Methodik", "en": "Methodology"},
    "title.impressum": {"de": "Impressum", "en": "Legal notice"},
    "title.datenschutz": {"de": "Datenschutzerklärung", "en": "Privacy policy"},
    "common.show_table": {"de": "Werte als Tabelle anzeigen", "en": "Show values as a table"},
    "common.not_enough_data": {"de": "noch nicht genug Daten", "en": "not enough data yet"},
    "common.table.day": {"de": "Tag", "en": "Day"},
    "common.table.station": {"de": "Station", "en": "Station"},
    "common.table.min_per_day": {"de": "Min./Tag", "en": "Min/day"},
    "weekday.short.0": {"de": "Mo", "en": "Mon"},
    "weekday.short.1": {"de": "Di", "en": "Tue"},
    "weekday.short.2": {"de": "Mi", "en": "Wed"},
    "weekday.short.3": {"de": "Do", "en": "Thu"},
    "weekday.short.4": {"de": "Fr", "en": "Fri"},
    "weekday.short.5": {"de": "Sa", "en": "Sat"},
    "weekday.short.6": {"de": "So", "en": "Sun"},
    "availability.heading": {"de": "Verfügbarkeit in Berlin", "en": "Availability in Berlin"},
    "availability.intro": {
        "de": "Mittlere Anzahl verfügbarer Räder in Berlin, je Wochentag und Uhrzeit (Europe/Berlin).",
        "en": "Mean number of bikes available citywide, by weekday and local hour (Europe/Berlin).",
    },
    "availability.aria": {
        "de": "Mittlere Anzahl verfügbarer Räder in Berlin je Wochentag und Uhrzeit (0-23 Uhr, Europe/Berlin)",
        "en": "Mean bikes available in Berlin by weekday and local hour (0-23, Europe/Berlin)",
    },
    "availability.caption": {
        "de": "Verfügbare Räder je Uhrzeit (0–23 Uhr, Europe/Berlin) und Wochentag (Mo–So), auf Basis von {full_days} vollen Tagen.",
        "en": "Bikes available by local hour (0–23, Europe/Berlin) and weekday (Mon–Sun), based on {full_days} full days.",
    },
    "availability.table.caption": {
        "de": "Verfügbare Räder je Wochentag und Uhrzeit",
        "en": "Bikes available by weekday and local hour",
    },
    "shortage.heading": {"de": "Der Morgen-Engpass um 8 Uhr", "en": "The 8am morning shortage"},
    "shortage.summary": {
        "de": "An Wochentagen waren um 8:00 Uhr durchschnittlich {share_pct}% der Stationen leer.",
        "en": "On weekdays, an average of {share_pct}% of stations were empty at 8:00.",
    },
    "shortage.aria": {
        "de": "Leerstehende Stationen am Morgen, Mo-Fr 7:30-8:30 Uhr, Top {n}",
        "en": "Stations empty in the morning, Mon-Fri 7:30-8:30, top {n}",
    },
    "shortage.caption": {
        "de": "Stationen mit den meisten leeren Minuten pro Tag im Morgenfenster (Mo–Fr 7:30–8:30 Uhr), auf Basis von {full_days} vollen Tagen.",
        "en": "Stations with the most empty minutes per day in the morning window (Mon–Fri 7:30–8:30), based on {full_days} full days.",
    },
    "shortage.table.caption": {
        "de": "Leere Minuten pro Tag im Morgenfenster, nach Station",
        "en": "Empty minutes per day in the morning window, by station",
    },
    "bezirke.heading": {"de": "Verfügbarkeit je Bezirk", "en": "Availability by Bezirk"},
    "bezirke.intro": {
        "de": "Mittlere Anzahl verfügbarer Räder je Bezirk, Mo-Fr, nach Uhrzeit (Europe/Berlin).",
        "en": "Mean number of bikes available by Bezirk, Mon-Fri, by local hour (Europe/Berlin).",
    },
    "bezirke.aria": {
        "de": "Mittlere Anzahl verfügbarer Räder je Bezirk, Mo-Fr, nach Uhrzeit (0-23 Uhr, Europe/Berlin)",
        "en": "Mean bikes available by Bezirk, Mon-Fri, by local hour (0-23, Europe/Berlin)",
    },
    "bezirke.caption": {
        "de": "Verfügbare Räder je Bezirk, Mo-Fr, je Uhrzeit (0–23 Uhr, Europe/Berlin), auf Basis von {full_days} vollen Tagen.",
        "en": "Bikes available by Bezirk, Mon-Fri, by local hour (0–23, Europe/Berlin), based on {full_days} full days.",
    },
    "bezirke.table.caption": {
        "de": "Verfügbare Räder je Bezirk und Uhrzeit (Mo-Fr)",
        "en": "Bikes available by Bezirk and local hour (Mo-Fr)",
    },
    "flow.heading": {"de": "Netto-Fluss zwischen Bezirken", "en": "Net flow between Bezirke"},
    "flow.intro": {
        "de": "Netto gewonnene oder verlorene Räder je Bezirk und Uhrzeit, Mo-Fr im Mittel pro Tag (Europe/Berlin).",
        "en": "Net bikes gained or lost per Bezirk by local hour, Mon-Fri mean per day (Europe/Berlin).",
    },
    "flow.aria": {
        "de": "Räder gewonnen/verloren je Bezirk und Uhrzeit (0-23 Uhr, Mo-Fr im Mittel pro Tag, Europe/Berlin)",
        "en": "Bikes gained/lost per Bezirk by local hour (0-23, Mon-Fri mean per day, Europe/Berlin)",
    },
    "flow.caption": {
        "de": "Räder gewonnen (+) / verloren (-) je Bezirk und Uhrzeit (0–23 Uhr, Europe/Berlin), Mo-Fr im Mittel pro Tag, auf Basis von {full_days} vollen Tagen.",
        "en": "Bikes gained (+) / lost (-) per Bezirk by local hour (0–23, Europe/Berlin), Mon-Fri mean per day, based on {full_days} full days.",
    },
    "flow.table.caption": {
        "de": "Netto gewonnene/verlorene Räder je Bezirk und Uhrzeit (Mo-Fr)",
        "en": "Net bikes gained/lost per Bezirk by local hour (Mo-Fr)",
    },
    "weather.heading": {"de": "Verfügbarkeit bei Regen und Kälte", "en": "Availability on rainy and cold hours"},
    "weather.intro": {
        "de": "Anteil leerer Stationen je Uhrzeit, bei Regen (&ge; {rain} mm/h) im Vergleich zu trocken, und bei Kälte (&lt; {cold} °C) im Vergleich zu warm (Europe/Berlin).",
        "en": "Share of empty stations by local hour, rainy (&ge; {rain} mm/h) versus dry, and cold (&lt; {cold} &deg;C) versus warm (Europe/Berlin).",
    },
    "weather.kind.rain": {"de": "Regen", "en": "rain"},
    "weather.kind.temperature": {"de": "Kälte", "en": "temperature"},
    "weather.aria": {
        "de": "Anteil leerer Stationen je Uhrzeit (0-23 Uhr, Europe/Berlin), {kind}",
        "en": "Share of empty stations by local hour (0-23, Europe/Berlin), {kind}",
    },
    "weather.caption": {
        "de": "Anteil leerer Stationen (%) je Uhrzeit (0–23 Uhr, Europe/Berlin), {kind}, auf Basis von {full_days} vollen Tagen; {excluded} Stunden ohne Wetterdaten ausgeschlossen.",
        "en": "Share of empty stations (%) by local hour (0–23, Europe/Berlin), {kind}, based on {full_days} full days; {excluded} hours excluded for missing weather.",
    },
    "weather.table.caption": {
        "de": "Anteil leerer Stationen je Uhrzeit, {kind}",
        "en": "Share of empty stations by local hour, {kind}",
    },
    "weather.table.bucket": {"de": "Zustand", "en": "Bucket"},
    "weather.missing": {
        "de": "Für „{label}“ liegen noch keine Stunden vor.",
        "en": "No hours classified as “{label}” yet.",
    },
    "footprint.heading": {"de": "Der tägliche Fußabdruck des Systems", "en": "The system's daily footprint"},
    "footprint.summary": {
        "de": "Am {date} gab es {n} Stationen und rund {bikes} Räder im System.",
        "en": "On {date}, there were {n} stations and about {bikes} bikes in the system.",
    },
    "footprint.aria": {
        "de": "Räder im System je Tag, E-Bike/Pedal/unbekannt, auf Basis von {full_days} vollen Tagen",
        "en": "Bikes in the system per day, e-bike/pedal/unknown, based on {full_days} full days",
    },
    "footprint.caption": {
        "de": "Räder im System je vollem Tag, aufgeteilt in E-Bike, Pedal und unbekannt, auf Basis von {full_days} vollen Tagen.",
        "en": "Bikes in the system per full day, split into e-bike, pedal and unknown, based on {full_days} full days.",
    },
    "footprint.legend.ebike": {"de": "E-Bike", "en": "e-bike"},
    "footprint.legend.pedal": {"de": "Pedal", "en": "pedal"},
    "footprint.legend.unknown": {"de": "unbekannt", "en": "unknown"},
    "footprint.table.caption": {"de": "Täglicher Fußabdruck des Systems", "en": "System's daily footprint"},
    "footprint.col.date": {"de": "Datum", "en": "Date"},
    "footprint.col.stations": {"de": "Stationen", "en": "Stations"},
    "footprint.col.bikes_at_stations": {"de": "Räder an Stationen", "en": "Bikes at stations"},
    "footprint.col.free_floating": {"de": "Free-floating", "en": "Free-floating"},
    "footprint.col.ebike": {"de": "E-Bike", "en": "E-bike"},
    "footprint.col.pedal": {"de": "Pedal", "en": "Pedal"},
    "footprint.col.unknown": {"de": "Unbekannt", "en": "Unknown"},
}


def t(key: str, lang: str, **kwargs: object) -> Markup:
    """Return the catalog string for ``key`` in ``lang``; raises KeyError if absent."""
    if lang not in LANGS:
        raise KeyError(f"unknown language: {lang!r}")
    return Markup(STRINGS[key][lang]).format(**kwargs)
