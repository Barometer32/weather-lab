#!/usr/bin/env bash
# Replace Models with live three-airport Current; retain the other views/data.
set -euo pipefail
WEATHER_PROJECT="j-weather-261020012817"
WEATHER_REGION="us-central1"
WEATHER_BUCKET="gs://$WEATHER_PROJECT-weather-data"
WEATHER_BRANCH="metar-cloud-history-20261019"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-live-update.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR

echo "Step 1/6: saving settings and stopping model collection."
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/collector-before.yaml"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
WEATHER_JOBS="$(gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(name)')"
WEATHER_SERVICES="$(gcloud run services list --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(metadata.name)')"
while IFS= read -r WEATHER_JOB_PATH; do
  if [[ "${WEATHER_JOB_PATH##*/}" == "weather-live-models" ]]; then
    if [[ "$(gcloud scheduler jobs describe weather-live-models --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == "ENABLED" ]]; then
      gcloud scheduler jobs pause weather-live-models --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
    fi
  fi
done <<< "$WEATHER_JOBS"
gcloud storage buckets describe "$WEATHER_BUCKET" >/dev/null
git clone --quiet --depth=1 --branch "$WEATHER_BRANCH" https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:live-${WEATHER_COMMIT:0:12}"

echo "Step 2/6: building the live Current update."
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi

echo "Step 3/6: updating the collector and two-minute airport checks."
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_CURRENT_ACTION=create
while IFS= read -r WEATHER_JOB_PATH; do
  if [[ "${WEATHER_JOB_PATH##*/}" == "weather-live-current" ]]; then WEATHER_CURRENT_ACTION=update; fi
done <<< "$WEATHER_JOBS"
gcloud scheduler jobs "$WEATHER_CURRENT_ACTION" http weather-live-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='*/2 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/current" --http-method=POST --oidc-service-account-email="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=120s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == "PAUSED" ]]; then
  gcloud scheduler jobs resume weather-live-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
gcloud scheduler jobs run weather-live-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"

echo "Step 4/6: publishing Current and the remaining six tabs."
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/observations" -o "$WEATHER_WORK/current.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,re,sys
from pathlib import Path
work=Path(sys.argv[1]);html=(work/'page.html').read_text()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['current','radar','metar-clouds','satellite','forecast','air-quality']:
    raise SystemExit('The published tab order is incorrect.')
current=html.split('<section id="current"')[1].split('</section>')[0]
satellite=html.split('<section id="satellite"')[1].split('</section>')[0]
if 'id="sun-angle"' not in current or 'sun-angle' in satellite or 'id="history"' in current:
    raise SystemExit('Current/Satellite layout has not updated.')
data=json.loads((work/'current.json').read_text())
if data.get('version')!='madis-five-minute-three-airports-v3' or 'history' in data:
    raise SystemExit('The live Current API is not published yet.')
print('Verified: live Current, Sun on Current only, no Current history or Models tab.')
if data.get('current'):
    print('Mean observation time:',data['current']['observedAt'],'Held:',data['held'])
else:
    print('First source check requested. Waiting for all three valid reports timestamped within 15 minutes of each other.')
PY

echo "Step 5/6: removing the retired model job, worker and prepared model JSON."
while IFS= read -r WEATHER_JOB_PATH; do
  case "${WEATHER_JOB_PATH##*/}" in
    weather-live-models|weather-live-observations)
      gcloud scheduler jobs delete "${WEATHER_JOB_PATH##*/}" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet ;;
  esac
done <<< "$WEATHER_JOBS"
while IFS= read -r WEATHER_SERVICE; do
  if [[ "$WEATHER_SERVICE" == "weather-models" ]]; then
    gcloud run services describe weather-models --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/models-before.yaml"
    gcloud run services delete weather-models --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
  fi
done <<< "$WEATHER_SERVICES"
WEATHER_OBJECTS="$(gcloud storage ls "$WEATHER_BUCKET/live/")"
while IFS= read -r WEATHER_OBJECT; do
  case "$WEATHER_OBJECT" in
    "$WEATHER_BUCKET/live/models.json"|"$WEATHER_BUCKET/live/models-status.json")
      gcloud storage rm "$WEATHER_OBJECT" ;;
  esac
done <<< "$WEATHER_OBJECTS"

echo "Step 6/6: checking the active update schedules."
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nUpdate complete. Refresh your usual J-Weather address.\nService URL: %s\nSource: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
