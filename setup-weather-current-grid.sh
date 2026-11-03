#!/usr/bin/env bash
# Add shared local Current estimates and cloud-only maps in the existing project.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass the active Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-current-grid.XXXXXX")"
trap 'echo "Setup stopped at line $LINENO. Saved settings and source: $WEATHER_WORK" >&2' ERR
echo 'Step 1/5: saving service settings and collection schedules.'
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_SERVICE.json"
done
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/schedules-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]);project=sys.argv[2]
web=json.loads((p/'weather-lab.json').read_text());collector=json.loads((p/'weather-collector.json').read_text())
image=web['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app'):raise SystemExit('Unexpected website image registry; no changes made.')
spec=collector['spec']['template']['spec'];env={v['name']:v.get('value') for v in spec['containers'][0].get('env',[])}
bucket=env.get('WEATHER_DATA_BUCKET');account=spec.get('serviceAccountName')
if not bucket or '/' in bucket or '\n' in bucket or not account or not account.endswith('.iam.gserviceaccount.com'):raise SystemExit('Missing collector bucket or identity.')
accounts={job.get('httpTarget',{}).get('oidcToken',{}).get('serviceAccountEmail') for job in json.loads((p/'schedules-before.json').read_text()) if job['name'].split('/')[-1]=='weather-live-metar-clouds'}
if len(accounts)!=1 or None in accounts:raise SystemExit('Could not identify the existing weather Scheduler account.')
(p/'image-path').write_text(image);(p/'bucket').write_text(bucket);(p/'collector-account').write_text(account);(p/'scheduler-account').write_text(accounts.pop())
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):current-grid-${WEATHER_COMMIT:0:12}"
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket")"
WEATHER_COLLECTOR_ACCOUNT="$(cat "$WEATHER_WORK/collector-account")"
echo 'Step 2/5: building Current and Clouds while retaining the radar and satellite renderers.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/5: preparing recent MN/WI observations once before publishing Current.'
WEATHER_JOB="weather-current-seed-$(date -u +%y%m%d-%H%M%S)-${WEATHER_WORK##*.}"
WEATHER_JOB="${WEATHER_JOB,,}"
gcloud run jobs deploy "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_ACCOUNT" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args='-u,current_analysis.py' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=600s --quiet
gcloud run jobs execute "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait --quiet
echo 'Step 4/5: isolating Current collection and enabling its five-minute schedule.'
gcloud run deploy weather-current-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --no-allow-unauthenticated --service-account="$WEATHER_COLLECTOR_ACCOUNT" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --cpu-throttling --cpu=1 --memory=2Gi --min-instances=0 --max-instances=1 --concurrency=1 --timeout=180 --command=gunicorn --args='--bind=0.0.0.0:8080,--workers=1,--threads=1,--timeout=180,current_collector:app' --quiet
gcloud run services add-iam-policy-binding weather-current-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --member="serviceAccount:$(cat "$WEATHER_WORK/scheduler-account")" --role=roles/run.invoker --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-current-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
if gcloud scheduler jobs describe weather-live-current-analysis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/current-job.json" 2>"$WEATHER_WORK/current-job.err"; then
  WEATHER_ACTION=update
elif grep -q NOT_FOUND "$WEATHER_WORK/current-job.err"; then
  WEATHER_ACTION=create
else
  cat "$WEATHER_WORK/current-job.err" >&2; exit 1
fi
gcloud scheduler jobs "$WEATHER_ACTION" http weather-live-current-analysis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='*/5 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/current-analysis" --http-method=POST --oidc-service-account-email="$(cat "$WEATHER_WORK/scheduler-account")" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-current-analysis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-current-analysis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
echo 'Step 5/5: publishing and verifying all six weather tabs.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 --dump-header "$WEATHER_WORK/headers.txt" "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/static/location-choice.js?v=one-shot-v1" -o "$WEATHER_WORK/location-choice.js"
python3 - "$WEATHER_WORK" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);headers=(p/'headers.txt').read_text().lower()
if 'permissions-policy: geolocation=(self)' not in headers:raise SystemExit('The explicit-location policy was not verified.')
if (p/'location-choice.js').read_bytes()!=(p/'source/static/location-choice.js').read_bytes():raise SystemExit('The click-only location script was not verified.')
print('Verified click-only location; no continuous location tracking.')
PY
gcloud run jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nCurrent and Clouds are ready.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\nClick Use my location once; that point remains selected until you change or reset it.\n' "$WEATHER_URL" "$WEATHER_WORK"
