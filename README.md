# Weather Lab

A responsive Twin Cities weather page with three tabs: combined routine observations, on-demand simplified MPX radar, and a 16-hour HRRR/RRFS blend. No AI API, GPU or training.

## Observations

KFCM, KMSP and KMIC routine METARs near :53 (:50–:59) are labeled with the following hour. SPECI reports are excluded. Equal station weights; small green/amber dots show basic range QA and whether all three sites were used. The sun angle uses Hopkins coordinates without a Hopkins label. Historical values cover 12 hours.

## Radar

MPX N0B 0.5° base reflectivity, all available scans from the previous two hours. White background, county/state boundaries only, no city labels. Manual slider works on mobile and desktop, with play/pause and fullscreen. No radar collection when the tab is closed or the page is hidden; a request already in progress may finish. A displayed radar tab refreshes every five minutes. Images and server calculations are cached.

Echoes below 10 dBZ are transparent. Bands: 10–20 very light, 20–25 light, 25–30 light–moderate, 30–38 moderate, 38–44 moderate–heavy, 44–50 heavy, 50–57 very heavy, 57+ intense. These labels describe echo strength, not measured rain at the ground.

## Forecast

The job checks at :45 UTC and :55 UTC for the same preferred cycle. At 13:45/13:55, it prefers 12Z; at 00:45, it prefers the previous day's 23Z. Model availability is checked through f018 before collecting anything large. If the preferred cycle is late, it searches up to three earlier cycles for the newest complete HRRR/RRFS pair, never mixing initialization times. A stored equal/newer cycle is retained without another large download. Invalid data also retains the previous complete forecast; cycle, publication time, original valid times and stale status remain visible. A late older run can have past rows and less than 16 hours remaining into the future; it is never relabeled as the current cycle.

Forecast hours +2 through +18 produce 17 timestamps over exactly 16 hours. Example: 12Z -> 14Z through 06Z next day. Six equally weighted values (2 models × 3 sites), all from the same cycle and exact valid time. Temperature/dewpoint at 2 m; scalar wind speed at 10 m; gust and surface pressure. Relative humidity is derived consistently from each temperature/dewpoint pair before averaging. Hourly precipitation is deaccumulated per model/site, then averaged; the first row has no precipitation because it is the window start. Amounts are liquid equivalents, not probabilities.

The collector automatically checks RRFS operational and parallel feeds and supports regular and subhourly surface files. For subhourly files it extracts only the exact whole-hour messages. Some parallel subhourly files lack cloud-cover fields: in those cases HRRR-only cloud total/low/mid/high values have explicit provenance and are marked with an asterisk. Regular RRFS files that contain clouds contribute to the blend automatically. No observation bias adjustment or AI is applied.

Only selected GRIB byte ranges are downloaded; servers ignoring Range are rejected. GRIB cycle/valid time, nearest-point distance, core numeric ranges and precipitation monotonicity are validated. All six core contributors are required before publication. Forecast JSON is written atomically and stored in a private Cloud Storage bucket, with separate web-reader and collector identities.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python forecast_worker.py
python app.py
```

Open http://localhost:8080. Until a collection succeeds the Forecast tab shows an honest unavailable state. Local output is `data/forecast.json`, ignored by git. You may explicitly collect a cycle using `python forecast_worker.py --cycle 2026-10-09T10:00:00Z` while that cycle remains on NOAA.

```bash
python -m unittest discover -s tests -v
node --check static/app.js
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for Google Cloud setup and cleanup. Upstream sources and bundled vendor licenses are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
