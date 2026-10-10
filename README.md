# Weather Lab

A phone-friendly Twin Cities weather page with six views:

- **Observations:** equal averages of routine KFCM, KMSP and KMIC hourly METARs.
- **Radar:** KMPX native Level II lowest-tilt reflectivity, a two-hour loop, a continuous COD-style reflectivity gradient from 10 dBZ, and a manual timeline.
- **Satellite:** local Central Minnesota GOES-East True Color, Day Cloud Phase, and Nighttime Microphysics, with state/county lines and a manual timeline.
- **Forecast:** the official NWS day/night forecast for Hopkins at **44.9244, -93.4140**, displayed as compact seven-day rows.
- **METAR clouds:** every available regional reporting station, cloud coverage and cloud-base heights, with a searchable layer list.
- **Alternate clouds:** an independent NOAA STAR experiment with day/night cloud RGB, GeoColor and infrared imagery.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:8080. No API keys or model files are needed.

## Observations

Routine METAR reports near :53 (:50–:59) receive the following-hour label: 8:53 p.m. becomes 9 p.m. Special SPECI reports are excluded. In the deployed site, the collector checks at :56, :59 and :03 to catch routine reports and small delays. The browser reads shortly after those times, on opening/returning to the page, or on manual Refresh; it does not poll every few seconds. The report is shown after collection; the label can briefly be ahead of the clock. Missing reports stay missing. The last twelve hourly snapshots are displayed in America/Chicago time.

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

## METAR clouds

The collector downloads Aviation Weather Center's complete METAR XML cache every five minutes and selects the latest available METAR or SPECI per station within 40–50°N, 100–85°W. A bounded API query can truncate the station list, so this tab uses the complete cache with no station-count cap. Reports older than two hours are excluded; reports over 90 minutes old are marked amber. This independent latest-report view does not change the three-station routine hourly observation average.

The white state/county map shows coverage and the lowest reported cloud layer. Tap a marker for every reported layer and its actual observation time, or search the station list. All available regional markers remain present when zooming; only text labels hide at wider zoom levels to reduce overlap. Cloud quantities use METAR codes FEW, SCT, BKN and OVC. Bases are feet **above the airport ground level (AGL)**, not sea level. Reported layers above 12,000 feet are retained. Automated CLR means no clouds detected at or below 12,000 feet; it does not establish that higher clouds exist or are thin. Missing cloud information remains unknown. VV is vertical visibility into an obscuration, not a measured cloud base. See [AWC help](https://aviationweather.gov/help/data/).

## Alternate clouds

This separate viewer reads NOAA/NESDIS/STAR's GOES-19 Upper Mississippi Valley sector. It preserves the original COD Satellite tab, map and products. Choose **Day / night cloud RGB** (Day Cloud Phase in daylight, Nighttime Microphysics after dark), **GeoColor** (daytime natural color and nighttime infrared), or **Infrared cloud tops** (band 13). These products help interpret cloud properties; their colors do not provide exact cloud bases or heights.

The server caches source-page metadata for two minutes on demand. While this tab is visible, the browser checks once per minute and downloads immutable 1200×1200 images directly from NOAA. There is no additional satellite background job or bucket image copy for this experiment. Every available image timestamp in the preceding two hours is included; a manual slider selects the image. Decoded images are reused, and refresh preserves a manually selected time while it remains available.

This viewer uses native image coordinates and NOAA's own baked map/annotations. Its surrounding controls are white, but the RGB ground colors are retained. Matching the radar's geographic grid and custom white ground would require a separate raw-GOES reprojection and cloud-mask pipeline. GeoColor attribution: CIRA / NOAA; imagery/maps: NOAA / NESDIS / STAR.

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

The script retires the old model job and KEVX radar job, removes KEVX live manifests/checkpoints, builds the app, creates a private collector and data bucket, and configures five authenticated Scheduler jobs: KMPX radar every minute; all three original satellite products every five minutes; observations at :56, :59 and :03; NWS forecast every five minutes; regional METAR clouds every five minutes. It also triggers the first backfill. Both services can scale to zero. Prepared image objects are cleaned up after one day; current manifests and map overlays are retained. The viewer retains only the two-hour radar window and latest 24 original satellite frames. Alternate clouds loads NOAA imagery on demand. Cloud changes occur only when this script is run in authenticated Cloud Shell.

## Checks

```bash
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/native-radar.js
node --check static/cloud-views.js
bash -n deploy.sh
```
