# Weather Lab

Active Google Cloud project: `weather-lab-261024-133205`, region `us-central1`.
Website: https://weather-lab.cloud.run. Repository branch: `metar-cloud-history-20261019`.

Fresh-project migration: `bash start-weather-lab-fresh.sh weather-lab-261024-133205`.
This creates one project named Weather Lab, reuses its saved ID on retries, rebuilds the saved four-product METAR layout at commit `ada1bdb84bfa39d3608812a6ed392a588e303b50`, copies the dedicated old weather bucket when available, and refreshes the source feeds. Settings are saved in `~/weather-lab-fresh-migration`. It tests the collector, all five public pages and their newest imagery before moving `weather-lab.cloud.run` with Google's delete-and-recreate mapping flow. The name is briefly released and cannot be guaranteed during transfer; failed claims attempt to restore the previous mapping. Old billing is disconnected only after the new mapping is ready and responds successfully. The old project itself is retained. Lost Air Q history accumulates again. A specific billing account can be supplied as argument two.

Current tabs: METAR, RADAR, SATELLITE, FORECAST and AIR Q.
Update the working site with `bash update-weather-lab-metars.sh weather-lab-261024-133205`.
Full restore in the same project: `bash restore-weather-lab-latest.sh weather-lab-261024-133205`.
The full restore undeletes the project when needed, links the only open billing account if billing is disabled (or accepts an account ID as argument two), rebuilds weather resources, imports twelve routine airport hours, restores imagery and five schedules, and checks the custom address. A closed billing account must first be reopened in the console. No replacement project is created. Lost Air Q source-hour snapshots accumulate again.

METAR has one map and one twelve-hour slider with Clouds, Wind, Dewpoint and Temperature in a dropdown. All four modes use the same official routine airport reports from :45–:59, closest to :53, labeled with the following hour. Collection starts at :00 with two-minute catch-up checks. No mesonet merge, airport blacklist or averaged metro site is used. Clouds keep every airport at its actual coordinates: a tiny dot without a reported BKN/OVC layer, otherwise the lowest BKN/OVC height rounded to thousands of feet (minimum 1). Missing cloud data/base shows ?. Wind shows a compact downwind vector and speed in mph; calm is 0. Dewpoint and temperature each show one rounded °F number. The non-cloud products use compact, history-stable spacing; zooming reveals nearby sites. Dropdown changes keep the selected hour and view and never fetch a different source. Sun angle is current for Hopkins above the METAR map.

Prepared manifests for every page start loading on page open. Two background browser workers preload the immutable radar and imagery files, with newest frames first. The last successful JSON snapshots are retained with Cache Storage when available and marked Saved while fresh prepared objects load. Fresh callbacks replace saved copies without resetting a selected history hour. Radar decoding is shared between preloading and the radar tab; satellite images use the browser HTTP cache. JSON transfers omit unused raw report fields, and the server retains up to 96 prepared files. A missing file no longer flushes other warmed files. Public production routes use prepared data; visiting a page never starts upstream collection or image preparation. First visits still require network transfers and map rendering, and a scaled-to-zero service can still have a cold start. No always-on instance or extra warm-up schedule is added by this update.

The update removes only retired rapid/mesonet schedule names, preserves the existing five weather schedules, builds and updates the web/collector images, checks every page's prepared data, and warms the newest radar/satellite/Air Q files. Older notes and scripts below are historical and may target retired projects; use the current update/restore commands above.

## Legacy Current implementation (historical)

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

Reserved MADIS sensor-status codes (including 15) are accepted when the
numeric measurement is present, the QC descriptor is V/S/G, and MADIS's QC
results word is zero. Any nonzero QC/internal-consistency results still reject
the value. Explicit sensor failures, unknown codes, missing values and physical
range/dewpoint failures remain excluded. A reserved code alone does not prove
a bad measurement. This covers KMSP's 2026-10-21 12:20 CDT wind: 190 degrees at
5 knots with status 15 and clear QC results.

`live/current.json` atomically retains the latest MADIS reports and last good
complete MADIS average. A new product version rejects the old mixed-source
cache and lastGood values. After deployment Current waits for its first
qualifying MADIS set, rather than displaying an old routine/SPECI average.
The browser and initial page only read prepared data. Visible Current reads
saved data every 30 seconds. The routine QA success line and source-check time
are removed; the observation time remains unchanged during a hold. Station
reports and QA details are available in the collapsed details section. That
table includes each airport's wind in the same compact `SW 5` format. The four
summary readings and their headings are centered in each column, including
the two-column mobile layout.

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

AIR Q archives the public EPA AirNow AQI contours used by MPCA, covering all
Minnesota. The map has county/state boundaries and lake geography without
city labels, monitor markers or numbers, plus a category legend. Source checks
run at :00 and :30; the slider keeps twelve distinct source data hours, using
the source timestamp rather than download time. Repeated checks reuse the same
hour; corrections replace its image. Previously archived styles remain until
they age out. Upstream failures retain the last available map.

The METAR map shows only temperature, dewpoint, a compact downwind vector at
the airport and blue wind speed in mph at lower right. Its frame-stable spacing
filter avoids overlapping weather plots; zooming reveals nearby airports.

The separate CLOUDS tab draws every available airport at its exact location,
without thinning. No BKN/OVC layer is a tiny solid dot. A known lowest BKN/OVC
base replaces the dot with a centered number in thousands of feet (rounded,
with a minimum of 1); 1,000 feet is 1 and 25,000 feet is 25. Unknown cloud cover
or an unknown BKN/OVC base is a question mark. Nothing is offset from the actual
station coordinates. Tap a site for its exact base and report time. Both maps
share twelve hourly frames and matching zoom controls.

METAR uses the canonical hourly archive: `live/metar-clouds.json` in the
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

## Container recovery after project restoration

If the Cloud Run revision cannot import its old image after a deleted project
is restored, rebuild from GitHub with the full airport restore helper and set
`WEATHER_ARTIFACT_REPOSITORY` to a new repository ID (for example,
`j-weather-recovery-20261024`). The builder, both services and the history seed
job use that repository. Existing project resources and weather data remain in
the same project; no new project or billing account is created. The default
repository remains `weather-lab` for other deployments. Failed repository reads
or creation stop before the build.

## METAR and Clouds display update

Run `update-weather-lab-plots.sh weather-lab-261024-133205` in Cloud Shell.
The six tabs are METAR, RADAR, CLOUDS, SATELLITE, FORECAST and AIR Q.
METAR has weather-only plots and CLOUDS has centered BKN/OVC heights or dots at
every available airport. Each map has its own twelve-hour slider.
All eligible airports, including KCFE/KFCE, KSGS and KDEH, remain available.

The helper saves website settings, builds into its current image repository,
and updates only `weather-lab`. Collector settings, schedules and saved weather
data are retained. The confirmed project argument avoids domain-discovery
ambiguity after a project restore.

## Satellite image count

Satellite history now keeps the latest 24 distinct available source images per
product, independent of a two-hour wall-clock cutoff. Source delays therefore
do not shorten an already prepared loop as the clock advances. The collector
checks a pool of up to 48 recent source images to backfill a corrupt or missing
image with the next real available image, retaining at most 24 in the manifest.
Existing images and map overlays are reused, and original JPEG bytes are
preserved. Future timestamps and images older than the one-day storage lifetime
are excluded. If fewer than 24 real images are available, only those actual
images are shown. Radar keeps its existing two-hour policy.

`update-weather-lab-satellite.sh PROJECT_ID` builds once, publishes the collector,
prepares all three satellite products in a private one-time job, then publishes
the website and verifies each image count and source times. Only the satellite
schedule is paused briefly during preparation; its original state is restored
on success or failure. The five-minute schedule and other collectors stay the
same. This update also includes the thicker METAR arrow with a shorter tail and
the latest compact value positions.

## Resume after a completed build and failed restore job

For the October 24 recovery, run
`bash resume-weather-lab-restore.sh weather-lab-261024-133205`. The helper reads
the deployed collector image, identity and bucket, saves existing website and
schedule settings, and runs the history import in a newly named job. This tests
whether a fresh job can run; it does not establish the cause of an earlier
FAILED_PRECONDITION. No image build, API enablement or billing change is made.
Only previously enabled managed schedules are paused and resumed. Existing
paused and unrelated jobs retain their state. The current website image is retained separately from the collector image,
so resuming a history import preserves any newer display changes. The website
is refreshed only after the import succeeds; its saved layout and twelve
populated hourly airport frames are then verified. Failure reports retain full execution, task and audit
JSON, including protoPayload. Saved settings are printed on exit.


## Legacy Hennepin observation station selection (historical)

`update-weather-observations.sh weather-lab-261024-133205` replaces the METAR tab with OBSERVATIONS. It lists only Hennepin West records available through public NOAA MADIS inside the actual U.S. Census Hennepin County boundary (GEOID 27053). Other mesonets, community stations, road stations and airport ASOS are excluded from this inventory. City/site names, station IDs, networks, Fahrenheit temperature/dewpoint, wind, actual observation time and age remain visible. Search helps select stations for a future average. No average or automatic station cohort is computed. There is no observation history slider. The Hopkins sun angle remains on Observations; CLOUDS retains all-airport exact-location slightly smaller dots/heights and twelve routine hourly frames.

Collection checks the current and previous UTC hourly MADIS files every two minutes with conditional HTTP requests. Five-minute report cadence does not imply five-minute delivery latency. Records are not forced onto the top of the hour. Previously discovered sites retain their last actual observation for up to 24 hours, with the original timestamp; missing/QC-rejected measurements show as unknown instead of hiding the entire site. Public availability is not a complete registry of all installed stations. County geometry is bundled in `static/hennepin-county.geojson`, fetched 2026-10-24 from U.S. Census TIGERweb State_County/MapServer/1 with `GEOID='27053'`, WGS84 coordinates, five decimal places. No county lookup is needed at runtime.

The update builds one image, saves both service settings and scheduler definitions, updates the collector and website, adds only `weather-live-observation-stations` at `*/2 * * * *`, and verifies the public station inventory. Existing airport collection continues for CLOUDS. Radar, satellite, forecast and Air Q schedules are preserved. Public page requests read the prepared inventory; they do not download NOAA files. The endpoint is `/api/observation-stations`, and the private collection route is `/collect/observation-stations`.
