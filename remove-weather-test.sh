#!/usr/bin/env bash
# Retire TEST only, keep the five weather tabs without device location.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-remove-test.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK. TEST collection remains stopped if already removed." >&2' ERR
echo 'Step 1/4: saving settings and stopping only TEST background work.'
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_SERVICE.json"
done
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]);project=sys.argv[2]
web=json.loads((p/'weather-lab.json').read_text());collector=json.loads((p/'weather-collector.json').read_text())
image=web['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app'):raise SystemExit('Unexpected website image registry.')
spec=collector['spec']['template']['spec'];env={v['name']:v.get('value') for v in spec['containers'][0].get('env',[])}
bucket=env.get('WEATHER_DATA_BUCKET');sa=spec.get('serviceAccountName')
if not bucket or '/' in bucket or '\n' in bucket or not sa or not sa.endswith('.iam.gserviceaccount.com'):raise SystemExit('Missing bucket or collector identity.')
(p/'image-path').write_text(image);(p/'bucket').write_text(bucket);(p/'collector-sa').write_text(sa)
PY
if gcloud scheduler jobs describe weather-live-test-weather --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/test-job.json" 2>"$WEATHER_WORK/test-job.err"; then
  WEATHER_STATE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("state",""))' "$WEATHER_WORK/test-job.json")"
  if [[ "$WEATHER_STATE" == ENABLED ]]; then
    gcloud scheduler jobs pause weather-live-test-weather --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  fi
  gcloud scheduler jobs delete weather-live-test-weather --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
elif ! grep -q NOT_FOUND "$WEATHER_WORK/test-job.err"; then
  cat "$WEATHER_WORK/test-job.err" >&2; exit 1
fi
# Cancel unfinished TEST seed/cleanup executions before deleting those jobs.
for WEATHER_JOB in weather-test-seed weather-test-cleanup; do
  if gcloud run jobs describe "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_JOB.json" 2>"$WEATHER_WORK/$WEATHER_JOB.err"; then
    gcloud run jobs executions list --job="$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_JOB-executions.json"
    python3 - "$WEATHER_WORK/$WEATHER_JOB-executions.json" "$WEATHER_JOB" >"$WEATHER_WORK/$WEATHER_JOB-running.txt" <<'PY'
import json,re,sys
for row in json.load(open(sys.argv[1])):
    status=row.get('status',{});name=row.get('metadata',{}).get('name',row.get('name','')).split('/')[-1]
    terminal=status.get('completionTime') or any(c.get('type')=='Completed' and str(c.get('status')) in ('True','False') for c in status.get('conditions',[]))
    if not terminal:
        if not re.fullmatch(re.escape(sys.argv[2])+r'-[a-z0-9-]+',name):raise SystemExit('Unexpected TEST execution name')
        print(name)
PY
    while IFS= read -r WEATHER_EXECUTION; do
      [[ -n "$WEATHER_EXECUTION" ]] || continue
      gcloud run jobs executions cancel "$WEATHER_EXECUTION" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
    done <"$WEATHER_WORK/$WEATHER_JOB-running.txt"
    gcloud run jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
  elif ! grep -Eq 'NOT_FOUND|Cannot find job \[' "$WEATHER_WORK/$WEATHER_JOB.err"; then
    cat "$WEATHER_WORK/$WEATHER_JOB.err" >&2; exit 1
  fi
done
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):without-test-${WEATHER_COMMIT:0:12}"
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket")"
WEATHER_COLLECTOR_SA="$(cat "$WEATHER_WORK/collector-sa")"
echo 'Step 2/4: building the five-tab site without TEST or device location.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/4: updating both service images while preserving their settings.'
for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services update "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
  gcloud run services update-traffic "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
done
echo 'Step 4/4: removing TEST data and verifying the remaining pages.'
gcloud run jobs deploy weather-test-cleanup --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args='-u,remove_test_data.py' --tasks=1 --parallelism=1 --cpu=1 --memory=512Mi --max-retries=0 --task-timeout=300s --quiet
gcloud run jobs execute weather-test-cleanup --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait --quiet
gcloud run jobs delete weather-test-cleanup --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK/page.html" "$WEATHER_URL" <<'PY'
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
import sys
html=Path(sys.argv[1]).read_text()
if 'id="tab-test"' in html or 'test-weather.js' in html or 'radar-location.js' in html:raise SystemExit('The expected five-tab version without location was not verified.')
for path in ('/api/test/conditions','/api/test/history','/api/test/location','/api/test/forecast'):
    try:
        with urlopen(sys.argv[2]+path,timeout=30):raise SystemExit('A retired TEST endpoint is still available')
    except HTTPError as error:
        if error.code!=404:raise
print('Verified: TEST removed; five weather tabs remain without device location.')
PY
printf '\nOpen https://weather-lab.cloud.run and refresh.\nSaved settings: %s\n' "$WEATHER_WORK"
