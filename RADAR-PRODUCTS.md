# KMPX radar products

The radar dropdown keeps the lowest reflectivity cut as its opening selection.
All available reflectivity elevations in the last two hours are listed using the
scan plan's actual angles. For example, the November 3 KMPX VCP contained 0.5,
0.9, 1.3, 1.8, 2.4, 3.1, 4.0, 5.1, 6.4, 8.0, 10.0, 12.0, 14.0, 16.7 and
19.5 degrees. Other scan patterns may produce different lists. A requested
1.5-degree view must not be labeled as such when the actual cut is 1.3 degrees.

The collector reuses each downloaded Level II volume for all elevations, drops
non-reflectivity moments, and excludes duplicate split-cut Doppler sweeps. Each
loop includes only complete sweeps at that angle, with its own actual scan time.
Higher cuts generally update once per volume; supplemental low cuts can update
more often. The existing 10 dBZ threshold and native-gate renderer are retained.
There is no automatic blending between elevations. Higher beams sample farther
above the ground and cannot reliably fill every apparent gap in the lowest cut.

Storm-total precipitation uses NOAA's dual-polarization DTA/172 product through
the public Unidata Level III archive. Its range is 230 km, with 250 m range gates
and 1-degree azimuths. The product's scale/offset converts source codes into
hundredths of inches; the viewer shows inches and the accumulation's start time.
The two-hour slider is a history of cumulative storm totals, not two-hour rainfall,
midnight-to-current rainfall, a fixed 24-hour total, or a sum of reflectivity.
The accumulation can reset after a continuous dry hour. Null products are shown
as inactive accumulation rather than fabricating a rainfall amount.

Only the selected product's loop is downloaded/decoded by the viewer. The
original low-cut loop continues to preload as before; upper cuts and precipitation
load on selection. Memory is bounded and no extra scheduler jobs are introduced.
All elevations increase collector work, object writes and storage; the original
one-day radar object lifecycle still applies. This is not a measured cost estimate.

Deployment: run `update-weather-radar-products.sh PROJECT_ID`, preferably with
`WEATHER_SOURCE_COMMIT` pinned to the reviewed commit. It saves both service
configurations and the radar schedule, builds once, seeds the new products through
an isolated manifest/cursor, then updates the collector and website images without
replacing other settings. An originally enabled radar schedule is resumed even
if preparation fails. METAR, satellite, forecast and Air Q schedules are untouched.
Verification retries transient 429/5xx responses and checks every newest packet.

References: NOAA ROC ICD 2620003Y, section 56 (Digital Storm Total Accumulation),
NOAA ROC ICD 2620001 product 172, and MetPy 1.7.1's Level III GenericDigitalMapper.
