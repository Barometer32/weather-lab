# WEATHER LAB

A phone-friendly Twin Cities weather page with four views:

- **METAR (first/default):** individual airport temperatures/dew points in °F, black wind-flow arrows with speed in mph, and a cloud-ceiling dropdown. Both views have twelve hourly snapshots. KFCM/KMIC/KMSP/KSTP stay independent; KCFE/KFCE and KSGS are excluded.
- **Radar:** KMPX native Level II lowest-tilt reflectivity, a two-hour loop, a continuous COD-style reflectivity gradient from 10 dBZ, and a manual timeline.
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

## Individual airport weather

The Observations tab, metro-average map marker, sun-angle metric and observation browser polling are removed. METAR is the first and initially visible tab, with **METAR plots** selected by default. KFCM, KMIC, KMSP and KSTP keep their own readings, so local temperature/dew-point differences remain visible. No three-station average is generated for the METAR history or map. The opening HTML no longer reads or computes the legacy observation snapshot.

The background METAR collector still performs one AWC bulk download at **:00**, retaining the last twelve routine hourly positions. Each station uses the routine report nearest :53 within :50–:59, labeled with the following hour. The METAR T remark supplies temperature/dew-point precision when available. Existing history remains usable after deployment. The retired observation API is retained for compatibility, but is not accessed by the page.

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

The METAR dropdown switches between **METAR cloud** and **METAR plots** over the original Upper Midwest region (40–50°N, 100–85°W). Both modes share **12 routine hourly positions only**, with no Live position. Each station contributes the downloaded routine METAR closest to :53 within :50–:59, labeled with the following hour; SPECI and five-minute reports are excluded. Temperature/dew point prefer T-remark precision when available, for each station individually. Unknown or absent data stay unknown rather than borrowing an older layer.

The source is one bulk download of `https://aviationweather.gov/data/cache/metars.cache.xml.gz` at **:00**, not station-by-station API requests. There are no additional within-hour source checks, historical API backfills or scheduled retries. Duplicate successful collector calls in the same hour reuse the prepared snapshot. Retained twelve-hour history is filtered to the regional extent, including when migrating from the national version. A brand-new empty data store builds the historical hourly positions over time; existing saved history is preserved. The latest bulk cache supplies only each station's latest report: a delayed routine report or one hidden by a newer SPECI may be unavailable in that hourly pull. Missing hourly reports stay missing until later collections; older reports are never assigned to a new hour. Failed or empty bulk downloads leave the previous snapshot and its check time unchanged.

The browser reads prepared data on opening, manual Refresh and tab return. Both views check the prepared API at :00:30. If that hour's result is still being prepared, bounded saved-data retries wait for up to two minutes, without making source requests. Both maps read the same canonical snapshot. Freshness allows two minutes for collection. Cloud mode shows only the lowest broken/overcast ceiling as an **unboxed number** in rounded thousands of feet AGL, minimum 1: 25,000→25, 9,000→9, 2,200→2, below 1,000→1. Clear/few/scattered and unknown/obscured reports without a known broken/overcast base have no symbol. Each metro airport remains independent in cloud mode, with exact heights and all layers in station popups. KCFE/KFCE and KSGS are permanently excluded from fresh and retained reports, including in both cloud and weather views. CLR does not prove clouds exist above the sensor or measure thickness.

Both views open/reset around the metro at zoom 8.5 on desktops and zoom 9 on narrow screens, with zoom-out access to the same Upper Midwest extent. Only in-view cloud markers and spaced weather plots are constructed. The searchable regional table populates when opened. State boundaries stay at opacity 0.8; METAR county lines are lighter at 0.2 (formerly 0.35). Radar and satellite maps are unchanged.

Weather plots use compact transparent SVGs. Temperature is upper left, dew point lower left, and wind speed is to the right in **mph**, rounded to a whole number. Text is bold with a white outline for contrast over boundaries. The narrow black 18-pixel arrow points **toward where wind is going**, using `(METAR source direction + 180) % 360`; e.g., a north wind points south. The arrow stays centered on the real station coordinates and has a thin white halo. Calm/variable/unknown winds get text instead of an invented direction. There are no location circles or wind barbs. Exact wind source direction, speed and report time remain in station popups.

Decluttering checks conservative bounding rectangles for actual label lengths, the short arrow, text halos and a small gap. Plot glyphs and their collision bounds use an 82% scale; typical two-digit plots fit about 60×38 pixels instead of the old 90×65 spacing; long/negative readings receive more space. More sites appear as zoom permits, without shifting station coordinates or allowing wind arrows/labels to touch. KFCM, KMIC and KMSP have first selection priority; regional anchors follow and KSTP has lower priority. Stations hidden for overlap remain in the searchable list. Legacy saved metro markers are ignored and removed when rebuilding the hourly API response.

The previous fixed METAR map height is restored: **580 px on desktops and 470 px on phones**, with the original heading spacing. The scroll/viewport-driven height resizing is removed. Radar and satellite retain their existing heights and layout. METAR and radar zoom controls move in **0.1-level increments**; satellite buttons also move by 0.1 while its continuous fitting is preserved. The slightly smaller plots let the three focus airports fit at the 8.5 desktop default and allow finer adjustments around the preferred zoom. KSTP cannot take precedence over those three airports.

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

The script retires the old model job, KEVX radar job and separate observations job, removes KEVX manifests/checkpoints, builds the app, creates a private collector and data bucket, and configures four authenticated Scheduler jobs: KMPX radar every minute; all three original satellite products every five minutes; NWS forecast every five minutes; the Upper Midwest METAR job once hourly at :00. The shared job has no automatic retries. Deployment triggers one initial collection; subsequent scheduled pulls run at the top of the hour. Both services can scale to zero. Prepared images are cleaned up after one day; manifests and map overlays are retained. The radar window stays two hours and satellite keeps the latest 24 frames. Cloud changes take effect when the deployment script runs in authenticated Cloud Shell.

## Checks

```bash
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/native-radar.js
node --check static/cloud-views.js
bash -n deploy.sh
```
