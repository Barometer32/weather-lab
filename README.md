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

The METAR station model combines red temperature and green dewpoint on the
left, a cloud-cover circle and compact downwind arrow at the airport, blue
wind speed in mph at lower right and the lowest BKN/OVC base at upper right.
Heights are rounded to thousands of feet (at or below 1,000 feet is 1).
No number is shown for FEW/SCT/clear, obscured sky (VV), or unknown ceiling
bases. An unknown-height BKN/OVC layer prevents claiming another layer is lowest.
Tap a station to see the exact cloud base in feet above ground level.
The separate Clouds tab has been removed. All eligible airports, including
KCFE/KFCE, KSGS and KDEH, are available; compact spacing prevents overlaps,
and zooming reveals more airports. No clouds are inferred above reporting limits.

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

## Combined METAR display update

Run `update-weather-lab-plots.sh weather-lab-261024-133205` in Cloud Shell.
The five tabs are METAR, RADAR, SATELLITE, FORECAST and AIR Q. Cloud information
is combined into the main twelve-hour METAR map; the separate Clouds tab is
removed. A station circle shows reported sky cover, with a compact solid arrow
pointing where the wind is going. Temperature and dewpoint
sit close to the circle on the left, wind speed in mph is lower right, and the lowest BKN/OVC
base is upper right, rounded to thousands of feet (at or below 1,000 feet is 1).
Clear reports have hollow circles, obscured sky has an X, and missing cloud
reports have a question mark. No ceiling number is invented for missing bases.
Tap a station to see the exact base in feet. The map reserves the largest
station footprint across the loop to avoid overlaps as values change.

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
paused and unrelated jobs retain their state. The website image is updated only
after the import succeeds; the latest layout and twelve populated hourly airport
frames are then verified. Failure reports retain full execution, task and audit
JSON, including protoPayload. Saved settings are printed on exit.
