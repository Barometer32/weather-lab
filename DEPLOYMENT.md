# Fresh METAR project

The `restore-no-ai-20261017` branch restores the latest five weather views: Observations, Maps, Radar, Satellite, and the official NWS Forecast. Experimental forecasting, model files, training jobs, and their API/viewer are removed from this branch.

Use `bash start-fresh.sh` when creating a new project. It links your active billing account, deploys the site and backfills twelve hours of METARs. After reopening a closed billing account, start this restoration with a separate state file to avoid resuming a deleted project:

```bash
WEATHER_STATE_FILE="$HOME/weather-lab-no-ai-project.txt" \
  WEATHER_BUILD_MODE=cloudbuild bash start-fresh.sh
```

If setup fails, rerun the same command with the same state file. It saves and reuses the project ID in `$HOME/weather-lab-no-ai-project.txt`; do not delete this file to retry.

To display the current site URL:

```bash
gcloud run services describe weather-lab \
  --project="$(cat "$HOME/weather-lab-no-ai-project.txt")" \
  --region=us-central1 --format='value(status.url)'
```

To inspect a failed one-time import:

```bash
gcloud run jobs executions list \
  --job=weather-metar-backfill \
  --project="$(cat "$HOME/weather-lab-no-ai-project.txt")" \
  --region=us-central1
```

The existing deleted/restored projects are not touched. Only one METAR observation collector is scheduled, at :02 each hour; its data is limited to :50–:59 of the preceding hour. Forecast collection runs at :00 and :30. Radar remains two hours; METAR history remains twelve. The same METAR collector also prepares Maps from saved reports. MADIS and mesonet observations remain disabled. No experimental forecast processing or training is deployed.

The wider-region upgrade rebuilds twelve hours of airport history once. Station collection has a fifteen-minute request deadline to allow this migration; normal runs still fetch only one hour at :02. The browser preloads and caches views; the public service can still scale to zero.
