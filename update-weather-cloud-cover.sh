#!/usr/bin/env bash
# Publish CLOUDS sky cover and ceiling labels; retain collection and service settings.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass a Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-cloud-cover.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
echo 'Step 1/3: saving website settings and fetching the cloud-cover layout.'
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
git clone --quiet --depth=1 --branch weather-cloud-cover-20261104 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_IMAGE_PATH:cloud-cover-${WEATHER_COMMIT:0:12}"
echo 'Step 2/3: building and publishing the website layout.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
echo 'Step 3/3: verifying the published cloud circles.'
python3 - "$WEATHER_URL" "$WEATHER_WORK/source" <<'PY'
import re,sys,time
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
base=sys.argv[1];source=Path(sys.argv[2])
def get(path):
    for attempt in range(8):
        try:
            with urlopen(Request(base+path,headers={'User-Agent':'Weather Lab cloud-cover check','Cache-Control':'no-cache'}),timeout=90) as response:return response.read()
        except HTTPError as error:
            if error.code not in (429,500,502,503,504) or attempt==7:raise
        except (URLError,TimeoutError):
            if attempt==7:raise
        time.sleep(min(5*(attempt+1),30))
html=get('/').decode();asset='/static/style.css?v=phone-controls-v1'
if re.findall(r'<button role="tab" id="tab-([^\"]+)"',html)!=['metar','radar','satellite','forecast','air-quality']:
    raise SystemExit('The original five weather tabs were not verified.')
if asset not in html or get(asset)!=(source/'static/style.css').read_bytes():
    raise SystemExit('The compact phone stylesheet was not verified.')
if 'id="radar-product"' in html:raise SystemExit('Unexpected radar product selector.')
for name in ('metar-model.js','metar-views.js'):
    asset='/static/'+name+'?v=cloud-cover-circle-v2'
    if asset not in html or get(asset)!=(source/'static'/name).read_bytes():
        raise SystemExit('The cloud-cover script was not verified: '+name)
print('Verified cloud sky-cover circles, height labels and the original five-tab site.')
PY
printf '\nCloud cover update complete. Refresh the website and select METAR > CLOUDS.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
