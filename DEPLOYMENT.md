# Fresh METAR project

Use `bash start-fresh.sh` only when creating a new project. It links your active billing account, deploys the site and backfills twelve hours of METARs. For this existing site's AI experiment, switch to `ai-forecast-20261016` and run `WEATHER_BUILD_MODE=cloudbuild bash deploy.sh weather-metar-261016-114317` in authenticated Cloud Shell. The trained pilot model is included, so no first-run training job is required. See README.md for selection rules and model limitations.

If setup fails, rerun the same script. It saves and reuses the project ID in `$HOME/weather-lab-metar-project.txt`; do not delete this file to retry.

To display the current site URL:

```bash
gcloud run services describe weather-lab \
  --project="$(cat "$HOME/weather-lab-metar-project.txt")" \
  --region=us-central1 --format='value(status.url)'
```

To inspect a failed one-time import:

```bash
gcloud run jobs executions list \
  --job=weather-metar-backfill \
  --project="$(cat "$HOME/weather-lab-metar-project.txt")" \
  --region=us-central1
```

The existing deleted/restored projects are not touched. Only one METAR observation collector is scheduled, at :02 each hour; its data is limited to :50–:59 of the preceding hour. Forecast collection runs at :00 and :30. Radar remains two hours; METAR history remains twelve. The same METAR collector also prepares Maps and experimental AI Forecast from saved reports; no additional scheduled collection is needed. MADIS and mesonet observations remain disabled. Optional retraining uses `bash train-ai.sh weather-metar-261016-114317`; this is a manual, bounded CPU job, not a step required for the initial deployment. Its progress appears in the AI Forecast tab after the training container starts.

The wider-region upgrade rebuilds twelve hours of airport history once. Station collection has a fifteen-minute request deadline to allow this migration; normal runs still fetch only one hour at :02. The browser preloads and caches views; the public service can still scale to zero.
