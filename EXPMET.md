# Experimental observation analysis

EXPMET is a separate hourly snapshot, leaving the six-hour airport METAR viewer
and its completeness policy intact. It has All fields, Temperature, Dewpoint and
Wind modes, the existing white state/county basemap, saved opening views and
fullscreen phone support. There is no experimental history slider in this version.

## Timing and sources

One scheduled collection at :05 UTC minutes analyzes the preceding top of hour.
For 09:05 local, the analysis is labeled 09:00 and selects each station's latest
available observation from 08:00 through 09:00 inclusive. Report age is measured
against 09:00, not against the file download time. No observations after the
analysis time are used. A successful analysis is not recollected within that hour.
Refresh and page views only read prepared data.

Inputs are the existing unthinned airport cache plus the public NOAA MADIS
Integrated Mesonet hourly files for the preceding and target UTC hours. No station
exclusion list or six-hour completeness filter applies to EXPMET. This does not
claim access to every MADIS dataset or provider: restricted feeds and other MADIS
datasets are not acquired. Preserve MADIS/provider attribution. Public sources:
https://madis.ncep.noaa.gov/madis_sfc.shtml and
https://madis.ncep.noaa.gov/madis_restrictions.shtml.

MADIS reports can arrive 8–45 minutes late or longer. A :05 collection is an
available-data snapshot, not a complete inventory for that hour. Delayed reports
will not revise that snapshot. If one feed fails, the other can support a clearly
labeled partial analysis; total lack of usable observations retains the prior
analysis with its original timestamp. The UI flags stale collection and feed loss.

## Estimation and limitations

Grid points use an anchored scaled Web Mercator grid, nominally 10 km at 45N,
so their on-screen spacing remains uniform in both directions. True ground
spacing and approximate analysis distances vary with latitude.
The same bounds as the airport collection are used: 40–50N, 100–85W. Zooming
selects a power-of-two regular subgrid to keep spacing readable; it never moves
an observed airport or depicts an estimate as an observation.

MADIS field QC rejections, basic ranges and dewpoint/temperature consistency are
checked. Latest observations are deduplicated by station; each field is declustered
to one representative per 5 km bin. Airport reports receive greater starting
weight than mesonets; CWOP receives lower starting weight. Age and distance reduce
weights, and a robust neighborhood median reduces individual extreme readings.
These tunable weights are heuristics, not calibrated station-specific skill scores.

Temperature, dewpoint and wind components use separate observation samples.
Wind is estimated as east/north velocity components before conversion to speed
and meteorological source direction. Dewpoint is constrained not to exceed
temperature. Map labels use Fahrenheit and conventional knot-encoded wind barbs;
popups show wind speed in mph and direction in degrees.

Every grid point is filled if a field has any usable regional observation. Normally
up to 24 neighbors within 120 km are used. Fewer than three nearby sites, or no
site within 50 km, triggers distant-station extrapolation using the closest
available regional observations. Those points stay visible; per-field sparse
support, contributor counts, nearest-site distances and weighted report ages are
reported in popups. A variable with no usable data anywhere is left unavailable.

This is an observation-only experimental interpolation, not NWS analysis,
forecasting, or a data-assimilation system. There is no terrain correction,
anemometer-height normalization, model background or explicit frontal analysis.
Grid resolution does not indicate accuracy; distant estimates can miss local
features. More observations can help coverage but do not guarantee better skill.
No independent accuracy claim has been established.

## Deployment

Run `setup-weather-lab-expmet.sh PROJECT_ID`. It saves existing settings, builds
once, updates the collector image, seeds the first analysis in a private job,
adds only `weather-live-expmet` at `5 * * * *` with retries disabled, then updates
the website and verifies its prepared data. Existing schedules and warm-instance
settings are retained. Full restores also prepare and schedule EXPMET.

Verification covers observation windows, deduplication, scalar fields, circular
wind direction, vector cancellation, robust weights, sparse filling, missing
variables, source failure retention, hourly idempotency, prepared-only reads,
frontend modes, and installer scope.
