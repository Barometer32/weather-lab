# J-Weather

Active Google Cloud project: `j-weather-261020012817` (J-Weather), region
`us-central1`. Repository branch: `metar-cloud-history-20261019`.

## Current

Current restores the original KFCM + KMIC + KMSP summary, twelve-hour table and
basic QA indicators. Temperature and dew point are equal averages in Celsius,
using METAR T-remark precision before Fahrenheit conversion. Wind speed is a
scalar average; direction uses speed-weighted circular averaging. A green QA
indicator requires all three airports to pass basic temperature/dew-point/wind
checks. Incomplete hourly rows use valid contributors and show amber QA dots.
No previous report is carried forward into a missing hour.

A plain **Sun angle** line at the top of **Satellite** shows the live angle, updated
every minute and independently of hourly observation history. It uses the
NOAA GML solar-position equations at 44.9244°N, 93.414°W; negative values mean
below the geometric horizon. Current contains the hourly table without metric
tiles or a sun-angle block. The Current page embeds prepared values and
history in its initial HTML response.

Original summary reference: `958541732691913175126f62202990f19521c5a2`.

## Clouds map

The Clouds map shows a small colored dot for each airport's lowest known
**broken or overcast** cloud base. Five shades run from black (lowest), through dark gray, medium gray and light
gray, to white (highest): ≤5,000 ft; >5,000 to <10,000 ft; 10,000 to <15,000 ft;
15,000 to <20,000 ft; and ≥20,000 ft AGL. The color scale is at the bottom of
the Clouds page. Map dots and scale swatches share CSS palette variables.
Tap a dot for the exact base, band, station, actual report time and all layers.
Clear/few/scattered, vertical visibility, unknown ceiling heights and missing
cloud data have no dot. An unknown-height BKN/OVC layer prevents labeling a
higher layer as the lowest base. These are custom display bands, not flight
categories. The bands above 12,000 ft use actual reported cloud bases; they
never infer high clouds from an automated station's CLR report.

KFCM, KMIC and KMSP appear individually here. Every qualifying airport in view
is drawn with no collision suppression, station priority or station-count cap.
The station list includes all available reports, including those without a
plotted ceiling. The regional extent remains 40–50°N, 100–85°W; existing
quality exclusions KCFE/KFCE and KSGS remain in effect. Zoom and pan reveal
more of the collected region. A missing dot does not establish clear skies.

Current and Clouds share one canonical archive: `live/metar-clouds.json` in the
private weather-data bucket. Collection now runs once hourly at **:00** and
selects routine METARs closest to :53 within **:45–:59** in the preceding hour.
SPECI and five-minute reports are excluded. The twelve-hour slider keeps real
hourly snapshots. Reports arriving after collection may be missing that hour.
No automatic within-hour upstream retries or extra collection job is added.

The browser reads prepared data on opening, Refresh and tab return. A saved-data
check at :00:30 waits up to two additional minutes for that collection result;
these checks do not trigger NOAA downloads. Freshness checks allow two minutes
for collection. Failed source collection preserves the previous saved object
and its actual check time.

## Other views

- Radar: native KMPX 0.5° reflectivity, original continuous colors, two-hour
  history, every available completed low-level scan; source collection each
  minute. No map location dots or city labels.
- Satellite: original COD true color, Day Cloud Phase and NT Microphysics,
  two-hour imagery window; collection every five minutes.
- Forecast: official NWS point forecast for Hopkins (44.9244°N, 93.414°W), read
  directly from MapClick's JSON feed to match its point-forecast webpage;
  collection at :00 and :30. This cadence can add about thirty minutes of lag
  after a forecast changes; it does not guarantee simultaneous updates with
  the NWS webpage or bypass upstream caching.

No AI forecast or contour-map tabs are enabled. Schedules run with the site
closed. Service identities, image-building and deployment are described in
`launch-j-weather.sh` and `deploy.sh`; older restore helpers target historical
projects and should not be used for this active project.

## Mobile map viewers

Radar, METAR and Satellite each have a **Full screen** button. The whole map
surface expands, including the timestamp, timeline, reset (where available)
and **Close** button. On phones and short landscape screens, the full-width
slider stays on the bottom row. Native browser fullscreen is requested when
supported; a viewport-filling overlay is used when unavailable, including on
mobile browsers. Browser chrome can remain visible in this fallback. Close or
Escape restores the page; map size is refreshed on exit and rotation without
resetting the timeline or geographic view. Safe-area padding protects controls
near a phone's home indicator. Cloud-height dots are 10 px, with a dark outline so white dots remain visible.

## Apply this update to J-Weather

In authenticated Cloud Shell:

```sh
curl -fsSL https://raw.githubusercontent.com/Barometer32/weather-lab/metar-cloud-history-20261019/update-j-weather-current.sh -o /tmp/j-weather-update.sh && bash /tmp/j-weather-update.sh
```

The helper saves website settings and the existing METAR schedule, builds a
versioned image, updates the existing `weather-lab` service, moves
`weather-live-metar-clouds` to `0 * * * *`, and verifies the published page and
twelve hourly positions. The collector already accepts any hourly trigger and
reads the same stored reports, so its image does not need an update. Existing
history, bucket, radar/satellite/forecast jobs and website domain mappings
remain in place. No archive reimport is needed.

## Local checks

Install `requirements.txt` plus pytest in a Python environment, then run:

```sh
python -m pytest -q tests
node tests/current_views.test.js
node tests/station_views.test.js
node tests/weather_tabs.test.js
node tests/sun_angle.test.js
node tests/map_fullscreen.test.js
```
