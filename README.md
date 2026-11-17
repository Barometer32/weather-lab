# Weather Lab

Personal weather site: https://weather-lab.cloud.run

Current project: `weather-lab-261105-184200-1a9b`, region `us-central1`.
GitHub branch: `rtmetar-default-20261111`.

## Current pages

- **CURRENT** opens first on every visit. Equal averages from KMSP, KFCM and KMIC official :50–:59 METARs, assigned to the following hour. Precise T-remark Celsius readings are averaged before whole-Fahrenheit conversion. Only complete three-airport hours appear in the last-12-hours table. Wind speed includes variable reports; their directions are omitted from the speed-weighted circular direction. Display uses whole mph and eight compass points; 3 mph or less is CALM. Sun angle uses Hopkins coordinates (44.925°N, 93.463°W), NOAA/Meeus apparent solar-centre elevation with refraction, tenths of a degree and one shared server-calibrated clock updated every ten seconds. Fresh network responses calibrate the clock; cached manifests never reset it. The sun angle appears only on CURRENT.
- **METAR** opens CLOUDS, with PLOTS as the other option. CLOUDS retains individual KMSP/KFCM/KMIC with first priority, then KSTP; KSGS appears when space allows. PLOTS replaces the trio with one marker at their geographic centroid, using the exact complete hourly averages from CURRENT, including its calm-wind rule; each timeline frame uses its own matching hour. All other airports retain their plots. The four-hour loop uses each hour's actual reports.
- **RADAR** uses native KMPX Level II lowest-tilt scans and a two-hour timeline.
- **SATELLITE** defaults to Visible (red) Band 02, with Day Cloud Phase and NT Microphysics. The last 24 available source images are retained.
- **FORECAST** uses the NWS Hopkins MapClick text forecast, with its original narrative and issuance time.
- **AIR Q** uses prepared Minnesota AirNow/MPCA source-hour maps.

## Background updates

`weather-lab` serves the pages and prepared data. The private `weather-collector` service prepares data while the site is closed. Six Cloud Scheduler tasks are required:

| Task | Endpoint |
|---|---|
| weather-live-current | /collect/current-hourly |
| weather-live-metar-clouds | /collect/metar-clouds |
| weather-live-radar | /collect/radar-KMPX |
| weather-live-satellite | /collect/satellite |
| weather-live-forecast | /collect/forecast |
| weather-live-air-quality | /collect/air-quality |

CURRENT checks at :00, :02, :04 and every two minutes until all three reports are complete, then skips upstream work until the next hour. METAR checks every two minutes. Forecast checks every five minutes. Other existing schedules are preserved. Page views read saved objects, without triggering collection.

## Operate

From an authenticated Cloud Shell checkout, deploy with:

```bash
bash release-plots.sh
```

Clean obsolete schedules and old deployment versions without a rebuild:

```bash
python3 cleanup_weather_jobs.py --apply --old-revisions
```

Without `--apply`, cleanup is a preview. Cleanup checks the live CURRENT data and all six required job targets, service accounts and enabled states. Only verified Weather Lab-owned jobs outside that set are removed. Unverified jobs are listed and retained. Current/latest deployment revisions and tags referenced by remaining schedules are protected. No extra rollback copies are created. Old experimental source and deployment scripts have been removed.

See [DEPLOYMENT.md](DEPLOYMENT.md) for release details and [THIRD_PARTY.md](THIRD_PARTY.md) for software/data credits.

## Verify

```bash
python3 -m pytest -q
for test in tests/*.test.js; do node "$test" || exit; done
```

`verify_weather_release.py https://weather-lab.cloud.run --all-products` checks CURRENT, METAR PLOTS/CLOUDS, imagery and the other retained products. `metar_history.py` retains the bounded official archive reader used by map recovery. `data-lifecycle.json` and `extend_satellite_lifecycle.py` document and preserve the weather bucket's existing retention rules.
