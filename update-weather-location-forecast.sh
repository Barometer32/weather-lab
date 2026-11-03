#!/usr/bin/env bash
# Make Forecast use the saved Current location; update only the website.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-location-forecast.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
echo 'Step 1/3: saving the website settings.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/web-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1]);project=sys.argv[2]
image=json.loads((work/'web-before.json').read_text())['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app'):raise SystemExit('Unexpected website image registry.')
(work/'image-path').write_text(image)
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):location-forecast-${WEATHER_COMMIT:0:12}"
echo 'Step 2/3: building the location-aware NWS Forecast and retaining city/time updates.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
echo 'Step 3/3: verifying the selected-location Forecast and six weather tabs.'
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 --dump-header "$WEATHER_WORK/headers.txt" "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
for WEATHER_ASSET in location-choice current-views forecast-views app prepared-data; do
  curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/static/$WEATHER_ASSET.js?v=current-labels-v2" -o "$WEATHER_WORK/$WEATHER_ASSET.js"
done
python3 - "$WEATHER_WORK" <<'PYVERIFY'
from pathlib import Path
import re,sys
work=Path(sys.argv[1]);html=(work/'page.html').read_text();headers=(work/'headers.txt').read_text().lower()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['current','radar','clouds','satellite','forecast','air-quality']:raise SystemExit('The six weather tabs were not verified.')
if 'permissions-policy: geolocation=(self)' not in headers:raise SystemExit('The click-only location policy was not verified.')
for asset,version in [('location-choice','city-label-v2'),('current-views','weighted-time-v2'),('forecast-views','selected-point-v1'),('app','selected-forecast-v2'),('prepared-data','selected-forecast-v2')]:
    if f'/static/{asset}.js?v={version}' not in html:raise SystemExit('The new Current viewer is not referenced.')
    if (work/f'{asset}.js').read_bytes()!=(work/f'source/static/{asset}.js').read_bytes():raise SystemExit('The expected Current script was not served.')
if 'id="current-observation-range"' not in html:raise SystemExit('The observation details were not verified.')
print('Verified selected-location Forecast, city/time viewer, six tabs, and click-only device location.')
PYVERIFY
WEATHER_FORECAST_STATUS="$(curl -sS --max-time 30 -o "$WEATHER_WORK/forecast-check.json" -w '%{http_code}' -H 'Content-Type: application/json' -X POST --data '{"latitude":44.782,"longitude":-93.484}' "$WEATHER_URL/api/forecast")"
if [[ "$WEATHER_FORECAST_STATUS" == 200 ]]; then
  python3 - "$WEATHER_WORK/forecast-check.json" <<'PYFORECAST'
import json,sys
forecast=json.load(open(sys.argv[1]))
if (forecast.get('latitude'),forecast.get('longitude'))!=(44.782,-93.484):raise SystemExit('The forecast did not match the requested point.')
if not forecast.get('periods') or forecast.get('source')!='National Weather Service':raise SystemExit('The selected NWS forecast was not verified.')
if 'lat=44.782&lon=-93.484' not in forecast.get('sourceUrl',''):raise SystemExit('The NWS source link did not match the point.')
print('Verified selected NWS forecast:',forecast.get('location'))
PYFORECAST
elif [[ "$WEATHER_FORECAST_STATUS" == 502 ]]; then
  echo 'Website updated. NWS is temporarily unavailable for the test point; reopen Forecast later to retry. No other location will be substituted.'
else
  echo "The selected Forecast returned HTTP $WEATHER_FORECAST_STATUS; send this output for diagnosis." >&2
  exit 1
fi
printf '\nOpen https://weather-lab.cloud.run and refresh each device.\nOnly the website was updated; collection schedules are unchanged.\nSaved settings: %s\n' "$WEATHER_WORK"
