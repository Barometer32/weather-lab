#!/usr/bin/env bash
# Update the source-hour Air Q archive to the existing J-Weather project.
set -euo pipefail
WEATHER_PROJECT="${1:-j-weather-261020012817}"
WEATHER_REGION=us-central1
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-airq.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR

echo 'Step 1/5: saving the running service and schedule settings.'
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/collector-before.yaml"
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
WEATHER_COLLECTOR_SA="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.serviceAccountName)')"
test -n "$WEATHER_COLLECTOR_SA"
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:airq-${WEATHER_COMMIT:0:12}"

echo 'Step 2/5: building the update and publishing the collector.'
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo 'Step 3/5: preparing the latest statewide Air Q map now.'
gcloud run jobs deploy weather-airq-prepare --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --command=python --args=air_quality.py --tasks=1 --parallelism=1 --cpu=1 --memory=1Gi --max-retries=0 --task-timeout=300s --quiet
gcloud run jobs execute weather-airq-prepare --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait

echo 'Step 4/5: scheduling source checks at :00 and :30 and setting snapshot retention.'
WEATHER_ACTION="$(python3 - "$WEATHER_WORK/jobs-before.json" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1]))
print('update' if any(row['name'].endswith('/weather-live-air-quality') for row in rows) else 'create')
PY
)"
gcloud scheduler jobs "$WEATHER_ACTION" http weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='0,30 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/air-quality" --http-method=POST --oidc-service-account-email="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=2 --min-backoff=120s --max-backoff=600s --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
gcloud storage buckets update "gs://$WEATHER_PROJECT-weather-data" --project="$WEATHER_PROJECT" --lifecycle-file="$WEATHER_WORK/source/data-lifecycle.json"

echo 'Step 5/5: publishing the page and verifying the captured history.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_WEB_URL/" -o "$WEATHER_WORK/page.html"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_WEB_URL/api/air-quality" -o "$WEATHER_WORK/airq.json"
python3 - "$WEATHER_WORK" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1]);html=(work/'page.html').read_text();data=json.loads((work/'airq.json').read_text())
if '>AIR Q</button>' not in html or '/static/air-quality-views.js?v=airq-v2' not in html or 'id="metar-timeline-description"' in html:
    raise SystemExit('The AIR Q page or METAR heading cleanup is not published yet.')
if not data.get('frames') or data.get('version')!='mn-region-v2' or data.get('timeBasis')!='source':
    raise SystemExit('No statewide Air Q map is ready yet.')
if any(frame.get('time')!=frame.get('sourceTime') for frame in data['frames']):
    raise SystemExit('The AIR Q slider is not using source data times yet.')
print(f"Verified {len(data['frames'])}/12 saved Air Q data hours.")
PY
gcloud scheduler jobs describe weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='yaml(name,schedule,state)'
printf '\nAIR Q is ready. History uses twelve source data hours; unchanged half-hour checks do not add duplicate frames.\nRefresh your usual J-Weather address.\nService URL: %s\nSaved settings: %s\n' "$WEATHER_WEB_URL" "$WEATHER_WORK"
