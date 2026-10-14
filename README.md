# WEATHER LAB

A phone-friendly Twin Cities weather page with four views:

- **Observations (first/default):** individual hourly station plots from Wisconet and IEM airport, road-weather, agricultural and other networks across the Upper Midwest. Temperature/dew point in °F and wind-flow arrows/speed in mph. Twelve hourly snapshots from reports within :35–:59; zoom in to reveal more plots. The dropdown retains routine hourly airport cloud ceilings. KCFE/KFCE and KSGS remain excluded.
- **Radar:** KMPX native Level II lowest-tilt reflectivity, a two-hour loop, the original continuous COD-style reflectivity gradient from 10 dBZ, and a manual timeline.
- **Satellite:** local Central Minnesota GOES-East True Color, Day Cloud Phase, and Nighttime Microphysics, with state/county lines and a manual timeline.
- **Forecast:** the official NWS day/night forecast for Hopkins at **44.9244, -93.4140**, displayed as compact seven-day rows.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:8080. No API keys or model files are needed.

## Hourly station observations

The default **All station plots** view combines IEM open `/api/1/currents.json?state=XX` bulk feeds for MN, WI, IA, ND, SD, NE, IL, MI, IN, OH, KS and MO with the UW–Madison Wisconet bulk map API. Sites remain inside 40–50°N / 100–85°W. This is the connected public regional network collection, not every MADIS or private station.

One `weather-live-stations` Scheduler job runs at **:00 once per hour** and collects both the weather plots and airport cloud ceilings. Successful hourly station collection is idempotent for the hour, including manual repeated triggers. There is no five-minute observation polling or automatic Scheduler retry. Radar, satellite and forecast schedules are independent and unchanged. The browser reads prepared data on opening, manual Refresh, view changes and tab return, plus an hourly :00:30 check with at most two minutes of bounded reads waiting for collection; those reads never initiate source downloads.

Each station snapshot accepts readings from **:35 through :59, excluding the target hour’s :00**, relative to its target hour. Later data is not mislabeled as a top-of-hour observation, including after a delayed manual deployment. Routine airport METARs from the shared NOAA Aviation Weather Center collection are preferred, with IEM routine METARs filling eligible airport gaps. Airport SPECI and high-frequency reports are omitted. Non-airport sites use their latest valid report within the 25-minute window. Missing sites remain missing; previous hours stay on their original slider positions. Twelve hourly positions are retained. Existing history is filtered to the new 25-minute rule. Bulk RWIS archive requests for MN, WI, IA, SD, NE, IL and IN recover eligible road observations after the currents feed has advanced. Empty archives fall back to eligible current reports; feeds with failures are reported. Other current-only networks can have fewer eligible readings when deployment occurs between hours. The window includes :35:00 through :59:59.999, excluding exact :00 of the target hour.

A separate **Surface contours** map retains the original weather plots above it and follows their hourly timeline. Select temperature, dew point or wind speed/direction. The hourly private collector prepares three raster layers plus contour lines and wind vectors; public visitors only read prepared assets. Old hours without an analysis remain explicitly unavailable. Prepared analysis objects expire after one day.

Each field receives a conservative spatial median/MAD screen against at least four independent neighbor cells within 100 km, excluding co-located sites. At least two corroborating neighbors can protect a real front from a majority-based rejection. Temperature/dew-point/wind-vector minimum disagreement thresholds are 8°F/10°F/15 mph; thresholds increase with local variability. Suspect fields are excluded only from the relevant contours; original plots and popup values remain. Fewer than four buddies means **unverified**, not passed. These are local heuristic checks, not complete MADIS QC, and do not correct terrain/exposure or groups of biased sensors.

Analysis uses a Mercator-aligned 241×161 grid over the stated region, five-kilometer input de-clustering, at most 12 nearby stations, positive distance weights capped at 40% per station, and wind-vector interpolation. It requires at least three stations within 110 km, a nearest station within 65 km, and a point inside the station convex hull. No extrapolation fills sparse gaps. Lines are every 2°F or 5 mph. Use source QC and local screening now; model-background comparisons and a monitored exclusion list are stronger future QC options.

The coverage table distinguishes latest-feed recent sites from eligible sites in the selected snapshot. It does not assert complete MADIS, Hennepin West, private-network or all-state coverage. Fields missing from otherwise available stations stay missing.

Wisconet uses one public `/api/v2/stations/map` request, specifying four five-minute fields and the instant before the target hour via `date`. This returns station coordinates and timestamped observations together, so no per-station requests or metadata downloads are needed. Air temperature/dew point are already Fahrenheit, and wind is already mph. It supplies a single five-minute average for the hourly snapshot, not an hour-long average. All four plotted values come from the same report timestamp; missing fields are not copied from a different time. Units are verified and suspect/bad/unrecognized quality flags are rejected. Unspecified QC (`Z`/blank) is retained without claiming it passed verification. Test stations are excluded. Wisconet is credited on the page and in popups under **CC BY 4.0**, with a notice that values are selected/filtered for hourly display.

IEM `tmpf`/`dwpf` are Fahrenheit, and `sknt` is converted from knots to mph. Air temperature is used, never pavement temperature. Missing/nonfinite/impossible values, invalid coordinates, future reports and dew points more than 1°F above temperature are filtered. These are range/time checks, not full MADIS quality control. Popups retain station names, networks and actual report times. The list searches station ID, name or network. Network-qualified IDs remain distinct. Each airport keeps its own values; no metro average is shown. Unknown wind directions stay unknown. Plots remain at their true coordinates and become denser as zoom permits, with no overlap or new source requests on zoom/pan.

The atomic `live/station-plots.json` object holds the hourly frames. Individual failed sources are listed; only still-valid readings from the same hourly window can remain. Total failure retains the previous object and its original time. The separate `live/metar-clouds.json` object continues to support the cloud dropdown. Its routine reports nearest :53 within :50–:59 are labeled with the following hour; cloud symbols and ceiling logic remain unchanged. The retired `weather-live-metar-clouds` Scheduler job is removed because the station job now shares that collection.

## Radar

Native radar requires the background collector and `WEATHER_DATA_BUCKET`; starting only the local public Flask process does not collect native scans.

NOAA/NWS native Level II reflectivity is collected for **KMPX (Twin Cities)** from NSF Unidata's public real-time chunk and completed-volume archive buckets. KMPX uses its 0.5° base tilt. The VCP scan plan selects the surveillance cut, so brief antenna transitions do not misclassify scans. Only complete lowest-tilt surveillance reflectivity sweeps are published. Split-cut Doppler REF duplicates, higher tilts, incomplete sweeps and missing chunk sequences are excluded. Supplemental low-level surveillance scans are kept when produced; their frequency is controlled by the radar operator.

KMPX has an authenticated minute Scheduler job and a 45-second steady-state work budget (up to 120 seconds for first backfill). The collector checks every minute. It locates the current streaming volume with a 24-byte archive header request, processes new chunks in sequence, saves a partial low-tilt sweep across cold starts, and publishes each completed scan without waiting for the volume to finish. The completed-volume archive fills the preceding two hours and recovers missed streaming data. Both the prepared manifest and public API use scan timestamps to keep every available completed scan within the rolling two-hour window. There is no frame-count cap: 30, 100 or more scans are included when available. Missing source data can leave gaps; the viewer indicates incomplete history. Bounded backfill resumes on later invocations. The public app serves prepared data only and never launches per-visitor collection.

Native super-resolution reflectivity has 250-meter range gates and 0.5° azimuth spacing. These are polar measurements, not 250-meter square geographic pixels; cross-beam resolution worsens with distance. Compressed binary frame packets keep native azimuths and range geometry. The canvas viewer samples the nearest native gate at the current zoom using WGS84 geodesic distances/bearings and standard 4/3-earth beam geometry, without smoothing or averaging. Codes below 10 dBZ/missing/range-folded are transparent. No geographic PNG raster limits the displayed detail.

Reflectivity uses the original continuous COD-style palette: greens through 31.5 dBZ; yellow from about 32 dBZ, then orange and red; magenta/purple from 65 dBZ; and cyan at 80 dBZ and above. The exact original stops are restored, and native 0.5 dBZ codes interpolate between them. Below 10 dBZ/missing/range-folded stays transparent. The continuous color-bar legend matches the renderer. Reflectivity is not an exact surface rain-rate estimate: snow, hail, and non-rain targets can produce echoes too. The API supplies the current gradient for all retained raw scans, so restoring colors does not discard the two-hour history.

Native gates are displayed sharply, without spatial averaging or a display blur. Color interpolation follows each original half-dBZ code; it does not blend neighboring radar cells. Map boundaries remain sharp. All three personal reference markers and their coordinates have been removed from the current radar code.

The map retains its white background, state/county boundaries, no city labels, zoom/pan, and a manual slider on phones and desktop. Zoom can reach level 13. Radar timestamps use Central time. History backfill, gaps and stale scans are flagged. The scan timestamp is its start; the native packet also retains its completion time.

## Satellite

The page reads the public College of DuPage NEXLAB loop for its `local-S_Minnesota` sector and prepares copies of the original GOES-East image bytes in private Cloud Storage. The web service serves the saved images; their colors and annotations are unchanged. Each view contains the latest available 24 images (typically about two hours at five-minute intervals). COD supplies the correctly aligned state and county overlays; city labels are omitted.

The Leaflet viewer uses the source's **native image coordinates**, not a latitude/longitude radar reprojection. This preserves image/overlay alignment and provides pinch zoom, drag to pan, reset view, expand, and a manual slider. The original 1600×900 RGB image and its source annotation are retained. Phones use a taller central view, with the timestamp and Reset/Expand actions in a toolbar below the image; zoom out to see the full sector. Desktop retains a full-width 16:9 image. The surrounding viewer and controls are white. Replacing ground colors with white would alter the RGB product and is not done.

- **True color:** natural daytime cloud/ground appearance; requires daylight.
- **Day Cloud Phase:** daytime cloud-phase RGB; its interpretation depends on sunlight.
- **NT Microphysics:** nighttime RGB for low-cloud/fog and other cloud distinctions; daytime solar reflection affects interpretation.

RGB colors give qualitative cloud clues, not exact cloud heights. All three products are collected every five minutes even without viewers. On opening, the newest image is shown while the remaining loop loads. Already decoded frames are reused on refresh. Radar and satellite history use manual sliders only, with no automatic playback or playback buttons; dragging selects a frame and updates its timestamp. Background refresh preserves a manually selected time while it remains available. Failed images, gaps and stale acquisition times are indicated. Product switches cancel obsolete loads so the old product cannot replace the new one.

## NWS forecast

The collector reads the official MapClick JSON forecast (`FcstType=json`) for 44.9244, -93.4140, using the same source as the linked NWS webpage. The NWS API generates different narrative wording and can select different initial periods even with the same grid update time, so it is not used for this view. This corresponds to the user's [Hopkins forecast](https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414&unit=0&lg=english&FcstType=text&TextType=1). NWS narrative wording is preserved. Each compact row shows the period name, high/low temperature and the complete NWS narrative. Weather icons, the repeated short summary, and separate wind/precipitation-chance footers are omitted to keep the display concise. Wind and precipitation wording supplied in the full narrative is preserved.

NWS source issue time comes from the same MapClick response as its narrative and periods (`creationDate`, not the observation timestamp `creationDateLocal`). Completed periods disappear at both request and browser-render time; the first remaining period comes from the webpage feed. The private collector checks the forecast every five minutes; each successful collection replaces the saved MapClick snapshot, including when the issuance time is unchanged but the initial period has rolled over. The web service reads the saved snapshot. Opening the tab, Refresh, and a five-minute visible-tab refresh read the latest available NWS issuance. This does **not** force NWS to issue new forecasts hourly. Failed refreshes retain already displayed rows with a warning.

The old HRRR/RRFS collector, GRIB dependencies and blend storage code are removed. Only lightweight feed/image collection is scheduled; no numerical weather model or AI computation runs. The compatibility-only airport average API is retained.

## Deploy/update

See [DEPLOYMENT.md](DEPLOYMENT.md). In the existing Google Cloud Shell checkout:

```bash
cd ~/weather-lab
git pull --ff-only
bash deploy.sh weather-lab-20261013-204529
```

The script retires old model, KEVX radar, separate observations, Surface, and separate METAR-cloud Scheduler jobs. It builds the app, creates the private collector/data bucket, and configures **four** authenticated Scheduler jobs: KMPX radar every minute; satellite every five minutes; NWS forecast every five minutes; and the combined station/airport-cloud collector once hourly at :00. Deployment resumes paused jobs and triggers initial collection. Both services can scale to zero. Prepared images expire after one day; live manifests and station history remain. Changes take effect after deployment in authenticated Cloud Shell.

## Checks

```bash
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/native-radar.js
node --check static/cloud-views.js
bash -n deploy.sh
```
