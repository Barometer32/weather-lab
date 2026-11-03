#!/usr/bin/env bash
# Show individual pollutants and restrict Current wind to airport feeds.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-pollutants-wind.XXXXXX")"
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
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):pollutants-wind-${WEATHER_COMMIT:0:12}"
echo 'Step 2/3: building individual pollutants and airport-only wind.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
echo 'Step 3/3: verifying individual pollutants, airport-only wind and the five tabs.'
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
for asset,version in [('location-choice','city-label-v2'),('current-views','airport-wind-v3'),('forecast-views','selected-point-v1'),('local-air-views','pollutants-v2'),('app','local-air-v1'),('prepared-data','local-air-v1')]:
    if f'/static/{asset}.js?v={version}' not in html:raise SystemExit('The new Current viewer is not referenced.')
    if (work/f'{asset}.js').read_bytes()!=(work/f'source/static/{asset}.js').read_bytes():raise SystemExit('The expected Current script was not served.')
if 'id="current-observation-range"' not in html:raise SystemExit('The observation details were not verified.')
if 'air-quality-views.js' in html or 'id="air-quality"' in html:raise SystemExit('The retired air-quality map is still present.')
if (work/'style.css').read_bytes()!=(work/'source/static/style.css').read_bytes():raise SystemExit('The new air-quality layout was not served.')
if 'Pollution mix' in html or 'local-mix-value' in html:raise SystemExit('The old combined score is still present.')
if not all(f'id="air-{p}-value"' in html for p in ('pm25','pm10','ozone','no2')):raise SystemExit('All four pollutant cards were not verified.')
print('Verified four pollutant cards, five tabs and click-only device location.')
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
if p.get('version')!='local-pollutants-v2' or 'mix' in p:raise SystemExit('The individual-pollutant response was not verified.')
if {r.get('pollutant') for r in p.get('readings',[])}!={'PM2.5','PM10','Ozone','NO2'}:raise SystemExit('The four pollutants were not verified.')
if not p.get('available'):raise SystemExit('Recent pollutant observations are unavailable. Website updated; the old map job has not been changed.')
for r in p['readings']:print(r['pollutant'],r.get('value') if r.get('value') is not None else 'unavailable',r['unit'],r.get('station') or '')
PYAIR
WEATHER_WIND_STATUS="$(curl -sS --max-time 30 -o "$WEATHER_WORK/wind-check.json" -w '%{http_code}' -H 'Content-Type: application/json' -X POST --data '{"latitude":44.782,"longitude":-93.484}' "$WEATHER_URL/api/current")"
if [[ "$WEATHER_WIND_STATUS" != 200 ]]; then
  echo "Current returned HTTP $WEATHER_WIND_STATUS. Send this output for diagnosis." >&2
  exit 1
fi
python3 - "$WEATHER_WORK/wind-check.json" <<'PYWIND'
import json,sys
p=json.load(open(sys.argv[1]))
if p.get('windPolicy')!='airports-only-v1':raise SystemExit('The airport-only wind policy was not verified.')
wind=[r for r in p.get('stations',[]) if 'wind' in r.get('weightsPct',{})]
for r in wind:
    if r.get('provider','').upper() not in ('AWC','HF-METAR') and r.get('network','').upper() not in ('AIRPORT METAR','HF-METAR'):raise SystemExit('A non-airport still contributes wind.')
if wind:print('Verified wind contributors:',', '.join(r['station'] for r in wind))
else:print('Airport-only policy verified. Wind is currently unavailable because too few recent airport reports passed the checks.')
PYWIND
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
printf '\nOpen https://weather-lab.cloud.run and refresh each device.\nIndividual pollutants and airport-only wind are ready. The old map job remains paused; other schedules are unchanged.\nSaved settings: %s\n' "$WEATHER_WORK"
