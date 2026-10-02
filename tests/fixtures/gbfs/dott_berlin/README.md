# Dott Berlin GBFS fixtures

Recorded by `scripts/record_gbfs_fixtures.py --system dott_berlin` from the
live feed at `https://gbfs.api.ridedott.com/public/v2/berlin/gbfs.json`
(GBFS version 2.3) on 2026-10-02.

## Differences from nextbike_bn

- **Single locale.** `gbfs.json` only has an `en` key (no `de`), unlike
  nextbike which publishes both.
- **It is a scooter feed, not bikes.** Every `vehicle_type_id` is
  `dott_scooter` (`form_factor: "scooter"`, `propulsion_type: "electric"`).
  GBFS still calls the identifier field `bike_id` in v2.3, so the collector
  interface and this fixture set use that name unchanged.
- **station_information/station_status are published.** At recording time
  the earlier assumption that Dott might omit these did not hold: it lists
  568 stations, all `is_virtual_station: true` ("Jelbi" virtual parking
  areas), with real-looking `vehicle_capacity` and `num_bikes_available`.
- **No docked bikes in this snapshot.** Every entry in `free_bike_status`
  was free-floating (no `station_id` key present on any bike).
- **gbfs.json lists three extra feeds that are not recorded as fixtures**:
  `gbfs_versions`, `geofencing_zones` (1428 polygon features, ~1.6 MB) and
  `system_pricing_plans`. None of them are part of G1's collector interface
  (`station_information`, `station_status`, `vehicle_types`,
  `free_bike_status`), so the recording script fetches each once to confirm
  its shape (per the one-request-per-listed-feed allowance) and discards it
  rather than committing an irrelevant multi-hundred-KB file.

## Pseudonymisation

Per the charter non-goal, `bike_id` never reaches disk. Dott embeds the
real `bike_id` UUID directly in `rental_uris` (e.g.
`https://go.ridedott.com/vehicles/<bike_id>?platform=android`), unlike
nextbike's separate numeric place id, so the scrub is a literal substring
replace of the real UUID with the same synthetic `fixture-NNNN` id assigned
to `bike_id`. There is no `vehicle_id` field distinct from `bike_id` in this
feed version.

## Trimming

The live `free_bike_status` response had 4548 vehicles. Only the first 600
(in the order the feed returned them) are kept, per the task notes, to keep
the fixture small. `vehicle_capacity` and `num_bikes_available` counts in
`station_information`/`station_status` were left untouched and were not
recomputed against the trimmed bike list — those feeds describe station
capacity/occupancy, not free-floating vehicles, and are unaffected by the
`free_bike_status` trim.
