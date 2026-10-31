#!/usr/bin/env bash
# Add the observation dropdown and independent quarter-hour current MADIS collection.
set -euo pipefail
WEATHER_PROJECT="${1:-$(gcloud config get-value project)}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your active Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-madis-products.XXXXXX")"
trap 'echo "Map update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
printf 'Updating Weather Lab project: %s\n' "$WEATHER_PROJECT"
echo 'Step 1/5: saving the live services and schedules.'
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_SERVICE-before.json"
done
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1]);project=sys.argv[2]
for service in ('weather-lab','weather-collector'):
    spec=json.loads((work/f'{service}-before.json').read_text())['spec']['template']['spec']
    path=spec['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
    if not path.startswith(f'us-central1-docker.pkg.dev/{project}/') or not path.endswith('/app'):
        raise SystemExit('Unexpected image registry; no build started.')
    if service=='weather-lab':(work/'image-path.txt').write_text(path)
    else:
        account=spec.get('serviceAccountName')
        bucket=next((v.get('value') for v in spec['containers'][0].get('env',[]) if v['name']=='WEATHER_DATA_BUCKET'),None)
        if account!=f'weather-collector@{project}.iam.gserviceaccount.com' or bucket!=f'{project}-weather-data':
            raise SystemExit('Unexpected collector account or bucket; no build started.')
        (work/'collector-account.txt').write_text(account);(work/'bucket.txt').write_text(bucket)
job=next((j for j in json.loads((work/'jobs-before.json').read_text()) if j['name'].rsplit('/',1)[-1]=='weather-live-madis-map'),None)
(work/'schedule-action.txt').write_text('update' if job else 'create')
(work/'schedule-paused.txt').write_text('yes' if job and job.get('state')=='PAUSED' else 'no')
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path.txt"):madis-current-${WEATHER_COMMIT:0:12}"
echo 'Step 2/5: building the dropdown and deploying the matching collector image.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
echo 'Step 3/5: preparing the current 25-minute mesonet snapshot.'
WEATHER_JOB="weather-madis-seed-$(date -u +%y%m%d-%H%M%S)-${WEATHER_WORK##*.}"
WEATHER_JOB="${WEATHER_JOB,,}"
gcloud run jobs deploy "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$(cat "$WEATHER_WORK/collector-account.txt")" --set-env-vars="WEATHER_DATA_BUCKET=$(cat "$WEATHER_WORK/bucket.txt")" --command=python --args='-u,madis_map.py' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=900s --quiet
gcloud run jobs execute "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait
echo 'Step 4/5: adding only the MADIS schedule and publishing the dropdown.'
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
gcloud scheduler jobs "$(cat "$WEATHER_WORK/schedule-action.txt")" http weather-live-madis-map --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='0,15,30,45 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/madis-map" --http-method=POST --oidc-service-account-email="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
if [[ "$(cat "$WEATHER_WORK/schedule-paused.txt")" == yes ]]; then
  gcloud scheduler jobs resume weather-live-madis-map --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
echo 'Step 5/5: verifying airport plots, the separate mesonet map and all weather pages.'
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
printf '\nObservation dropdown update complete.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
