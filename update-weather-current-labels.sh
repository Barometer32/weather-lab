#!/usr/bin/env bash
# Add city labels and weighted observation times; update only the website.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-current-labels.XXXXXX")"
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
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):current-labels-${WEATHER_COMMIT:0:12}"
echo 'Step 2/3: building and publishing city names and weighted observation times.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
echo 'Step 3/3: verifying city labels, weighted observation times, and the six weather tabs.'
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 --dump-header "$WEATHER_WORK/headers.txt" "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
for WEATHER_ASSET in location-choice current-views; do
  curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/static/$WEATHER_ASSET.js?v=current-labels-v2" -o "$WEATHER_WORK/$WEATHER_ASSET.js"
done
python3 - "$WEATHER_WORK" <<'PYVERIFY'
from pathlib import Path
import re,sys
work=Path(sys.argv[1]);html=(work/'page.html').read_text();headers=(work/'headers.txt').read_text().lower()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['current','radar','clouds','satellite','forecast','air-quality']:raise SystemExit('The six weather tabs were not verified.')
if 'permissions-policy: geolocation=(self)' not in headers:raise SystemExit('The click-only location policy was not verified.')
for asset,version in [('location-choice','city-label-v2'),('current-views','weighted-time-v2')]:
    if f'/static/{asset}.js?v={version}' not in html:raise SystemExit('The new Current viewer is not referenced.')
    if (work/f'{asset}.js').read_bytes()!=(work/f'source/static/{asset}.js').read_bytes():raise SystemExit('The expected Current script was not served.')
if 'id="current-observation-range"' not in html:raise SystemExit('The observation details were not verified.')
print('Verified city-name viewer, weighted observation time, six tabs, and click-only device location.')
PYVERIFY
WEATHER_NAME_STATUS="$(curl -sS --max-time 20 -o "$WEATHER_WORK/city-check.json" -w '%{http_code}' -H 'Content-Type: application/json' -X POST --data '{"latitude":44.98,"longitude":-93.26}' "$WEATHER_URL/api/location-name")"
if [[ "$WEATHER_NAME_STATUS" == 200 ]]; then
  python3 - "$WEATHER_WORK/city-check.json" <<'PYCITY'
import json,sys
city=json.load(open(sys.argv[1]))
if city.get('label')!='Minneapolis, MN':raise SystemExit('The city lookup did not return the expected city.')
print('City lookup verified: Minneapolis, MN.')
PYCITY
elif [[ "$WEATHER_NAME_STATUS" == 502 ]]; then
  echo 'City-name service is temporarily unavailable. Weather remains available; reopen the page later to retry the city lookup.'
else
  echo "The city endpoint returned HTTP $WEATHER_NAME_STATUS; website update finished but city lookup needs checking." >&2
  exit 1
fi
printf '\nOpen https://weather-lab.cloud.run and refresh each device.\nOnly the website was updated; collection schedules are unchanged.\nSaved settings: %s\n' "$WEATHER_WORK"
