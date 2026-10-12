# WEATHER LAB

A phone-friendly Twin Cities weather page with five views:

- **Observations:** routine hourly KFCM, KMSP and KMIC METAR averages, plus twelve routine hourly snapshots.
- **Radar:** KMPX native Level II lowest-tilt reflectivity, a two-hour loop, a continuous COD-style reflectivity gradient from 10 dBZ, and a manual timeline.
- **Satellite:** local Central Minnesota GOES-East True Color, Day Cloud Phase, and Nighttime Microphysics, with state/county lines and a manual timeline.
- **Forecast:** the official NWS day/night forecast for Hopkins at **44.9244, -93.4140**, displayed as compact seven-day rows.
- **METAR:** a dropdown for cloud ceilings or spaced weather plots (°F temperature/dew point, wind in knots), with live cloud data and twelve routine hourly weather snapshots. KCFE remains excluded.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:8080. No API keys or model files are needed.

## Observations

Current conditions and the twelve-hour history use one official routine METAR per station closest to :53 within :50–:59, labeled with the following hour: 8:53 p.m. becomes 9 p.m. SPECI and five-minute reports are excluded. The raw METAR's T remark supplies temperature and dew point in tenths of a degree Celsius when present; otherwise the decoded source values are used. The three values are averaged without intermediate rounding and then converted to Fahrenheit. Main current values require all three stations to pass QA for the same labeled hour. Missing hourly reports are not carried forward; incomplete historical rows remain flagged and can show averages of the available valid contributors.

The observations collector checks NOAA Aviation Weather Center at **:55, :58 and :02**, forcing a fresh request each time so :58 cannot reuse the :55 response. Saved reports are merged by station/timestamp with the newest correction receipt preferred. Failed/empty requests preserve the previous snapshot and its check time. Minute ASOS/MADIS collection has been removed from the main observations job; the independent regional METAR cloud collector remains live. The browser reads saved observations on opening, tab return, manual Refresh and at these three minutes (30 seconds after the collector schedule), without minute polling. Staleness follows the most recent scheduled check with a two-minute grace period, so the normal gap from :02 to :55 is not flagged. Source delays beyond :02 wait for the next scheduled check or a manually triggered collector run. Times use America/Chicago.


Temperature/dew point use equal valid-station weights. Wind speed is averaged separately; direction uses speed-weighted circular averaging and is displayed with eight compass directions. Green QA dots require valid temperature, dew point, and wind from all three stations. Amber dots indicate missing/invalid readings or a failed refresh. Basic QA catches missing/impossible numbers but does not detect all sensor biases. Sun angle is calculated locally in the browser for the existing Hopkins reference.

## Radar

Native radar requires the background collector and `WEATHER_DATA_BUCKET`; starting only the local public Flask process does not collect native scans.

NOAA/NWS native Level II reflectivity is collected for **KMPX (Twin Cities)** from NSF Unidata's public real-time chunk and completed-volume archive buckets. KMPX uses its 0.5° base tilt. The VCP scan plan selects the surveillance cut, so brief antenna transitions do not misclassify scans. Only complete lowest-tilt surveillance reflectivity sweeps are published. Split-cut Doppler REF duplicates, higher tilts, incomplete sweeps and missing chunk sequences are excluded. Supplemental low-level surveillance scans are kept when produced; their frequency is controlled by the radar operator.

KMPX has an authenticated minute Scheduler job and a 45-second steady-state work budget (up to 120 seconds for first backfill). The collector checks every minute. It locates the current streaming volume with a 24-byte archive header request, processes new chunks in sequence, saves a partial low-tilt sweep across cold starts, and publishes each completed scan without waiting for the volume to finish. The completed-volume archive fills the preceding two hours and recovers missed streaming data. Both the prepared manifest and public API use scan timestamps to keep every available completed scan within the rolling two-hour window. There is no frame-count cap: 30, 100 or more scans are included when available. Missing source data can leave gaps; the viewer indicates incomplete history. Bounded backfill resumes on later invocations. The public app serves prepared data only and never launches per-visitor collection.

Native super-resolution reflectivity has 250-meter range gates and 0.5° azimuth spacing. These are polar measurements, not 250-meter square geographic pixels; cross-beam resolution worsens with distance. Compressed binary frame packets keep native azimuths and range geometry. The canvas viewer samples the nearest native gate at the current zoom using WGS84 geodesic distances/bearings and standard 4/3-earth beam geometry, without smoothing or averaging. The 10 dBZ cutoff and approved continuous COD-style palette are preserved; codes below 10 dBZ/missing/range-folded are transparent. No geographic PNG raster limits the displayed detail.

The map retains its white background, state/county boundaries, no city labels, zoom/pan, and a manual slider on phones and desktop. Zoom can reach level 13. Radar timestamps use Central time. History backfill, gaps and stale scans are flagged. The scan timestamp is its start; the native packet also retains its completion time.

## Satellite

The page reads the public College of DuPage NEXLAB loop for its `local-S_Minnesota` sector and prepares copies of the original GOES-East image bytes in private Cloud Storage. The web service serves the saved images; their colors and annotations are unchanged. Each view contains the latest available 24 images (typically about two hours at five-minute intervals). COD supplies the correctly aligned state and county overlays; city labels are omitted.

The Leaflet viewer uses the source's **native image coordinates**, not a latitude/longitude radar reprojection. This preserves image/overlay alignment and provides pinch zoom, drag to pan, reset view, expand, and a manual slider. The original 1600×900 RGB image and its source annotation are retained. Phones use a taller central view, with the timestamp and Reset/Expand actions in a toolbar below the image; zoom out to see the full sector. Desktop retains a full-width 16:9 image. The surrounding viewer and controls are white. Replacing ground colors with white would alter the RGB product and is not done.

- **True color:** natural daytime cloud/ground appearance; requires daylight.
- **Day Cloud Phase:** daytime cloud-phase RGB; its interpretation depends on sunlight.
- **NT Microphysics:** nighttime RGB for low-cloud/fog and other cloud distinctions; daytime solar reflection affects interpretation.

RGB colors give qualitative cloud clues, not exact cloud heights. All three products are collected every five minutes even without viewers. On opening, the newest image is shown while the remaining loop loads. Already decoded frames are reused on refresh. Radar and satellite history use manual sliders only, with no automatic playback or playback buttons; dragging selects a frame and updates its timestamp. Background refresh preserves a manually selected time while it remains available. Failed images, gaps and stale acquisition times are indicated. Product switches cancel obsolete loads so the old product cannot replace the new one.

## METAR clouds and weather plots

The METAR dropdown switches between **METAR cloud** and **METAR plots** over the same region (40–50°N, 100–85°W). Both views check prepared data every minute. AWC's complete current cache supplies regional routine/SPECI observations; direct NOAA MADIS supplies newer five-minute weather/cloud reports where available. The regional METAR collector caches MADIS decoding and reuses conditional downloads; the main hourly observations collector uses AWC only. A cloud field omitted from a rapid report does not erase the latest actual cloud report; cloud and weather observation times remain distinct. A new full METAR with unknown cloud information remains unknown. Individual live station reports older than 90 minutes disappear. Source latency remains possible.

Cloud mode has **12 hourly positions followed by Live**; weather plots have **12 hourly positions only**. Hourly snapshots preserve one routine METAR per station closest to :53 within :50–:59, exclude SPECI/rapid reports, and label the following hour. Initial deployment backfills thirteen hours, including temperature/dew point/wind fields. Later runs merge bounded overlap queries no more often than every fifteen minutes, plus :56/:59/:03 rechecks; ordinary minute updates only check current feeds. AWC capped responses are split and spaced. History and live source timestamps are never relabeled as newly observed. Manual hour selection is preserved across background updates.

Cloud mode shows only the lowest broken/overcast ceiling number in thousands of feet AGL, rounded with a minimum of 1 (25,000→25, 9,000→9, 2,200→2, below 1,000→1). Ceiling numbers have no background boxes. Clear/few/scattered, unknown and obscured reports without a known broken/overcast base have no cloud-map symbol. Only ceiling stations appear in the cloud list, with exact heights and all layers in the popup. KCFE is permanently excluded. CLR does not prove clouds exist above the sensor or measure thickness.

Weather plots use transparent SVG station models with temperature and dew point in Fahrenheit beside a sky-cover circle and wind staff/barbs. The circle reflects the greatest reported layer coverage. Wind staffs point toward the source direction; short/full barbs indicate 5/10 knots and pennants 50 knots, with speed rounded to the nearest 5 knots. Calm uses an outer ring; variable or unknown direction is labeled instead of inventing a staff direction. Individual values come from the routine METAR, converted to Fahrenheit. Station locations do not move. A closer 90×65-pixel screen-space spacing rule hides overlapping plots as the view zooms out and reveals more as it zooms in; Mankato (KMKT), Redwood Falls (KRWF) and regional anchors have priority. All stations remain available in the searchable list. KFCM/KMSP/KMIC are replaced by one fixed **Metro average** plot near their approximate equal-distance center. Metro values use the corresponding routine three-station average from the main hourly history. Its open location circle does not claim averaged sky coverage. Celsius values are averaged before Fahrenheit conversion, speed is scalar-averaged, and direction is speed-weighted circular. The hourly metro plot requires all three valid routine sites regardless of zoom. Main current conditions use the same routine hourly selection and T-remark precision.

Manual timelines are half-width above 600px and full-width on phones.

## NWS forecast

The collector reads the official MapClick JSON forecast (`FcstType=json`) for 44.9244, -93.4140, using the same source as the linked NWS webpage. The NWS API generates different narrative wording and can select different initial periods even with the same grid update time, so it is not used for this view. This corresponds to the user's [Hopkins forecast](https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414&unit=0&lg=english&FcstType=text&TextType=1). NWS narrative wording is preserved. Each compact row shows the period name, high/low temperature and the complete NWS narrative. Weather icons, the repeated short summary, and separate wind/precipitation-chance footers are omitted to keep the display concise. Wind and precipitation wording supplied in the full narrative is preserved.

NWS source issue time comes from the same MapClick response as its narrative and periods (`creationDate`, not the observation timestamp `creationDateLocal`). Completed periods disappear at both request and browser-render time; the first remaining period comes from the webpage feed. The private collector checks the forecast every five minutes; each successful collection replaces the saved MapClick snapshot, including when the issuance time is unchanged but the initial period has rolled over. The web service reads the saved snapshot. Opening the tab, Refresh, and a five-minute visible-tab refresh read the latest available NWS issuance. This does **not** force NWS to issue new forecasts hourly. Failed refreshes retain already displayed rows with a warning.

The old HRRR/RRFS collector, GRIB dependencies and blend storage code are removed. Only lightweight feed/image collection is scheduled; no numerical weather model or AI computation runs. Observation selection, averaging and QA are preserved.

## Deploy/update

See [DEPLOYMENT.md](DEPLOYMENT.md). In the existing Google Cloud Shell checkout:

```bash
cd ~/weather-lab
git pull --ff-only
bash deploy.sh weather-lab-511113
```

The script retires the old model job and KEVX radar job, removes KEVX live manifests/checkpoints, builds the app, creates a private collector and data bucket, and configures five authenticated Scheduler jobs: KMPX radar every minute; all three original satellite products every five minutes; observations at :55/:58/:02; NWS forecast every five minutes; both regional METAR views every minute. It also triggers the first backfill. Both services can scale to zero. Prepared image objects are cleaned up after one day; current manifests and map overlays are retained. The viewer retains only the two-hour radar window and latest 24 original satellite frames. Cloud changes occur only when this script is run in authenticated Cloud Shell.

## Checks

```bash
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/native-radar.js
node --check static/cloud-views.js
bash -n deploy.sh
```
