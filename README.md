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

A compact **Sun angle** block above the hourly table shows the live angle, updated
every minute and independently of hourly observation history. It uses the
NOAA GML solar-position equations at 44.9244°N, 93.414°W; negative values mean
below the geometric horizon. The Current page embeds prepared values and
history in its initial HTML response.

Original summary reference: `958541732691913175126f62202990f19521c5a2`.

## METAR cloud map

The METAR map shows only the lowest known **broken or overcast** cloud base at
each actual airport location. Numbers are **hundreds of feet above ground**:
27 = 2,700 ft, 250 = 25,000 ft, 3 = 300 ft. Clear, few, scattered, vertical
visibility, missing cloud data and unknown ceiling heights have no map number.
If a BKN/OVC layer has unknown height, another layer is not labeled as the
lowest base. Tap a number for its station, exact base, actual report time and
reported cloud layers.

KFCM, KMIC and KMSP appear individually here. Every qualifying airport in view
is drawn with no collision suppression, station priority or station-count cap.
The station list includes all available reports, including those without a
plotted ceiling. The regional extent remains 40–50°N, 100–85°W; existing
quality exclusions KCFE/KFCE and KSGS remain in effect. Zoom and pan reveal
more of the collected region. A missing number does not establish clear skies.

Current and METAR share one canonical archive: `live/metar-clouds.json` in the
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
- Forecast: official NWS point forecast for Hopkins; collection at :00 and :30.

No AI forecast or contour-map tabs are enabled. Schedules run with the site
closed. Service identities, image-building and deployment are described in
`launch-j-weather.sh` and `deploy.sh`; older restore helpers target historical
projects and should not be used for this active project.

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
```
