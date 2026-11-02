#!/usr/bin/env bash
# Add TEST without changing the established maps, their schedules or warm settings.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-test.XXXXXX")"
trap 'echo "TEST setup stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
printf 'Step 1/5: saving existing settings in %s\n' "$WEATHER_WORK"
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_SERVICE.json"
done
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]);project=sys.argv[2]
web=json.loads((p/'weather-lab.json').read_text());collector=json.loads((p/'weather-collector.json').read_text())
image=web['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app'):raise SystemExit('Unexpected website registry; no build started.')
spec=collector['spec']['template']['spec'];env={v['name']:v.get('value') for v in spec['containers'][0].get('env',[])}
bucket=env.get('WEATHER_DATA_BUCKET');sa=spec.get('serviceAccountName')
if not bucket or '/' in bucket or '\n' in bucket or not sa or not sa.endswith('.iam.gserviceaccount.com'):raise SystemExit('Missing bucket or collector identity; no build started.')
(p/'image-path').write_text(image);(p/'bucket').write_text(bucket);(p/'collector-sa').write_text(sa)
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):test-${WEATHER_COMMIT:0:12}"
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket")"
WEATHER_COLLECTOR_SA="$(cat "$WEATHER_WORK/collector-sa")"
echo 'Step 2/5: building the TEST page and shared observation collector once.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/5: updating the private collector and preparing the first station snapshot and twelve-hour history.'
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
gcloud run jobs deploy weather-test-seed --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args='-u,point_weather.py' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=900s --quiet
gcloud run jobs execute weather-test-seed --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait --quiet
echo 'Step 4/5: scheduling only the new TEST observation checks every five minutes.'
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
# Reuse the established scheduler identity and its existing private-service access.
gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(httpTarget.oidcToken.serviceAccountEmail)' >"$WEATHER_WORK/scheduler-sa"
WEATHER_SCHEDULER_SA="$(cat "$WEATHER_WORK/scheduler-sa")"
[[ "$WEATHER_SCHEDULER_SA" == *@*.iam.gserviceaccount.com ]] || { echo 'Scheduler identity missing.' >&2; exit 1; }
WEATHER_ACTION=create
if gcloud scheduler jobs describe weather-live-test-weather --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/test-schedule.json" 2>"$WEATHER_WORK/test-schedule.err"; then
  WEATHER_ACTION=update
elif ! grep -q NOT_FOUND "$WEATHER_WORK/test-schedule.err"; then
  cat "$WEATHER_WORK/test-schedule.err" >&2; exit 1
fi
gcloud scheduler jobs "$WEATHER_ACTION" http weather-live-test-weather --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='*/5 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/test-weather" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER_SA" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0
if [[ "$(gcloud scheduler jobs describe weather-live-test-weather --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-test-weather --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
echo 'Step 5/5: publishing and verifying TEST alongside the existing pages.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
python3 "$WEATHER_WORK/source/verify_test_weather.py" "$WEATHER_URL"
printf '\nTEST ready: %s\nWebsite: https://weather-lab.cloud.run\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
