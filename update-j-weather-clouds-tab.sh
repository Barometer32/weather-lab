#!/usr/bin/env bash
# Publish website display updates without changing the collector or schedules.
set -euo pipefail
WEATHER_PROJECT="${1:-j-weather-261020012817}"
WEATHER_REGION=us-central1
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-clouds-tab.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR

echo 'Step 1/3: saving the website settings and getting the update.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:clouds-tab-${WEATHER_COMMIT:0:12}"

echo 'Step 2/3: building and updating the website.'
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo 'Step 3/3: verifying the updated page.'
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_WEB_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK/page.html" <<'PY'
from pathlib import Path
import sys
html=Path(sys.argv[1]).read_text()
import re
if re.findall(r'<button role="tab" id="tab-([^\"]+)"',html)!=['metar-clouds','radar','satellite','forecast','air-quality']:
    raise SystemExit('The combined METAR tabs are not published yet.')
for asset in ['style.css','metar-model.js','cloud-views.js','app.js']:
    if f'/static/{asset}?v=' not in html:
        raise SystemExit(f'The Clouds update for {asset} is not published yet.')
if 'data-ceiling-unit="thousands-ft"' not in html or 'id="metar-cloud-timeline"' not in html:
    raise SystemExit('The cloud-height units or history slider are not published yet.')
print('Verified combined METAR station plots with 12-hour history.')
PY
printf '\nUpdate complete. Refresh your usual J-Weather address.\nService URL: %s\nSaved settings: %s\n' "$WEATHER_WEB_URL" "$WEATHER_WORK"
