"""String catalog for the site shell: every key carries both languages."""

from __future__ import annotations

from markupsafe import Markup

LANGS = ("de", "en")

STRINGS: dict[str, dict[str, str]] = {
    "site.title": {"de": "Wie Berlin radelt", "en": "How Berlin Rides"},
    "nav.skip": {"de": "Zum Inhalt springen", "en": "Skip to content"},
    "meta.description": {
        "de": "Wo und wann Berliner Leihräder fehlen: Auswertung der öffentlichen Bestandsdaten von Nextbike und Dott.",
        "en": "Where and when Berlin's rental bikes run short: an analysis of the public stock data of Nextbike and Dott.",
    },
    "meta.image_alt": {
        "de": "Vorschaubild: Wie Berlin radelt – wann und wo Leihräder fehlen",
        "en": "Preview image: How Berlin Rides – when and where rental bikes run short",
    },
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
    "common.days_collected": {"de": "{days}/{needed} Tage gesammelt", "en": "{days}/{needed} days collected"},
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
    "lead.text": {
        "de": "Wo stehen morgens um 8 Uhr noch Leihräder? Diese Seite wertet die öffentlich abrufbaren Bestandsdaten der Berliner Leihradsysteme aus und zeigt, wann und wo Räder fehlen.",
        "en": "Where are the rental bikes still standing at 8am? This page analyses the publicly available stock data of Berlin's bike-share systems and shows when and where bikes run short.",
    },
    "callout.days": {"de": "volle Tage gesammelt", "en": "full days collected"},
    "callout.bikes": {"de": "Räder verfügbar um {hour}:00 (Tiefpunkt an Wochentagen)", "en": "bikes available at {hour}:00 (weekday low)"},
    "callout.shortage": {"de": "der Stationen um 8:00 leer (Wochentage)", "en": "of stations empty at 8:00 (weekdays)"},
    "toc.aria": {"de": "Inhalt dieser Seite", "en": "On this page"},
    "anchor.aria": {"de": "Link zu diesem Abschnitt", "en": "Link to this section"},
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
    "availability.axis.x": {"de": "Uhrzeit (Uhr, Europe/Berlin)", "en": "Local hour (h, Europe/Berlin)"},
    "availability.axis.y": {"de": "Verfügbare Räder (Anzahl)", "en": "Bikes available (count)"},
    "availability.headline": {"de": "{value} Räder um {hour}:00", "en": "{value} bikes at {hour}:00"},
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
    "shortage.axis.x": {
        "de": "Leere Minuten pro Tag (Mo–Fr 7:30–8:30)",
        "en": "Empty minutes per day (Mon–Fri 7:30–8:30)",
    },
    "shortage.headline": {"de": "{value} Min.", "en": "{value} min"},
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
    "bezirke.axis.x": {"de": "Uhrzeit (Uhr, Europe/Berlin)", "en": "Local hour (h, Europe/Berlin)"},
    "bezirke.axis.y": {"de": "Verfügbare Räder (Anzahl, Mo–Fr)", "en": "Bikes available (count, Mon–Fri)"},
    "bezirke.headline": {
        "de": "{value} Räder um {hour}:00",
        "en": "{value} bikes at {hour}:00",
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
    "flow.axis.x": {"de": "Uhrzeit (Uhr, Europe/Berlin)", "en": "Local hour (h, Europe/Berlin)"},
    "flow.axis.y": {
        "de": "Räder pro Stunde (netto, Mo–Fr)",
        "en": "Bikes per hour (net, Mon–Fri)",
    },
    "flow.headline": {
        "de": "{value} Räder/Std. um {hour}:00",
        "en": "{value} bikes/h at {hour}:00",
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
    "weather.axis.x": {"de": "Uhrzeit (Uhr, Europe/Berlin)", "en": "Local hour (h, Europe/Berlin)"},
    "weather.axis.y": {"de": "Leere Stationen (%)", "en": "Empty stations (%)"},
    "weather.headline.both": {
        "de": "{first} {first_value} % · {second} {second_value} %",
        "en": "{first} {first_value} % · {second} {second_value} %",
    },
    "weather.headline.single": {"de": "{first} {first_value} %", "en": "{first} {first_value} %"},
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
    "footprint.axis.x": {"de": "Datum (Tag, Europe/Berlin)", "en": "Date (day, Europe/Berlin)"},
    "footprint.axis.y": {"de": "Räder im System (Anzahl)", "en": "Bikes in the system (count)"},
    "footprint.headline": {"de": "{value} Räder", "en": "{value} bikes"},
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
    "map.heading": {"de": "Gibt es um 8 Uhr ein Rad an meiner Station?", "en": "Will there be a bike at my station at 8:00?"},
    "map.intro": {
        "de": "Wähle eine Station (auf der Karte oder in der Liste) oder einen Ortsteil und einen Wochentag. Die Kurve zeigt, wie viele Räder dort typischerweise zu jeder Stunde verfügbar sind.",
        "en": "Pick a station (on the map or from the list) or an Ortsteil, and a weekday. The curve shows how many bikes are typically available there at each hour.",
    },
    "map.noscript": {
        "de": "Die Karte braucht JavaScript. Die Rohdaten gibt es als {link}.",
        "en": "The map needs JavaScript. The raw data is available as {link}.",
    },
    "map.aria": {"de": "Karte der Stationen", "en": "Map of stations"},
    "map.label.station": {"de": "Station", "en": "Station"},
    "map.label.ortsteil": {"de": "Ortsteil", "en": "Ortsteil"},
    "map.label.search": {"de": "Station suchen (Name eintippen)", "en": "Search for a station (type its name)"},
    "map.search.placeholder": {"de": "Stationsname", "en": "Station name"},
    "map.label.hour": {"de": "Uhrzeit", "en": "Hour"},
    "map.ortsteil_button": {"de": "Ganzen Ortsteil zeigen", "en": "Show the whole Ortsteil"},
    "map.label.weekday": {"de": "Wochentag", "en": "Weekday"},
    "map.chart.aria": {"de": "Verfügbare Räder je Stunde", "en": "Bikes available by hour"},
    "map.caption": {
        "de": "Mittlere verfügbare Räder je Stunde (0–23 Uhr, Europe/Berlin).",
        "en": "Mean bikes available by local hour (0–23, Europe/Berlin).",
    },
    "map.days": {"de": "({n} Tage)", "en": "({n} days)"},
    "map.table.summary": {"de": "Werte als Tabelle", "en": "Values as a table"},
    "map.table.caption": {"de": "Verfügbare Räder je Stunde", "en": "Bikes available by hour"},
    "map.table.hour": {"de": "Stunde", "en": "Hour"},
    "map.table.bikes": {"de": "Räder", "en": "Bikes"},
    "map.axis.x": {"de": "Uhrzeit (Uhr, Europe/Berlin)", "en": "Local hour (h, Europe/Berlin)"},
    "map.axis.y": {"de": "Verfügbare Räder (Anzahl)", "en": "Bikes available (count)"},
    "map.headline": {"de": "{value} Räder um {hour}:00", "en": "{value} bikes at {hour}:00"},
    "map.credit": {"de": "Kartendaten", "en": "Map data"},
    "map.ortsteil_title": {"de": "Ortsteil {name}", "en": "Ortsteil {name}"},
    "map.days_collected": {"de": "{days}/{needed} Tage gesammelt", "en": "{days}/{needed} days collected"},
    "map.not_enough_data": {"de": "Noch nicht genug Daten", "en": "Not enough data yet"},
    "map.load_error": {"de": "Daten konnten nicht geladen werden.", "en": "Could not load data."},
    "map.legend.heading": {"de": "Typische Verfügbarkeit zur gewählten Uhrzeit", "en": "Typical availability at the picked hour"},
    "map.bin.0": {"de": "0 Räder", "en": "0 bikes"},
    "map.bin.1": {"de": "unter 1 Rad", "en": "under 1 bike"},
    "map.bin.2": {"de": "1–3 Räder", "en": "1–3 bikes"},
    "map.bin.3": {"de": "3 oder mehr Räder", "en": "3 or more bikes"},
    "map.bin.none": {"de": "keine Daten", "en": "no data"},
    "map.marker_label": {"de": "{name}: {bin} um {hour}:00", "en": "{name}: {bin} at {hour}:00"},
    "map.weekday.0": {"de": "Montag", "en": "Monday"},
    "map.weekday.1": {"de": "Dienstag", "en": "Tuesday"},
    "map.weekday.2": {"de": "Mittwoch", "en": "Wednesday"},
    "map.weekday.3": {"de": "Donnerstag", "en": "Thursday"},
    "map.weekday.4": {"de": "Freitag", "en": "Friday"},
    "map.weekday.5": {"de": "Samstag", "en": "Saturday"},
    "methodology.h1": {
        "de": "Methodik: So entstehen die Zahlen",
        "en": "Methodology: how the numbers are made",
    },
    "methodology.h2": {
        "de": "Methodik",
        "en": "Methodology",
    },
    "methodology.h3": {
        "de": "Datenquellen",
        "en": "Data sources",
    },
    "methodology.col.source": {
        "de": "Quelle",
        "en": "Source",
    },
    "methodology.col.used_for": {
        "de": "Verwendet für",
        "en": "Used for",
    },
    "methodology.col.license": {
        "de": "Lizenz",
        "en": "License",
    },
    "methodology.p.snapshot": {
        "de": "Diese Seite sammelt keine Fahrten. nextbike und Dott veröffentlichen keine historischen Fahrtdaten, sondern nur den aktuellen Zustand des Systems (GBFS). Deshalb speichert der Collector alle 2 Minuten eine Momentaufnahme (<em>snapshot</em>) der Stationen und frei stehenden Räder.",
        "en": "This site does not collect trips. nextbike and Dott do not publish historical trip data, only the system's current state (GBFS). The collector therefore stores a snapshot of stations and free-floating bikes every 2 minutes.",
    },
    "methodology.p.bike_id": {
        "de": "Die <code>bike_id</code> jedes Rads wechselt nach jeder Fahrt. Daraus lassen sich keine Fahrten und keine Verlaufshistorie einzelner Räder rekonstruieren, und <code>bike_id</code> wird nie auf die Festplatte geschrieben, geloggt oder als Join-Schlüssel benutzt. Frei stehende Räder werden stattdessen auf H3-Zellen der Auflösung 8 aggregiert (siehe ADR-0001), bevor etwas gespeichert wird.",
        "en": "Each bike's <code>bike_id</code> rotates after every rental. No trips and no per-bike history can be reconstructed from that, and <code>bike_id</code> is never written to disk, logged or used as a join key. Free-floating bikes are instead aggregated to H3 resolution 8 cells (ADR-0001) before anything is stored.",
    },
    "methodology.p.min_days": {
        "de": "Jede Kennzahl nennt, auf wie vielen Tagen sie basiert, und verweigert eine Veröffentlichung unterhalb von {min_full_days} vollen Tagen (\"noch nicht genug Daten\").",
        "en": "Every metric reports how many days of data it is based on and refuses to publish below {min_full_days} full days (\"not enough data yet\").",
    },
    "methodology.p.empty": {
        "de": "Bei \"leeren Stationsminuten\" wird die Dauer zwischen zwei Momentaufnahmen derselben Station auf 0 gesetzt, wenn sie mehr als das Doppelte des mittleren Abtastintervalls beträgt oder eine erfasste Ausfallzeit (<em>gap</em>) überlappt, damit ein Feed-Ausfall oder Neustart die Zahlen nicht verzerrt.",
        "en": "For \"empty station minutes\", the duration between two snapshots of the same station is capped to 0 when it exceeds twice the dataset's median snapshot interval, or when it overlaps a recorded outage (<em>gap</em>), so a feed outage or restart never inflates the total.",
    },
    "methodology.p.flow": {
        "de": "Der Netto-Fluss zwischen Bezirken ist keine Messung einzelner Fahrten, sondern eine Schätzung aus Zu- und Abnahmen je Station und Stunde, proportional auf die Bezirke verteilt.",
        "en": "Net flow between Bezirke is not a measurement of individual trips; it is inferred from each station's gains and losses per hour, allocated proportionally across Bezirke.",
    },
    "methodology.p.weather": {
        "de": "Regen wird ab {rain_mm} mm/h Niederschlag gezählt, Kälte unter {cold_c} °C (siehe ADR-0017). Alle Uhrzeiten auf dieser Seite werden in der Zeitzone Europe/Berlin angezeigt; die Rohdaten sind in UTC gespeichert.",
        "en": "Rain is counted from {rain_mm} mm/h of precipitation, cold below {cold_c} °C (ADR-0017). All times on this page are shown in the Europe/Berlin timezone; the underlying data is stored in UTC.",
    },
    "impressum.h2": {
        "de": "Impressum",
        "en": "Legal notice",
    },
    "impressum.private": {
        "de": "Dies ist ein privates, nicht-kommerzielles Projekt. Es besteht keine Verbindung zu nextbike, Dott oder dem Land Berlin.",
        "en": "A private, non-commercial project, not affiliated with nextbike, Dott or the State of Berlin. Contact details above.",
    },
    "datenschutz.h2": {
        "de": "Datenschutzerklärung",
        "en": "Privacy",
    },
    "map.weekday.6": {"de": "Sonntag", "en": "Sunday"},
}


def t(key: str, lang: str, **kwargs: object) -> Markup:
    """Return the catalog string for ``key`` in ``lang``; raises KeyError if absent."""
    if lang not in LANGS:
        raise KeyError(f"unknown language: {lang!r}")
    return Markup(STRINGS[key][lang]).format(**kwargs)
