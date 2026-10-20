#!/usr/bin/env bash
# Add a private model worker and update the existing J-Weather website.
set -euo pipefail
WEATHER_PROJECT="j-weather-261020012817"
WEATHER_REGION="us-central1"
WEATHER_BRANCH="metar-cloud-history-20261019"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-models-update.XXXXXX")"
WEATHER_SCHEDULER="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com"
trap 'echo "Models update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR

echo "Step 1/6: saving the working website settings."
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/collector-before.yaml"
WEATHER_EXISTING_MODEL_SERVICE="$(gcloud run services list --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --filter='metadata.name=weather-models' --format='value(metadata.name)')"
if [[ -n "$WEATHER_EXISTING_MODEL_SERVICE" ]]; then
  gcloud run services describe weather-models --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/models-before.yaml"
fi
git clone --quiet --depth=1 --branch "$WEATHER_BRANCH" https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="${WEATHER_MODELS_IMAGE:-$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:models-${WEATHER_COMMIT:0:12}}"

echo "Step 2/6: building the website and model reader."
if [[ -n "${WEATHER_MODELS_IMAGE:-}" ]]; then
  echo "Reusing previously built image: $WEATHER_IMAGE"
  gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null
elif ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi

echo "Step 3/6: deploying a separate private model worker."
gcloud run deploy weather-models --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --no-allow-unauthenticated --service-account="weather-collector@$WEATHER_PROJECT.iam.gserviceaccount.com" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=1 --timeout=900 --command=gunicorn --args='--bind=0.0.0.0:8080,--workers=1,--threads=1,--timeout=900,collector:app' --quiet
gcloud run services add-iam-policy-binding weather-models --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --member="serviceAccount:$WEATHER_SCHEDULER" --role=roles/run.invoker --quiet >/dev/null
WEATHER_MODEL_URL="$(gcloud run services describe weather-models --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo "Step 4/6: setting hourly background collection at :35."
WEATHER_JOB_ACTION="create"
WEATHER_EXISTING_MODEL_JOB="$(gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --filter="name=projects/$WEATHER_PROJECT/locations/$WEATHER_REGION/jobs/weather-live-models" --format='value(name)')"
if [[ -n "$WEATHER_EXISTING_MODEL_JOB" ]]; then
  WEATHER_JOB_ACTION="update"
  gcloud scheduler jobs describe weather-live-models --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/models-schedule-before.json"
fi
gcloud scheduler jobs "$WEATHER_JOB_ACTION" http weather-live-models --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='35 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_MODEL_URL/collect/models" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER" --oidc-token-audience="$WEATHER_MODEL_URL" --attempt-deadline=900s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-models --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == "PAUSED" ]]; then
  gcloud scheduler jobs resume weather-live-models --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi

echo "Step 5/6: updating the website and requesting the first model run."
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud scheduler jobs run weather-live-models --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"

echo "Step 6/6: verifying the tab order and saved-data API."
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/models" -o "$WEATHER_WORK/models.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,re,sys
from pathlib import Path
work=Path(sys.argv[1]);html=(work/'page.html').read_text()
tabs=re.findall(r'<button role="tab" id="tab-([^"]+)"',html)
if tabs!=['current','radar','metar-clouds','satellite','models','forecast','air-quality']:
    raise SystemExit('The published tab order does not match the update.')
data=json.loads((work/'models.json').read_text())
if 'available' not in data:
    raise SystemExit('The prepared model API is not published yet.')
if data['available']:
    if [h['forecastHour'] for h in data['hours']]!=list(range(2,18)) or data.get('precipitationPeriod')!='preceding-one-hour':
        raise SystemExit('The saved model horizon or precipitation period is incorrect.')
    print('Complete model blend available:',data['cycleTime'])
else:
    print('First model collection requested. Open MODELS for its progress; submission does not confirm a completed forecast.')
print('Verified tabs: CURRENT → RADAR → CLOUDS → SATELLITE → MODELS → FORECAST → Air Quality')
print('Background model checks: hourly at :35. Both models, all three airports, same run; F02–F17.')
PY
printf '\nOpen your usual J-Weather address and refresh.\nService URL: %s\nSource: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
