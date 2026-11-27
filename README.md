# Weather Lab

Personal weather site: https://weather-lab.cloud.run

Current project: `weather-lab-261105-184200-1a9b`, region `us-central1`.
GitHub branch: `rtmetar-default-20261111`.

## Current pages

- **METAR** opens first with PLOTS selected. PLOTS shows individual airport temperatures, dewpoints and mph wind barbs from four hourly METAR batches. CLOUDS shows each airport's sky cover and lowest broken or overcast ceiling. Both maps prioritize KMSP, KFCM and KMIC, followed by KSTP, and reveal nearby airports as zoom makes room.
- **RADAR** uses native KMPX Level II lowest-tilt scans and a two-hour timeline.
- **SATELLITE** defaults to True Color, with Day Cloud Phase and NT Microphysics. The last 24 available source images are retained.
- **FORECAST** shows the NWS Hopkins day/night text forecast, including falling-temperature arrows and targets.
- **AIR Q** uses prepared Minnesota maps from EPA AirNow’s latest and 24-hour combined AQI contour layers. Each source hour appears after its image loads.

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

The retained `/api/current` feed calculates three-airport averages separately from the maps. METAR checks every two minutes. Forecast checks every five minutes. Page views read saved objects without triggering collection.

## Operate

From an authenticated Cloud Shell checkout, deploy with:

```bash
bash release-plots.sh
```

Clean obsolete schedules and old deployment versions without a rebuild:

```bash
python3 cleanup_weather_jobs.py --apply --old-revisions
```

Without `--apply`, cleanup is a preview. Cleanup checks the retained `/api/current` feed and all six required job targets, service accounts and enabled states. Only verified Weather Lab-owned jobs outside that set are removed. Unverified jobs are listed and retained. Current/latest deployment revisions and tags referenced by remaining schedules are protected. No extra rollback copies are created. Old experimental source and deployment scripts have been removed.

See [DEPLOYMENT.md](DEPLOYMENT.md) for release details and [THIRD_PARTY.md](THIRD_PARTY.md) for software/data credits.

## Verify

```bash
python3 -m pytest -q
for test in tests/*.test.js; do node "$test" || exit; done
```

`verify_weather_release.py https://weather-lab.cloud.run --all-products` checks METAR PLOTS/CLOUDS, imagery and the other retained products. `metar_history.py` retains the bounded official archive reader used by map recovery. `data-lifecycle.json` and `extend_satellite_lifecycle.py` document and preserve the weather bucket's existing retention rules.
