# J-Weather

Active Google Cloud project: `j-weather-261020012817` (J-Weather), region
`us-central1`. Repository branch: `metar-cloud-history-20261019`.

## Current

Current shows four compact readings: three-airport temperature, dewpoint and
wind, plus the current Hopkins Sun angle. There is no Current history table.
`weather-live-current` checks the latest KFCM, KMIC and KMSP airport reports
once every two minutes, using only direct NOAA MADIS five-minute ASOS. Only
reports at :00, :05, :10, … :55 are eligible. IEM, AWC, routine text METAR and
SPECI reports are excluded from Current. The Clouds map keeps its own hourly
METAR collection.

MADIS Kelvin temperatures are decoded to whole Celsius degrees. All three
Celsius values are averaged equally, then converted to Fahrenheit and displayed
as whole degrees. Wind speed is scalar-averaged in mph and displays as `SW 5`,
without a unit suffix; direction uses speed-weighted circular averaging and
eight compass headings. Sun angle keeps its decimal precision.

The complete MADIS average advances only when all three latest reports pass
physical-range/dewpoint/wind checks and their timestamps span no more than
15 minutes, inclusive. Otherwise the last qualifying average and its original
mean observation time remain displayed. Report age relative to the current
clock does not disqualify an aligned set; a two-station average is never used.
Observation time is the arithmetic mean of the actual three UTC timestamps,
including across midnight. This is a spatial latest-report mean, not temporal
smoothing. Missing or invalid latest reports cannot silently fall back to an
older report to hide the problem.

`live/current.json` atomically retains the latest MADIS reports and last good
complete MADIS average. A new product version rejects the old mixed-source
cache and lastGood values. After deployment Current waits for its first
qualifying MADIS set, rather than displaying an old routine/SPECI average.
The browser and initial page only read prepared data. Visible Current reads
saved data every 30 seconds. The routine QA success line and source-check time
are removed; the observation time remains unchanged during a hold. Station
reports and QA details are available in the collapsed details section.

Sun angle appears only on Current, for 44.925°N, 93.463°W, matching the Hopkins
reference page. The full NOAA/Meeus Julian-century equations replace the old
fractional-year fit. Display uses apparent solar-centre elevation with NOAA's
standard refraction correction and refreshes every ten seconds. Server-time
checks correct the browser clock offset. It is independent of METAR time and
continues updating when observations are held. For 2026-10-21 04:01:54 UTC,
NOAA's full calculator and this code give -47.60264°; the supplied Timeanddate
screenshot gives -47.61° for that instant. Atmospheric conditions, coordinates,
rounding and update timing can still produce small differences. No fixed
angle offset is applied. Sunrise/sunset are upper-limb events, not a guarantee
that solar-centre elevation equals 0°.

Models have been removed from the UI, API, collector, requirements and current
source tree. The update helper pauses/deletes `weather-live-models`, deletes
only the dedicated `weather-models` service, and removes its two prepared JSON
objects. Shared registry images and the existing radar, satellite, Clouds,
forecast and Air Quality views are retained.

## Air Quality

The Air Quality tab embeds the standalone interactive map used on MPCA's
[current conditions page](https://www.pca.state.mn.us/air-water-land-climate/current-air-quality-conditions).
It loads directly from MPCA on the first tab selection, keeps its view across
tab changes, and offers a manual refresh and direct source links. MPCA manages
its data and layer refreshes; J-Weather adds no collection job, archive, or API key.

## Clouds map

The Clouds map shows only the lowest known **broken or overcast** cloud base
at each actual airport location. Compact 12 px numbers are hundreds of feet
above ground: 27 = 2,700 ft, 250 = 25,000 ft, 3 = 300 ft. No color dots or
height-band scale are used. Tap a number for its station, exact base, actual
report time and all reported cloud layers.

Clear/few/scattered, vertical visibility, unknown ceiling heights and missing
cloud data have no map number. An unknown-height BKN/OVC layer prevents
labeling a higher layer as the lowest base. Higher bases use actual reports;
no clouds are inferred above an automated station's reporting limit.

KFCM, KMIC and KMSP appear individually here. Every qualifying airport in view
is drawn with no collision suppression, station priority or station-count cap.
The station list includes all available reports, including those without a
plotted ceiling. The regional extent remains 40–50°N, 100–85°W; existing
station exclusions KCFE/KFCE, KSGS and KDEH remain in effect. Zoom and pan reveal
more of the collected region. A missing number does not establish clear skies.

Clouds uses the canonical hourly archive: `live/metar-clouds.json` in the
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
near a phone's home indicator. Cloud-height numbers are 12 px, with a light halo for legibility.

## Apply this update to J-Weather

In authenticated Cloud Shell:

```sh
curl -fsSL https://raw.githubusercontent.com/Barometer32/weather-lab/metar-cloud-history-20261019/update-j-weather-live.sh -o /tmp/j-weather-update.sh && bash /tmp/j-weather-update.sh
```

The helper saves service settings and schedules, pauses model collection,
builds a versioned image, and updates the collector and website. It creates or
updates `weather-live-current` for two-minute checks and verifies the published
Current page and saved-data API. After verification it removes the retired
model job, dedicated model service and two prepared model JSON objects. The
Clouds history, bucket, radar/satellite/forecast/cloud schedules and website
domain mappings remain in place. No archive reimport is needed. An initial
check is requested; all three valid reports must be within 15 minutes of
each other before a first Current average can appear.

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
