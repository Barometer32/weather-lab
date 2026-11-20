# Weather Lab deployment

This repository updates the existing project `weather-lab-261105-184200-1a9b` in `us-central1`. Its two Cloud Run services are `weather-lab` and `weather-collector`. It reuses the existing image repository, builder/service accounts, IAM policy, data bucket and billing link.

Use a clean checkout and authenticated Google Cloud Shell:

```bash
bash release-plots.sh
```

The release validates service identities and the six current schedule targets before building. It stages and checks the website, updates the collector, enables the current schedules and waits for prepared weather data. Progress is printed during verification. Website traffic changes only after the staged pages and prepared products pass. The public website retains at least one warm instance. Other resource settings, image retention and weather data are preserved.

The release then verifies the live website and removes obsolete schedules and deployment revisions. No rollback commands, backups or alternate project copies are created. On failure the script stops and prints the failing command; it does not automatically restore an older release.

## Cleanup without deployment

```bash
python3 cleanup_weather_jobs.py --apply --old-revisions
```

The cleanup is scoped to the Weather Lab project and region. It preserves the six named tasks for the METAR averages, METAR maps, radar, satellite, forecast and air quality. Other HTTP schedules qualify for removal only when their Weather Lab name, collector URL, POST method, OIDC audience and service account verify ownership. Each candidate and required schedule is reread immediately before deletion; configuration changes stop cleanup. Unknown ownership is reported and left alone.

Old deployment versions are deleted only after verifying their service's traffic assignments. Versions serving traffic, latest created/ready versions and tags referenced by remaining schedules are protected. Old tags are removed while preserving the current traffic percentages. Current/latest versions cannot all be deleted because Cloud Run requires them. Container registry images, weather data, credentials and billing are outside this cleanup.
