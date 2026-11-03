#!/usr/bin/env bash
# Publish the original five-tab site with a held METAR loop. Preserve runtime settings.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass the Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-metar-hour-hold.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Diagnostics: $WEATHER_WORK" >&2' ERR
echo 'Step 1/4: saving service settings and preparing the original five-tab source.'
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_SERVICE.json"
done
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
WEATHER_IMAGE_PATH="$(python3 - "$WEATHER_WORK/weather-lab.json" "$WEATHER_PROJECT" <<'PY'
import json,sys
image=json.load(open(sys.argv[1]))['spec']['template']['spec']['containers'][0]['image']
path=image.split('@',1)[0].split(':',1)[0]
if not path.startswith(f'us-central1-docker.pkg.dev/{sys.argv[2]}/') or not path.endswith('/app'):
    raise SystemExit('Unexpected website registry; no deployment started.')
print(path)
PY
)"
git clone --quiet --depth=1 --branch metar-hour-hold-20261103 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
python3 - "$WEATHER_WORK/source" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]);html=(p/'static/index.html').read_text()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['metar','radar','satellite','forecast','air-quality']:
    raise SystemExit('Expected the original five-tab site; no build started.')
if 'metar-hour-hold-v1' not in html or 'function readyWindow(' not in (p/'static/metar-views.js').read_text():
    raise SystemExit('The METAR hour hold is missing; no build started.')
PY
WEATHER_IMAGE="$WEATHER_IMAGE_PATH:hour-hold-${WEATHER_COMMIT:0:12}"
echo 'Step 2/4: building the held-loop update.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/4: updating the existing services without changing their other settings.'
for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services update "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
  gcloud run services update-traffic "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
done
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
echo 'Step 4/4: verifying the updated files and held airport history.'
python3 - "$WEATHER_URL" "$WEATHER_WORK/source" <<'PY'
import json,re,sys
from datetime import datetime,timedelta
from pathlib import Path
from urllib.request import Request,urlopen
base=sys.argv[1];source=Path(sys.argv[2])
def get(path):
    with urlopen(Request(base+path,headers={'Cache-Control':'no-cache','User-Agent':'Weather Lab hour hold check'}),timeout=90) as r:return r.read()
html=get('/').decode()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['metar','radar','satellite','forecast','air-quality']:
    raise SystemExit('The original tabs were not verified.')
for name,version in [('metar-views.js','metar-hour-hold-v1'),('metar-model.js','metar-barb-staff-plus5-v1')]:
    url='/static/'+name+'?v='+version
    if url not in html or get(url)!=(source/'static'/name).read_bytes():raise SystemExit('Updated asset was not verified: '+name)
d=json.loads(get('/api/station-plots'));frames=d.get('history',[])
if 'pendingHour' not in d or d.get('sourcePolicy')!='airport-routine-only' or len(frames)<4:
    raise SystemExit('The updated airport API was not verified.')
window=frames[-4:]
if any(not f.get('stations') for f in window):raise SystemExit('The latest four source hours are not populated; previous display is retained.')
times=[datetime.fromisoformat(f['hour'].replace('Z','+00:00')) for f in window]
if any(b-a!=timedelta(hours=1) for a,b in zip(times,times[1:])):raise SystemExit('Airport hours are not consecutive.')
print('Verified original five tabs, unchanged wind-barb renderer, held-loop viewer and populated airport history.')
print('Latest prepared hour:',window[-1]['hour'],'| pending hour:',d.get('pendingHour'),'| last successful collection:',d.get('checkedAt'))
PY
echo 'Requesting one initial METAR refresh; the recurring :00/:05/:10 schedule is unchanged.'
gcloud scheduler jobs run weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='yaml(state,schedule,lastAttemptTime,status)'
printf '\nUpdate deployed. The previous four-hour loop stays visible while a new batch arrives.\nWebsite: https://weather-lab.cloud.run\nDirect URL: %s\nDiagnostics: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
