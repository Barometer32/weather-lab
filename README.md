# Weather Lab

A phone-friendly Twin Cities weather page with four views:

- **Observations:** equal averages of routine KFCM, KMSP and KMIC hourly METARs.
- **Radar:** MPX 0.5° base reflectivity, a two-hour loop, eight simplified colors, and a manual timeline.
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

Routine METAR reports near :53 (:50–:59) receive the following-hour label: 8:53 p.m. becomes 9 p.m. Special SPECI reports are excluded. The report is shown once received; the label can briefly be ahead of the clock. Missing reports stay missing. The last twelve hourly snapshots are displayed in America/Chicago time.

Temperature/dew point use equal valid-station weights. Wind speed is averaged separately; direction uses speed-weighted circular averaging and is displayed with eight compass directions. Green QA dots require valid temperature, dew point, and wind from all three stations. Amber dots indicate missing/invalid readings or a failed refresh. Basic QA catches missing/impossible numbers but does not detect all sensor biases. Sun angle is calculated locally in the browser for the existing Hopkins reference.

## Radar

NWS MPX N0B imagery is obtained through Iowa Environmental Mesonet. All available scans in the previous two hours are included. The minimum is 10 dBZ. Indexed data values, not RGB colors, determine echo classes. Antialiasing smooths the display while retaining the source echo footprint and hiding values below 10 dBZ. Echo labels approximate intensity, not measured rainfall reaching the ground.

The map has a white background, state/county boundaries, no city labels, play/pause, previous/next, speed selection, zoom/pan, and a manual slider on both phones and desktop. Scan gaps or stale images are flagged.

## Satellite

The page reads the public College of DuPage NEXLAB loop for its `local-S_Minnesota` sector and loads the original GOES-East images directly from COD. Each view contains the latest available 24 images (typically about two hours at five-minute intervals). COD supplies the correctly aligned state and county overlays; city labels are omitted.

The Leaflet viewer uses the source's **native image coordinates**, not a latitude/longitude radar reprojection. This preserves image/overlay alignment and provides pinch zoom, drag to pan, reset view, expand, play/pause, speed control, and a manual slider. The original 1600×900 RGB image and its source annotation are retained. The surrounding viewer and controls are white. Replacing ground colors with white would alter the RGB product and is not done.

- **True color:** natural daytime cloud/ground appearance; requires daylight.
- **Day Cloud Phase:** daytime cloud-phase RGB; its interpretation depends on sunlight.
- **NT Microphysics:** nighttime RGB for low-cloud/fog and other cloud distinctions; daytime solar reflection affects interpretation.

RGB colors give qualitative cloud clues, not exact cloud heights. Images load only while the Satellite tab is opened; switching tabs or hiding the page pauses animation. Failed images, gaps and stale acquisition times are indicated. Product switches cancel obsolete loads so the old product cannot replace the new one.

## NWS forecast

The backend discovers the forecast endpoint from `https://api.weather.gov/points/44.9244,-93.4140` and reads the official seven-day day/night point forecast. This corresponds to the user's [Hopkins forecast](https://forecast.weather.gov/MapClick.php?lat=44.9244&lon=-93.414&unit=0&lg=english&FcstType=text&TextType=1). NWS narrative wording is preserved. Each compact row shows the period name, high/low temperature and the complete NWS narrative. Weather icons, the repeated short summary, and separate wind/precipitation-chance footers are omitted to keep the display concise. Wind and precipitation wording supplied in the full narrative is preserved.

NWS source issue time appears separately from request time. Completed periods disappear; the current period remains. Upstream JSON is cached five minutes per web instance; point mapping is rechecked daily. Opening the tab, Refresh, and a five-minute visible-tab refresh read the latest available NWS issuance. This does **not** force NWS to issue new forecasts hourly. Failed refreshes retain already displayed rows with a warning.

The old HRRR/RRFS collector, GRIB dependencies and blend storage code are removed. No scheduled forecast task is necessary. Observation/radar behavior is preserved.

## Deploy/update

See [DEPLOYMENT.md](DEPLOYMENT.md). In the existing Google Cloud Shell checkout:

```bash
cd ~/weather-lab
git pull --ff-only
bash deploy.sh weather-lab-511113
```

The script deletes Weather Lab's retired `weather-hourly` scheduler and `weather-forecast` collector job, deploys the web app, and removes its obsolete forecast object and empty forecast bucket. It does not create replacement scheduled jobs. Cloud changes occur only when this script is run in authenticated Cloud Shell.

## Checks

```bash
python -m unittest discover -s tests -v
node --check static/app.js
bash -n deploy.sh
```
