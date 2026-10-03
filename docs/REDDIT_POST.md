# Draft r/berlin post

Fill the `{{…}}` placeholders from the live article after at least 14 (better 28)
full days of data. Each placeholder names the chart it comes from.

---

## Deutsch

**Titel:** Ich habe {{FULL_DAYS}} Tage lang alle 2 Minuten die nextbike-Stationen in Berlin mitgeschrieben. Hier ist, wann und wo die Räder ausgehen.

Berlin veröffentlicht keine Fahrtdaten für Leihräder, nur einen Live-Feed, welche
Räder gerade wo stehen. Ich habe diesen Feed seit {{START_DATE}} alle zwei Minuten
gespeichert und ausgewertet. Fahrrad-IDs werden dabei nicht gespeichert, es geht nur
um Verfügbarkeit.

Die interessantesten Ergebnisse:

1. **Morgens um 8 ist {{SHARE_EMPTY_0800}} % der Stationen leer.** Am schlimmsten:
   {{TOP_EMPTY_STATION}} ({{TOP_EMPTY_ORTSTEIL}}). *(Abschnitt „Morgendlicher Mangel“)*
2. **{{FLOW_FINDING}}** — z. B. „Werktags fließen zwischen 7 und 9 Uhr netto
   {{N}} Räder pro Tag aus {{BEZIRK_A}} nach {{BEZIRK_B}}.“ *(Abschnitt „Netto-Fluss“)*
3. **Bei Regen {{RAIN_FINDING}}.** *(Abschnitt „Regen und Kälte“)*
4. **{{FOOTPRINT_FINDING}}** — z. B. „{{EBIKE_SHARE}} % der Flotte sind E-Bikes.“
   *(Abschnitt „Systemgröße“)*

Auf der Karte kannst du deine eigene Station anklicken und sehen, wie viele Räder dort
typischerweise montags um 8 stehen: {{SITE_URL}}/map.html

Methodik und Datenquellen: {{SITE_URL}}/methodology.html. Code (MIT, ein Fork von Todd
Schneiders NYC-Citi-Bike-Analyse): https://github.com/tpatzelt/berlin-bike-data

---

## English

**Title:** I logged every nextbike station in Berlin every 2 minutes for {{FULL_DAYS}} days. Here's when and where the bikes run out.

Berlin publishes no trip data for its bike share, only a live feed of which bikes are
where right now. I've been saving that feed every two minutes since {{START_DATE}}
and analysed it. Bike ids are never stored; this is about availability only.

Highlights:

1. **At 8:00 on weekdays, {{SHARE_EMPTY_0800}}% of stations are empty.** Worst:
   {{TOP_EMPTY_STATION}} ({{TOP_EMPTY_ORTSTEIL}}). *(Morning shortage section)*
2. **{{FLOW_FINDING}}** e.g. "On weekday mornings a net {{N}} bikes a day move from
   {{BEZIRK_A}} to {{BEZIRK_B}}." *(Net flow section)*
3. **When it rains, {{RAIN_FINDING}}.** *(Rain and cold section)*
4. **{{FOOTPRINT_FINDING}}** e.g. "{{EBIKE_SHARE}}% of the fleet are e-bikes."
   *(System footprint section)*

Check your own station on the map, typical bikes at 8:00 on a Monday:
{{SITE_URL}}/map.html

Methodology and sources: {{SITE_URL}}/methodology.html. Code (MIT, a fork of Todd
Schneider's NYC Citi Bike analysis): https://github.com/tpatzelt/berlin-bike-data
