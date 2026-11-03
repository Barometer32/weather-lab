# CURRENT and CLOUDS

CURRENT replaces the combined METAR station-plot tab. Navigation is CURRENT,
RADAR, CLOUDS, SATELLITE, FORECAST. Air quality is a compact Current section;
the retired AIR Q map tab is no longer loaded or preloaded.
Forecast uses the same saved point as Current, without reading device location.

## Local air quality and pollution mix

POST /api/local-air-quality uses the same saved location. No device location
request is made by this viewer. A shared, in-memory snapshot is refreshed on
demand at most every 30 minutes per website instance. No API key, new scheduled
job, user-specific backend storage, or statewide image rendering is needed.

The public AirNow reportingarea.dat file provides the official U.S. AQI and
available pollutant subindices for a nearby reporting area. Prefer an area
assigned to the nearest active monitor within 80 km; otherwise use a nearby
reporting-area centre within 100 km. Display the area name in details: this
does not imply an AQI sensor at the GPS point. Use one common observation hour,
not the maximum across mismatched hours. Preserve actual source times.

The separate Pollution mix card is explicitly a **classic AQHI estimate**,
not an official issued U.S. or Canadian index. It uses three-hour mean raw
concentrations of PM2.5 (µg/m³), ozone (ppb), and NO2 (ppb):

    AQHI = (1000/10.4) * [expm1(.000487*PM2.5)
                        + expm1(.000537*ozone) + expm1(.000871*NO2)]

Use the nearest active monitor with all three consecutive source hours for
each pollutant, within 50 km. Thus the inputs may come from different nearby
sites, shown with distances. This is a local estimate, not a personal exposure
measurement or a claim of clinical validation for the selected U.S. location.
Coefficients come from the published national Canadian AQHI formulation; they
are not arbitrary weights on U.S. AQI subindices. Round to a level of at least
1 and display levels above 10 as 10+. Categories are Low 1–3, Moderate 4–6,
High 7–10, Very high above 10. Show contribution percentages as proportions of
this calculated index, not as estimates of a person's share of health risk.

This classic formula covers **only those three pollutants**. PM10, CO and SO2
may appear as separate recent measurements; they are not silently added to the
mix. Canadian operational smoke overrides are not applied. Keep official U.S.
AQI visible independently, including during particulate pollution events.
If any input lacks a complete series, show the mix as unavailable, never zero.

HourlyAQObs timestamps label the START of an hourly sample, so display its end
as the time through which measurements were included. Source files are national;
only active MN/WI monitors and recent reporting-area observations are retained.
Inactive sites, unknown units, mismatched source hours and nonfinite/fill values
are rejected. Preserve valid slight negative raw readings when forming hourly
means, then floor the mean at zero. Do not display indices older than 3 hours;
flag delayed sources or ages over 2 hours. AirNow values are preliminary.

The browser stores only one selected-point air-quality snapshot and clears it
on location change/reset. Late responses from the old point are ignored. Current
weather collection, airport/mesonet choices, weights and wind remain unchanged.

Apply update-weather-local-air.sh with a pinned commit. It builds only the web
service, verifies the five tabs and local endpoint, then pauses the old
weather-live-air-quality map-generation schedule. All other collection jobs and
service scaling settings are retained. Existing archive files and legacy map
endpoints are retained for backwards-compatible restoration.

Sources:
- https://docs.airnowapi.org/docs/HourlyAQObsFactSheet.pdf
- https://docs.airnowapi.org/faq
- https://www.canada.ca/en/environment-climate-change/services/air-quality-health-index/about.html
- Public Health Ontario, Review of Air Quality Index and Air Quality Health
  Index (2013), equation 2 (classic national formulation):
  https://www.publichealthontario.ca/-/media/documents/A/2013/air-quality-health-index.pdf

## Selected-location Forecast

The Forecast viewer posts the saved Current latitude/longitude to /api/forecast.
Coordinates are rounded to four decimal places (roughly 10 m); they do not enter
our access-log query strings. The website reads the NWS MapClick JSON for that
point, preserving its issuance time and day/night narrative. The source link is
also built from that point. A bounded in-memory cache holds up to 64 points for
30 minutes; refresh can recheck NWS after a one-minute minimum. No selected-point
forecasts are written to Cloud Storage or retained as a travel history.

The viewer preloads on page opening, reloads when the selected point changes,
and checks every 30 minutes while Forecast is visible. It also checks on tab
selection and return from the background; cache reuse avoids repeat upstream
requests within the interval. A single browser snapshot accelerates repeat
visits, is keyed to the selected coordinates, and is cleared on a location
change/reset. A failed or late old-location request never substitutes Hopkins
or a prior city's forecast. The fixed prepared GET /api/forecast and existing
collector schedule remain available for legacy restoration checks, but the
current viewer does not subscribe to or preload that fixed forecast.

Update with update-weather-location-forecast.sh and a pinned source commit.
It updates only the website and retains all other service/schedule settings.

## Location

Use my location obtains one position only inside the button's click handler.
No location request runs on load, refresh, tab switching, timers, or movement.
The selection is retained locally on that device until changed or reset. It
updates CURRENT, its solar elevation, and a small fixed-pixel radar dot; the
radar center, renderer, layers, scan history and slider are unchanged. Satellite
imagery and controls are unchanged. Reset location clears the selection and
returns CURRENT to Hopkins. The default point is labelled as a default and is
never shown as a device-location dot.

The site permits geolocation only for its own origin. A browser permission
prompt is controlled by browser settings. Coordinates are sent in the JSON body
of POST /api/current, not in query strings; no travel history is stored. One
local saved weather snapshot is replaced when the selected point changes.

The selected city is looked up once through POST /api/location-name using the
US Census Bureau geographic-coordinate lookup and retained with that selection
on the device. An existing saved point without a name receives one lookup on
load, without accessing device location. Actual containing incorporated places
take priority, then census-designated places, townships/subdivisions, and counties
for rural points. If the lookup fails, weather still loads and the label says
city unavailable. Reset clears the selected city with the coordinates. There
is no periodic place lookup or device-location read.

The main observation timestamp is the mean of the displayed measurements'
representative times, rounded to the nearest minute. Each measurement time
uses its actual, unrounded spatial/age/network station weights from the analysis.
Thus a station's overall time weight is its mean normalized contribution across
the available temperature, dewpoint and wind estimates. Expired or unavailable
fields do not affect this timestamp. The full source time range and individual
station times remain under Contributing stations. Sun height uses current time.

Apply city names and weighted times with update-weather-current-labels.sh;
it builds and updates only the website, retaining all collection schedules.

## Shared collection, every five minutes

The private, scale-to-zero weather-current-collector service handles
/collect/current-analysis independently of the original radar/satellite collector. It reads NOAA MADIS public Integrated Mesonet,
RWIS, and high-frequency airport files, plus the AWC latest airport cache.
Only usable MN/WI observations within the last 30 minutes enter the prepared
snapshot. Data-provider attribution is retained. Public availability and field
QC determine inclusion; restricted MADIS networks are not promised.

Only the current MADIS hour is needed from :30 onward; before :30 the previous
hour is also checked so the observation window crosses midnight/hour changes.
ETag/Last-Modified conditional requests and saved regional parsed rows avoid
unnecessary retransfers/reprocessing. Successfully revised files replace old QC
choices. Failed sources may reuse their cached rows only while the actual
observation timestamps still pass the 30-minute limit. Page views never trigger
MADIS downloads, historical backfills, or grid-wide regeneration.

Filtering to MN/WI reduces processing, shared JSON size and storage. NOAA's
public netCDF files and AWC cache are national downloads; state filtering does
not turn those into regional network transfers.

## Analysis

A fixed local metric grid uses approximately 5-km spacing. For a selected point,
the server evaluates four surrounding grid nodes from the same up-to-five
nearest valid stations **per measurement**, then bilinearly blends those local
node estimates. This is local interpolation, not a precomputed all-state analysis
or a claim of 5-km observational resolution. Evaluating only the required nodes
avoids computing, storing, or sending a statewide grid for each page visit.

Weights combine inverse squared distance (2-km stabilizer), report age (30-minute
exponential scale), a density adjustment, and reduced weight for CWOP. A field
needs at least three usable stations within 80 km, including one within 35 km.
Less than five stations or the nearest usable station beyond 15 km is labelled
limited support. These are initial engineering choices, not certified error
bounds. Elevation/exposure differences and small-scale weather remain limitations.

Temperature and dewpoint have independent valid contributors; wind uses paired
speed/direction components, handles north wraparound, and accepts calm wind
without a direction. The displayed wind is the resultant vector average, in
mph with eight-point direction. Missing wind never invalidates a good temperature.
Source-time ranges and per-field representative times are retained; no claim is
made that asynchronous reports were all observed at one instant.

## Quality control

- Honor MADIS field QC/result words, internal checks and sensor status rules.
- Reject missing, non-finite, out-of-range, future or older-than-30-minute values.
- Reject inconsistent dewpoints above temperature; use QC-passing RH/T for a
  derived dewpoint when needed.
- Deduplicate station aliases and co-located redistributed observations (~20 m).
- Screen isolated temperature/dewpoint outliers only against at least five peers
  within 25 km and 10 minutes: threshold max(12 F, 5 x 1.4826 x local MAD).
  This is conservative screening; it cannot guarantee detection of every fault.
- Do not fill a field without the minimum nearby support or extend stale data
  beyond the requested observation window.

Values are whole degrees F; wind uses an integer speed, with `0` for calm.
Zero wind is a valid numerical report and contributes a zero u/v vector if the
supplied feed QC accepts it, even when calm has no direction. There is no local
stuck-anemometer history test or independent wind buddy check in this version.
The local spatial outlier test above applies to temperature and dewpoint only;
it is not a guarantee that all included sensors are accurate or well exposed.
Solar height is the existing NOAA/Meeus apparent solar-centre calculation at
that selected position and current time. Expanding Contributing stations shows
actual report times, distances, networks, values and per-field weights.

## Clouds and retained products

CLOUDS retains the hourly airport policy (:45–:59 reports; collector at :00,
:05 and :10), four displayed frames (current plus three previous hours), stable
collision spacing, saved/reset view and fullscreen. It displays only a numeric
lowest BKN/OVC height in thousands of feet. No temperature, dewpoint, wind,
coverage circle or dot is plotted. The prepared airport cache still has 12
source hours; viewing or sampling CURRENT does not download that archive.

Boundaries: US Census Bureau TIGERweb State_County layer 0, states 27 and 55,
WGS84 GeoJSON, simplified to 0.002 degrees for regional filtering:
https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/0
The stored file is mn_wi_states.geojson and is bundled in the container image.

Apply this release with setup-weather-current-grid.sh and a pinned source
commit. It backs up service settings/schedules, builds once, prepares the
observations before publishing, adds only weather-live-current-analysis, and
verifies all six tabs. It adds an isolated private Current collector with a scheduler-only invocation
grant. It does not change billing, domains, radar/satellite
schedules, or existing web warm-instance settings.
