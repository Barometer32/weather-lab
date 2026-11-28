# Weather Lab

Personal weather site: https://weather-lab.cloud.run

Current project: `weather-lab-261105-184200-1a9b`, region `us-central1`.
GitHub branch: `rtmetar-default-20261111`.

## Current pages

- **OBSERVATIONS** opens first with the temperature, dewpoint and wind averages for KMSP, KFCM and KMIC, plus the live Hopkins sun angle. The last 12 hours show only hours with complete reports from all three airports. The observations reuse the existing hourly collector.
- **CLOUDS** has its own tab. It shows each eligible airport's sky cover and lowest broken or overcast ceiling, prioritizing KMSP, KFCM and KMIC followed by KSTP where markers crowd. The placement keeps station symbols and ceiling labels clear of one another.
- **RADAR** uses native KMPX Level II lowest-tilt scans and a two-hour timeline.
- **SATELLITE** defaults to True Color, with Day Cloud Phase and NT Microphysics. The last 24 available source images are retained.
- **FORECAST** shows the NWS Hopkins day/night text forecast, including falling-temperature arrows and targets.
- **HOURLY** blends up to 24 hours of NOAA LAMP guidance across KMSP, KFCM and KMIC. Each row uses P01 from the following hour and averages available finite ceiling estimates. The existing forecast job checks for new runs every five minutes.
- **AIR Q** uses prepared Minnesota maps from EPA AirNow’s latest and 24-hour combined AQI contour layers. Each source hour appears after its image loads.

## Background updates

`weather-lab` serves the pages and prepared data. The private `weather-collector` service prepares data while the site is closed. Five Cloud Scheduler tasks are required:

| Task | Endpoint |
|---|---|
| weather-live-metar-clouds | /collect/metar-clouds |
| weather-live-radar | /collect/radar-KMPX |
| weather-live-satellite | /collect/satellite |
| weather-live-forecast | /collect/forecast |
| weather-live-air-quality | /collect/air-quality |

Airport reports for OBSERVATIONS and CLOUDS are checked every two minutes. Forecast checks every five minutes. Page views read saved objects without triggering collection.

## Operate

From an authenticated Cloud Shell checkout, deploy with:

```bash
bash release-plots.sh
```

Clean obsolete schedules and old deployment versions without a rebuild:

```bash
python3 cleanup_weather_jobs.py --apply --old-revisions
```

Without `--apply`, cleanup is a preview. Cleanup verifies the prepared CLOUDS loop, along with all required job targets, service accounts and enabled states. Only verified Weather Lab-owned jobs outside that set are removed. Unverified jobs are listed and retained. Current/latest deployment revisions and tags referenced by remaining schedules are protected. No extra rollback copies are created. Old experimental source and deployment scripts have been removed.

See [DEPLOYMENT.md](DEPLOYMENT.md) for release details and [THIRD_PARTY.md](THIRD_PARTY.md) for software/data credits.

## Verify

```bash
python3 -m pytest -q
for test in tests/*.test.js; do node "$test" || exit; done
```

`verify_weather_release.py https://weather-lab.cloud.run --all-products` checks OBSERVATIONS, CLOUDS, imagery and the other retained products. `metar_history.py` retains the bounded official archive reader used by map recovery. `data-lifecycle.json` and `extend_satellite_lifecycle.py` document and preserve the weather bucket's existing retention rules.
