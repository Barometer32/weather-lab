#!/usr/bin/env bash
# Replace the METAR map with rolling MADIS conditions inside ten miles.
set -euo pipefail
WEATHER_PROJECT="j-weather-261020012817"
WEATHER_REGION="us-central1"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-local-current.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR

echo "Step 1/5: checking J-Weather and saving current settings."
test "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" = ACTIVE
test "$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)')" = True
gcloud config set project "$WEATHER_PROJECT"
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1]);spec=json.loads((work/'collector-before.json').read_text())['spec']['template']['spec']
env={entry['name']:entry.get('value','') for entry in spec['containers'][0].get('env',[])}
(work/'bucket.txt').write_text(env['WEATHER_DATA_BUCKET'])
(work/'collector-sa.txt').write_text(spec['serviceAccountName'])
jobs=json.loads((work/'jobs-before.json').read_text())
(work/'current-action.txt').write_text('update' if any(j['name'].rsplit('/',1)[-1]=='weather-live-current' for j in jobs) else 'create')
(work/'retired-jobs.txt').write_text('\n'.join(j['name'].rsplit('/',1)[-1] for j in jobs if j['name'].rsplit('/',1)[-1] in {'weather-live-metar-clouds','weather-live-madis','weather-live-observations'}))
PY
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket.txt")"
WEATHER_COLLECTOR_SA="$(cat "$WEATHER_WORK/collector-sa.txt")"
test -n "$WEATHER_BUCKET"
test -n "$WEATHER_COLLECTOR_SA"
gcloud storage buckets describe "gs://$WEATHER_BUCKET" >/dev/null
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:local-${WEATHER_COMMIT:0:12}"

echo "Step 2/5: building the local Current page and collector."
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --memory=2Gi --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo "Step 3/5: collecting current local stations before publishing."
gcloud run jobs deploy weather-current-start --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args=local_current.py --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=600s --quiet
if ! gcloud run jobs execute weather-current-start --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait; then
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="weather-current-start"' --project="$WEATHER_PROJECT" --freshness=30m --limit=25 --format='value(textPayload,jsonPayload.message)'
  exit 1
fi
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/observations" -o "$WEATHER_WORK/current.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,re,sys
from pathlib import Path
work=Path(sys.argv[1]);page=(work/'page.html').read_text();data=json.loads((work/'current.json').read_text())
if re.findall(r'<button role="tab" id="tab-([^"]+)"',page)!=['current','radar','satellite','forecast','air-quality']:
    raise SystemExit('Expected Current, Radar, Satellite, Forecast and Air Quality only.')
if data.get('version')!='madis-hopkins-ten-mile-v1' or not data.get('current'):
    raise SystemExit('The local MADIS average is not ready. Previous settings remain saved.')
print('Verified local Current with',data['current']['stationCount'],'contributing stations.')
print('Average observation time:',data['current']['observedAt'])
for row in data['candidate']['stations']:print(row['displayName'],row['network'],row['distanceMiles'],'miles',row['status'])
PY

echo "Step 4/5: enabling two-minute checks for new five-minute observations."
WEATHER_CURRENT_ACTION="$(cat "$WEATHER_WORK/current-action.txt")"
gcloud scheduler jobs "$WEATHER_CURRENT_ACTION" http weather-live-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='*/2 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/current" --http-method=POST --oidc-service-account-email="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi

echo "Step 5/5: removing only the retired METAR-map collection schedules."
while IFS= read -r WEATHER_JOB || [[ -n "$WEATHER_JOB" ]]; do
  if [[ -n "$WEATHER_JOB" ]]; then
    gcloud scheduler jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
  fi
done <"$WEATHER_WORK/retired-jobs.txt"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nLocal Current update complete. Refresh your usual J-Weather address.\nService URL: %s\nSource: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
