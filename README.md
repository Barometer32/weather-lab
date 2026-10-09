# Weather Lab

A phone-friendly Twin Cities weather page with four views:

- **Observations:** equal averages of routine KFCM, KMSP and KMIC hourly METARs.
- **Radar:** MPX 0.5° base reflectivity, a two-hour loop, a continuous COD-style reflectivity gradient from 10 dBZ, and a manual timeline.
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

## Observations

Routine METAR reports near :53 (:50–:59) receive the following-hour label: 8:53 p.m. becomes 9 p.m. Special SPECI reports are excluded. In the deployed site, the collector checks at :56, :59 and :03 to catch routine reports and small delays. The browser reads shortly after those times, on opening/returning to the page, or on manual Refresh; it does not poll every few seconds. The report is shown after collection; the label can briefly be ahead of the clock. Missing reports stay missing. The last twelve hourly snapshots are displayed in America/Chicago time.

Temperature/dew point use equal valid-station weights. Wind speed is averaged separately; direction uses speed-weighted circular averaging and is displayed with eight compass directions. Green QA dots require valid temperature, dew point, and wind from all three stations. Amber dots indicate missing/invalid readings or a failed refresh. Basic QA catches missing/impossible numbers but does not detect all sensor biases. Sun angle is calculated locally in the browser for the existing Hopkins reference.

## Radar

NWS MPX N0B imagery is obtained through Iowa Environmental Mesonet. All available scans in the previous two hours are included. The minimum is 10 dBZ. Indexed data values, not RGB colors, determine echo colors. The gradient follows the supplied COD reference: dark-to-bright green, yellow/orange/red, then magenta/pale purple/cyan. Each native 0.5 dBZ code retains a distinct interpolated color through most of the range; 80+ dBZ uses cyan. The renderer keeps the original IEM raster dimensions, projects rows using nearest-source pixels, and does not antialias or blend adjacent echoes. The browser displays the radar layer with nearest-neighbor pixel scaling. Values below 10 dBZ remain hidden. These are colored Level III image cells, not untouched Level II radial samples; the upstream image generation still sets the effective display resolution.

The map has a white background, state/county boundaries, no city labels, play/pause, previous/next, speed selection, zoom/pan, and a manual slider on both phones and desktop. Scan gaps or stale images are flagged.

## Satellite

The page reads the public College of DuPage NEXLAB loop for its `local-S_Minnesota` sector and prepares copies of the original GOES-East image bytes in private Cloud Storage. The web service serves the saved images; their colors and annotations are unchanged. Each view contains the latest available 24 images (typically about two hours at five-minute intervals). COD supplies the correctly aligned state and county overlays; city labels are omitted.

The Leaflet viewer uses the source's **native image coordinates**, not a latitude/longitude radar reprojection. This preserves image/overlay alignment and provides pinch zoom, drag to pan, reset view, expand, play/pause, speed control, and a manual slider. The original 1600×900 RGB image and its source annotation are retained. Phones use a taller central view, with the timestamp and Reset/Expand actions in a toolbar below the image; zoom out to see the full sector. Desktop retains a full-width 16:9 image. The surrounding viewer and controls are white. Replacing ground colors with white would alter the RGB product and is not done.

- **True color:** natural daytime cloud/ground appearance; requires daylight.
- **Day Cloud Phase:** daytime cloud-phase RGB; its interpretation depends on sunlight.
- **NT Microphysics:** nighttime RGB for low-cloud/fog and other cloud distinctions; daytime solar reflection affects interpretation.

RGB colors give qualitative cloud clues, not exact cloud heights. All three products are collected every five minutes even without viewers. On opening, the newest image is shown while the remaining loop loads. Already decoded frames are reused on refresh; switching tabs or hiding the page pauses animation. Failed images, gaps and stale acquisition times are indicated. Product switches cancel obsolete loads so the old product cannot replace the new one.

## NWS forecast

The backend discovers the forecast endpoint from `https://api.weather.gov/points/44.9244,-93.4140` and reads the official seven-day day/night point forecast. This corresponds to the user's [Hopkins forecast](https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414&unit=0&lg=english&FcstType=text&TextType=1). NWS narrative wording is preserved. Each compact row shows the period name, high/low temperature and the complete NWS narrative. Weather icons, the repeated short summary, and separate wind/precipitation-chance footers are omitted to keep the display concise. Wind and precipitation wording supplied in the full narrative is preserved.

NWS source issue time appears separately from request time. Completed periods disappear; the current period remains. The private collector checks the forecast every five minutes; point mapping is rechecked daily. The web service reads the saved snapshot. Opening the tab, Refresh, and a five-minute visible-tab refresh read the latest available NWS issuance. This does **not** force NWS to issue new forecasts hourly. Failed refreshes retain already displayed rows with a warning.

The old HRRR/RRFS collector, GRIB dependencies and blend storage code are removed. Only lightweight feed/image collection is scheduled; no numerical weather model or AI computation runs. Observation selection, averaging and QA are preserved.

## Deploy/update

See [DEPLOYMENT.md](DEPLOYMENT.md). In the existing Google Cloud Shell checkout:

```bash
cd ~/weather-lab
git pull --ff-only
bash deploy.sh weather-lab-511113
```

The script retires the old model job, builds the app, creates a private collector and data bucket, and configures four authenticated Scheduler jobs: radar every two minutes; all three satellite products every five minutes; observations at :56, :59 and :03; NWS forecast every five minutes. It also triggers the first backfill. Both services can scale to zero. Prepared image objects are cleaned up after one day; current manifests and map overlays are retained. The viewer retains only the two-hour radar window and latest 24 satellite frames. Cloud changes occur only when this script is run in authenticated Cloud Shell.

## Checks

```bash
python -m unittest discover -s tests -v
node --check static/app.js
bash -n deploy.sh
```
