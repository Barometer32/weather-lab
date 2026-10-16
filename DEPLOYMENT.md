# Fresh METAR project

Use `bash start-fresh.sh` from this branch in authenticated Google Cloud Shell. It creates a new project, links your active billing account, deploys all four views and backfills twelve hours of METARs. See README.md for exact selection rules and setup details.

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

The existing deleted/restored projects are not touched. Only one METAR observation collector is scheduled, at :02 each hour; its data is limited to :50–:59 of the preceding hour. Forecast collection runs at :00 and :30. Radar remains two hours; METAR history remains twelve. The same METAR collector also prepares the Maps tab from saved history; no additional scheduler job or observation download is needed. MADIS and mesonet observations remain disabled.
