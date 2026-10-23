#!/usr/bin/env bash
# Update only the running app images and the METAR retry schedule.
set -euo pipefail
WEATHER_PROJECT="${1:-j-weather-261020012817}"
WEATHER_REGION=us-central1
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-metar-retries.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR

echo 'Step 1/4: saving the running services and METAR schedule.'
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/collector-before.yaml"
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/metar-job-before.json"
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:metar-retries-${WEATHER_COMMIT:0:12}"

echo 'Step 2/4: building and updating the collector and website.'
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo 'Step 3/4: enabling two-minute catch-up checks and requesting an update now.'
gcloud scheduler jobs update http weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='*/2 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/metar-clouds" --http-method=POST --oidc-service-account-email="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
gcloud scheduler jobs run weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"

echo 'Step 4/4: verifying the updated page and schedule.'
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_WEB_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK/page.html" <<'PY'
from pathlib import Path
import sys
html=Path(sys.argv[1]).read_text()
if '/static/cloud-views.js?v=airport-hourly-' not in html or 'rechecks every two minutes through :20' not in html:
    raise SystemExit('The retry-aware page is not published yet.')
print('Verified retry-aware METAR page.')
PY
gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='yaml(name,schedule,state)'
printf '\nMETAR retries published. An immediate collection was requested; this does not confirm that NOAA has delivered the reports yet.\nRefresh your usual J-Weather address.\nService URL: %s\nSaved settings: %s\n' "$WEATHER_WEB_URL" "$WEATHER_WORK"
