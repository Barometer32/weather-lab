# WEATHER LAB

A phone-friendly Twin Cities weather page with four views:

- **Observations (first/default):** fresh individual station plots from IEM airport, road-weather, agricultural and other networks across the Upper Midwest. Temperature/dew point in °F and wind-flow arrows/speed in mph. Latest reports plus twelve hourly snapshots; zoom in to reveal more plots. The dropdown retains routine hourly airport cloud ceilings. KCFE/KFCE and KSGS remain excluded.
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

## Station observations

The default **All station plots** view reads IEM's openly available `/api/1/currents.json?state=XX` bulk feeds for MN, WI, IA, ND, SD, NE, IL, MI, IN, OH, KS and MO. Collection is every five minutes, with three concurrent upstream requests at most, independent of visitor count. Only sites inside 40–50°N / 100–85°W with recent temperature, dew point or wind are plotted. Rain/river-only sites have no weather plot. This is the available regional IEM network collection, not every restricted MADIS or private station.

`tmpf`/`dwpf` are source Fahrenheit values; `sknt` is converted from knots to mph. Air temperature is used, never road-surface temperature. Missing/nonfinite/impossible values, invalid coordinates, future reports and reports older than 90 minutes are filtered. Dew points above temperature by more than 1°F are omitted. These are range/age checks, **not full MADIS quality control**. Each popup/list entry identifies the station network and actual report time. The list can search station ID, name or network. Network-qualified keys keep duplicate IDs distinct. Each airport retains its own values. Unknown wind directions remain unknown; only explicit VRB reports are labeled variable.

The collector atomically saves `live/station-plots.json`. Failed state requests are listed, and only still-recent values from those failed states can remain. Total failure leaves the prior object untouched. The public API never initiates collection when using the prepared bucket and removes expired latest reports on every read. History stores the last collected report in each completed hourly interval plus a pending next interval, retaining twelve completed hourly frames and a separate latest view. No historical source query runs: a fresh installation builds history over time. Missing hours remain empty. The browser checks prepared observations every five minutes while this view is visible, on opening and on manual Refresh; zoom/pan makes no source requests.

The **METAR cloud** dropdown independently retains NOAA AWC routine hourly airport data and its twelve-position slider. It selects reports nearest :53 within :50–:59 and labels the following hour, using available T-remark precision. Its hourly Scheduler job has two bounded retries for transient startup/collection failures. Both views retain their selected historical time when refreshed. The old metro-average observation API is compatibility-only and is not accessed by the page.

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

The script retires the old model job, KEVX radar job, separate observations job and former Surface job. It builds the app, creates the private collector/data bucket, and configures **five** authenticated Scheduler jobs: KMPX radar every minute; satellite every five minutes; NWS forecast every five minutes; fresh station plots every five minutes; and Upper Midwest airport METAR clouds once hourly at :00 with two bounded retries. Deployment resumes paused jobs and triggers initial collection. Both services can scale to zero. Prepared images expire after one day; live manifests and station history are retained. The radar window stays two hours and satellite keeps the latest 24 frames. Changes take effect after deployment in authenticated Cloud Shell.

## Checks

```bash
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/native-radar.js
node --check static/cloud-views.js
bash -n deploy.sh
```
