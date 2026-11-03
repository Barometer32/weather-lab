#!/usr/bin/env bash
# Preserve website settings, backfill new products, then update the viewer.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass a Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-radar-products.XXXXXX")"
WEATHER_PAUSED=false
cleanup() {
  local result=$?
  if [[ "$WEATHER_PAUSED" == true ]]; then
    gcloud scheduler jobs resume weather-live-radar --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet || true
  fi
  if (( result != 0 )); then
    printf '\nUpdate stopped. Saved settings and source: %s\n' "$WEATHER_WORK" >&2
    if [[ -n "${WEATHER_JOB:-}" ]]; then
      printf 'Recovery job (safe to rerun): %s\n' "$WEATHER_JOB" >&2
    fi
  fi
}
trap cleanup EXIT
echo 'Step 1/5: saving existing settings and fetching the radar update.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/web-before.json"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
gcloud scheduler jobs describe weather-live-radar --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/schedule-before.json"
git clone --quiet --depth=1 --branch radar-tilts-20261103 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
readarray -t WEATHER_SETTINGS < <(python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1]);project=sys.argv[2]
web=json.loads((work/'web-before.json').read_text());collector=json.loads((work/'collector-before.json').read_text())
image=web['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
spec=collector['spec']['template']['spec'];env={x['name']:x.get('value') for x in spec['containers'][0].get('env',[])}
bucket=env.get('WEATHER_DATA_BUCKET');identity=spec.get('serviceAccountName')
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app') or not bucket or not identity:
    raise SystemExit('Unexpected registry, missing data bucket or collector identity; no deployment started.')
print(image);print(bucket);print(identity)
PY
)
[[ ${#WEATHER_SETTINGS[@]} == 3 ]] || { echo 'Settings check failed.' >&2; exit 1; }
WEATHER_IMAGE="${WEATHER_SETTINGS[0]}:radar-products-${WEATHER_COMMIT:0:12}"
echo 'Step 2/5: building the website and collector image.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/5: preparing all elevation loops and storm-total precipitation.'
WEATHER_SCHEDULE_STATE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["state"])' "$WEATHER_WORK/schedule-before.json")"
if [[ "$WEATHER_SCHEDULE_STATE" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-radar --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
  WEATHER_PAUSED=true
fi
# New multi-product manifests and cursors are isolated from the old collector.
WEATHER_JOB="weather-radar-products-$(date -u +%y%m%d-%H%M%S)"
gcloud run jobs deploy "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="${WEATHER_SETTINGS[2]}" --set-env-vars="WEATHER_DATA_BUCKET=${WEATHER_SETTINGS[1]}" --command=python --args='-u,prepare_radar_products.py' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=1800s --quiet
gcloud run jobs execute "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait --quiet
echo 'Step 4/5: updating the collector and website while preserving their settings.'
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
if [[ "$WEATHER_PAUSED" == true ]]; then
  gcloud scheduler jobs resume weather-live-radar --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
  WEATHER_PAUSED=false
fi
echo 'Step 5/5: verifying every radar option and its newest prepared scan.'
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 "$WEATHER_WORK/source/verify_radar_products.py" "$WEATHER_URL"
gcloud run jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
printf '\nRadar update complete. Open RADAR and choose an elevation or Storm-total precipitation.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
