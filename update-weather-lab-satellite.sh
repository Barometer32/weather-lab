#!/usr/bin/env bash
# Publish the latest-24 satellite history and current display refinements.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261024-133205}"
WEATHER_REGION=us-central1
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-satellite.XXXXXX")"
WEATHER_RESUME_SATELLITE=false
weather_cleanup() {
  local weather_code="$?"
  if [[ "$WEATHER_RESUME_SATELLITE" == true ]]; then
    gcloud scheduler jobs resume weather-live-satellite --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" || true
  fi
  if [[ "$weather_code" != 0 ]]; then echo "Update stopped. Settings and diagnostics: $WEATHER_WORK" >&2; fi
}
trap weather_cleanup EXIT

echo 'Step 1/5: saving service settings and the satellite schedule.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/website-before.json"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
WEATHER_JOB_STATE="$(gcloud scheduler jobs describe weather-live-satellite --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY' >"$WEATHER_WORK/settings.txt"
import json,sys
from pathlib import Path
work=Path(sys.argv[1]);project=sys.argv[2]
web=json.loads((work/'website-before.json').read_text())['spec']['template']['spec']
collector=json.loads((work/'collector-before.json').read_text())['spec']['template']['spec']
image=web['containers'][0]['image'].split('@')[0].split(':')[0]
account=collector.get('serviceAccountName')
bucket=next((v.get('value') for v in collector['containers'][0].get('env',[]) if v.get('name')=='WEATHER_DATA_BUCKET'),None)
if not image.startswith('us-central1-docker.pkg.dev/'+project+'/') or not image.endswith('/app') or not account or not bucket:
    raise SystemExit('Unexpected image path or missing collector identity/bucket; no build or deployment started.')
print(image);print(account);print(bucket)
PY
mapfile -t WEATHER_SETTINGS <"$WEATHER_WORK/settings.txt"
WEATHER_IMAGE_PATH="${WEATHER_SETTINGS[0]}"
WEATHER_COLLECTOR_SA="${WEATHER_SETTINGS[1]}"
WEATHER_BUCKET="${WEATHER_SETTINGS[2]}"
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_IMAGE_PATH:satellite-24-${WEATHER_COMMIT:0:12}"

echo 'Step 2/5: building the update and publishing the satellite collector.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
if [[ "$WEATHER_JOB_STATE" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-satellite --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  WEATHER_RESUME_SATELLITE=true
fi
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet

echo 'Step 3/5: preparing 24 available images for each satellite product now.'
gcloud run jobs deploy weather-satellite-prepare --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args=refresh_satellite.py --tasks=1 --parallelism=1 --cpu=1 --memory=1Gi --max-retries=0 --task-timeout=600s --quiet
if ! gcloud run jobs execute weather-satellite-prepare --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait; then
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="weather-satellite-prepare"' --project="$WEATHER_PROJECT" --freshness=20m --limit=20 --format='value(textPayload,jsonPayload.message)'
  exit 1
fi

echo 'Step 4/5: publishing the page with the thicker, shorter wind arrows.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo 'Step 5/5: verifying all three satellite histories.'
for WEATHER_PRODUCT in truecolor dcphase ntmicro; do
  curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_WEB_URL/api/satellite/$WEATHER_PRODUCT" -o "$WEATHER_WORK/$WEATHER_PRODUCT.json"
done
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_WEB_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1])
for product in ['truecolor','dcphase','ntmicro']:
    data=json.loads((work/(product+'.json')).read_text());frames=data.get('frames',[])
    times=[f['time'] for f in frames]
    if data.get('frameLimit')!=24 or data.get('historyPolicy')!='latest-24-images' or not 1<=len(frames)<=24 or times!=sorted(set(times)):
        raise SystemExit(product+': latest-24 image policy is not ready yet.')
    print(f'{product}: {len(frames)}/24 available images, {times[0]} through {times[-1]}')
html=(work/'page.html').read_text()
if '/static/metar-model.js?v=compact-vector-v3' not in html or '/static/app.js?v=satellite-24-v1' not in html:
    raise SystemExit('The latest satellite and wind display assets are not published yet.')
PY
if [[ "$WEATHER_RESUME_SATELLITE" == true ]]; then
  gcloud scheduler jobs resume weather-live-satellite --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  WEATHER_RESUME_SATELLITE=false
fi
gcloud scheduler jobs describe weather-live-satellite --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='yaml(schedule,state)'
printf '\nUpdate complete. Refresh https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_WEB_URL" "$WEATHER_WORK"
