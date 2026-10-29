#!/usr/bin/env bash
# Fit all screens, add infrared, and repair hourly Air Q history in the live project.
set -euo pipefail
WEATHER_REGION=us-central1
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-screen.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
if [[ -n "${1:-}" ]]; then
  WEATHER_PROJECT="$1"
elif [[ -s "$HOME/weather-lab-fresh-weather-lab-261027-024631-5ff2/project-id.txt" ]]; then
  WEATHER_PROJECT="$(cat "$HOME/weather-lab-fresh-weather-lab-261027-024631-5ff2/project-id.txt")"
else
  WEATHER_PROJECT="$(gcloud config get-value project)"
fi
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass the current Weather Lab project ID as the first argument.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
printf 'Updating Weather Lab project: %s\n' "$WEATHER_PROJECT"
echo 'Step 1/5: saving the live service and Air Q schedule settings.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/web-before.json"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
gcloud scheduler jobs describe weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/airq-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1]);project=sys.argv[2]
for service in ('web','collector'):
    spec=json.loads((work/f'{service}-before.json').read_text())['spec']['template']['spec']
    image=spec['containers'][0]['image'];path=image.split('@',1)[0].split(':',1)[0]
    if not path.startswith(f'us-central1-docker.pkg.dev/{project}/') or not path.endswith('/app'):raise SystemExit('Unexpected live image registry; no build started.')
    (work/f'{service}-image.txt').write_text(image+'\n')
    if service=='web':(work/'image-path.txt').write_text(path+'\n')
    else:
        account=spec.get('serviceAccountName');bucket=next((v.get('value') for v in spec['containers'][0].get('env',[]) if v['name']=='WEATHER_DATA_BUCKET'),None)
        if account!=f'weather-collector@{project}.iam.gserviceaccount.com' or bucket!=f'{project}-weather-data':raise SystemExit('Unexpected collector account or bucket; no build started.')
        (work/'collector-account.txt').write_text(account+'\n');(work/'bucket.txt').write_text(bucket+'\n')
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path.txt"):screen-${WEATHER_COMMIT:0:12}"
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket.txt")"
echo 'Step 2/5: building the screen layout and data improvements.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
echo 'Step 3/5: preparing infrared images and filling available hourly Air Q gaps.'
WEATHER_JOB="weather-viewer-$(date -u +%y%m%d-%H%M%S)-${WEATHER_WORK##*.}"
WEATHER_JOB="${WEATHER_JOB,,}"
gcloud run jobs deploy "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$(cat "$WEATHER_WORK/collector-account.txt")" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args='-u,prepare_viewer_data.py' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=900s --quiet
gcloud run jobs execute "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait
gcloud storage buckets update "gs://$WEATHER_BUCKET" --lifecycle-file="$WEATHER_WORK/source/data-lifecycle.json"
gcloud scheduler jobs update http weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='3-58/5 * * * *' --quiet
echo 'Step 4/5: publishing the fitted screen layout and preserved map controls.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
echo 'Step 5/5: verifying all weather pages and prepared images.'
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK/page.html" <<'PY'
from pathlib import Path
import sys
html=Path(sys.argv[1]).read_text()
for asset in ('style.css?v=compact-timeline-v1','map-fullscreen.js?v=viewport-v1','viewport-fit.js?v=viewport-v1','app.js?v=viewport-v1','metar-model.js?v=metar-combined-v4'):
    if '/static/'+asset not in html:raise SystemExit('The new viewer assets were not verified.')
if '<option value="13">Infrared</option>' not in html:raise SystemExit('Infrared dropdown was not verified.')
print('Verified fitted-screen layout, infrared option, combined METAR plots and prepared weather data.')
PY
printf '\nWeather Lab screen update complete.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nProject: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_PROJECT" "$WEATHER_WORK"
