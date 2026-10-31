#!/usr/bin/env bash
# Update only the website image; retain weather collection and warm-instance settings.
set -euo pipefail
WEATHER_PROJECT="${1:-$(gcloud config get-value project)}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your active Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-default-views.XXXXXX")"
trap 'echo "View update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
printf 'Updating website in project: %s\n' "$WEATHER_PROJECT"
echo 'Step 1/3: saving the website settings and building the updated opening views.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/web-before.json"
WEATHER_IMAGE_PATH="$(python3 - "$WEATHER_WORK/web-before.json" "$WEATHER_PROJECT" <<'PY'
import json,sys
image=json.load(open(sys.argv[1]))['spec']['template']['spec']['containers'][0]['image']
path=image.split('@',1)[0].split(':',1)[0]
if not path.startswith(f'us-central1-docker.pkg.dev/{sys.argv[2]}/') or not path.endswith('/app'):
    raise SystemExit('Unexpected website registry; no deployment started.')
print(path)
PY
)"
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_IMAGE_PATH:default-views-${WEATHER_COMMIT:0:12}"
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 2/3: publishing the website image.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
echo 'Step 3/3: verifying the weather pages and default-view assets.'
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK/page.html" <<'PY'
from pathlib import Path
import sys
html=Path(sys.argv[1]).read_text()
for text in ('default-views.js?v=default-views-v1','metar-views.js?v=default-views-v1','app.js?v=default-views-v1','id="radar-save-view"'):
    if text not in html:raise SystemExit('The updated opening-view controls were not verified.')
print('Verified: three-airport opening METAR view and radar Set default control.')
PY
printf '\nOpening views updated.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
