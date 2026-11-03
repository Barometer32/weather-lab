#!/usr/bin/env bash
# Put local U.S. AQI and a separate AQHI estimate on Current; retire map collection.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-local-air.XXXXXX")"
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
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):local-air-${WEATHER_COMMIT:0:12}"
echo 'Step 2/3: building Current air quality and preserving the selected-location Forecast.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
echo 'Step 3/3: verifying Current air quality and the five weather tabs.'
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 --dump-header "$WEATHER_WORK/headers.txt" "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
for WEATHER_ASSET in location-choice current-views forecast-views local-air-views app prepared-data style; do
  WEATHER_ASSET_SUFFIX=js; [[ "$WEATHER_ASSET" == style ]] && WEATHER_ASSET_SUFFIX=css
  curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/static/$WEATHER_ASSET.${WEATHER_ASSET_SUFFIX}?v=local-air-v1" -o "$WEATHER_WORK/$WEATHER_ASSET.${WEATHER_ASSET_SUFFIX}"
done
python3 - "$WEATHER_WORK" <<'PYVERIFY'
from pathlib import Path
import re,sys
work=Path(sys.argv[1]);html=(work/'page.html').read_text();headers=(work/'headers.txt').read_text().lower()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['current','radar','clouds','satellite','forecast']:raise SystemExit('The five weather tabs were not verified.')
if 'permissions-policy: geolocation=(self)' not in headers:raise SystemExit('The click-only location policy was not verified.')
for asset,version in [('location-choice','city-label-v2'),('current-views','weighted-time-v2'),('forecast-views','selected-point-v1'),('local-air-views','aqhi-local-v1'),('app','local-air-v1'),('prepared-data','local-air-v1')]:
    if f'/static/{asset}.js?v={version}' not in html:raise SystemExit('The new Current viewer is not referenced.')
    if (work/f'{asset}.js').read_bytes()!=(work/f'source/static/{asset}.js').read_bytes():raise SystemExit('The expected Current script was not served.')
if 'id="current-observation-range"' not in html:raise SystemExit('The observation details were not verified.')
if 'air-quality-views.js' in html or 'id="air-quality"' in html:raise SystemExit('The retired air-quality map is still present.')
if (work/'style.css').read_bytes()!=(work/'source/static/style.css').read_bytes():raise SystemExit('The new air-quality layout was not served.')
print('Verified local air-quality viewer, five tabs and click-only device location.')
PYVERIFY
WEATHER_AIR_STATUS="$(curl -sS --max-time 80 -o "$WEATHER_WORK/air-check.json" -w '%{http_code}' -H 'Content-Type: application/json' -X POST --data '{"latitude":44.782,"longitude":-93.484}' "$WEATHER_URL/api/local-air-quality")"
if [[ "$WEATHER_AIR_STATUS" != 200 ]]; then
  echo "The local air-quality endpoint returned HTTP $WEATHER_AIR_STATUS. Website updated; send this output for diagnosis." >&2
  exit 1
fi
python3 - "$WEATHER_WORK/air-check.json" <<'PYAIR'
import json,sys
p=json.load(open(sys.argv[1]))
if (p.get('latitude'),p.get('longitude'))!=(44.782,-93.484):raise SystemExit('The air-quality response did not match the point.')
if not(p.get('aqi') or p.get('mix')):raise SystemExit('Recent local air-quality data are not available yet. Reopen Current later; the old map schedule has not been changed.')
if p.get('mix') and (p['mix'].get('official') is not False or p['mix'].get('method')!='Classic 3-pollutant AQHI estimate'):raise SystemExit('The separate mix method was not verified.')
print('U.S. AQI:',(p.get('aqi') or {}).get('value','unavailable'))
print('Classic AQHI estimate:',(p.get('mix') or {}).get('display','unavailable: required inputs missing'))
PYAIR
echo 'Pausing the retired statewide air-quality map collector.'
if gcloud scheduler jobs describe weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)' >"$WEATHER_WORK/air-map-state" 2>"$WEATHER_WORK/air-map-error"; then
  if [[ "$(cat "$WEATHER_WORK/air-map-state")" != PAUSED ]]; then
    gcloud scheduler jobs pause weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
  fi
elif [[ "$(cat "$WEATHER_WORK/air-map-error")" == *NOT_FOUND* ]]; then
  echo 'No old air-quality map job remains.'
else
  cat "$WEATHER_WORK/air-map-error" >&2
  echo 'The map collector could not be checked. Send this output for diagnosis.' >&2
  exit 1
fi
printf '\nOpen https://weather-lab.cloud.run and refresh each device.\nCurrent air quality is ready. The old air-quality map job is paused; other schedules are unchanged.\nSaved settings: %s\n' "$WEATHER_WORK"
