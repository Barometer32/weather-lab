#!/usr/bin/env bash
# Finish a verified 1afc57b rollback without building or deploying anything.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
[[ "$WEATHER_PROJECT" == weather-lab-261028-205713-506d ]] || { echo 'This finisher is scoped to the 506d project.' >&2; exit 1; }
WEATHER_REGION=us-central1
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-metar-finish.XXXXXX")"
trap 'echo "Finish stopped at line $LINENO. Diagnostics: $WEATHER_WORK" >&2' ERR
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/web.json"
WEATHER_URL="$(python3 - "$WEATHER_WORK/web.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
if not s.get('status',{}).get('url'):raise SystemExit('No deployed website URL.')
if not any(c.get('type')=='Ready' and c.get('status')=='True' for c in s['status'].get('conditions',[])):
    raise SystemExit('The website is not Ready.')
print(s['status']['url'])
PY
)"
echo "Step 1/3: verifying the deployed METAR site and prepared products."
curl --retry 3 --retry-delay 2 -fsSL --max-time 90 \
  https://raw.githubusercontent.com/Barometer32/weather-lab/1afc57b91559de5a3decb15cf699f49b525604a8/static/metar-model.js \
  -o "$WEATHER_WORK/expected-model.js"
python3 - "$WEATHER_URL" "$WEATHER_WORK/expected-model.js" <<'PY'
import json,re,sys
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse
def verify(base, expected, fetch=None):
    origin=urlparse(base)
    if origin.scheme!='https' or not origin.hostname or origin.path not in ('','/'):
        raise ValueError('Expected an HTTPS website origin.')
    def download(path):
        with urlopen(Request(base.rstrip('/')+path,headers={'Cache-Control':'no-cache','User-Agent':'Weather Lab finish check'}),timeout=90) as response:
            return response.read()
    fetch=fetch or download
    html=fetch('/').decode()
    tabs=re.findall(r'<button role="tab" id="tab-([^"]+)"',html)
    if tabs!=['metar','radar','satellite','forecast','air-quality']:
        raise ValueError('The original five tabs are not deployed.')
    picker=re.search(r'<select id="metar-product"[^>]*>(.*?)</select>',html,re.S)
    if not picker or re.findall(r'<option value="([^"]+)">',picker[1])!=['plots','clouds']:
        raise ValueError('The PLOTS/CLOUDS dropdown is missing.')
    asset='/static/metar-model.js?v=metar-barb-staff-plus5-v1'
    if asset not in html or fetch(asset)!=expected:
        raise ValueError('The saved 5% longer wind-barb renderer was not verified.')
    if any(x in html.lower() for x in ('use my location','location-choice.js','current-views.js')):
        raise ValueError('Unexpected location or CURRENT controls.')
    data=json.loads(fetch('/api/station-plots'))
    frames=data.get('history',[])
    if data.get('sourcePolicy')!='airport-routine-only' or data.get('stationPolicy')!='all-airports-v1' or len(frames)!=12 or any(not f.get('stations') for f in frames):
        raise ValueError('Prepared airport history is incomplete.')
    for frame in frames:
        for row in frame['stations']:
            if row.get('reportType')!='METAR' or not 45<=int(row['time'][14:16])<=59:
                raise ValueError('A report is outside the routine airport window.')
    print('METAR: original PLOTS/CLOUDS and 5% longer barbs verified.',flush=True)
    for endpoint in ('radar?site=KMPX','satellite/truecolor','satellite/dcphase','satellite/ntmicro','forecast','air-quality'):
        product=json.loads(fetch('/api/'+endpoint))
        if endpoint=='forecast':
            if not product.get('periods'):raise ValueError('Prepared forecast is empty.')
        else:
            if not product.get('frames'):raise ValueError('No prepared frames: '+endpoint)
            asset=product['frames'][-1].get('url','')
            if not asset.startswith('/api/prepared/') or '..' in asset.split('/') or not fetch(asset):
                raise ValueError('Invalid prepared asset: '+endpoint)
        print(endpoint+': ready',flush=True)
if __name__=='__main__':
    verify(sys.argv[1],Path(sys.argv[2]).read_bytes())
PY
echo "Step 2/3: checking schedules and removing the retired CURRENT collector."
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs.json"
python3 - "$WEATHER_WORK/jobs.json" >"$WEATHER_WORK/job-actions.txt" <<'PY'
import json,sys
jobs={j['name'].rsplit('/',1)[-1]:j for j in json.load(open(sys.argv[1]))}
required={'weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds','weather-live-air-quality'}
if required-jobs.keys():raise SystemExit('Missing weather schedules: '+', '.join(sorted(required-jobs.keys())))
for name in sorted(required):
    state=jobs[name].get('state')
    if state=='PAUSED':print('resume',name)
    elif state!='ENABLED':raise SystemExit('Unexpected scheduler state: '+name+' '+str(state))
if 'weather-live-current-analysis' in jobs:print('delete','weather-live-current-analysis')
PY
while read -r WEATHER_ACTION WEATHER_JOB; do
  gcloud scheduler jobs "$WEATHER_ACTION" "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
done <"$WEATHER_WORK/job-actions.txt"
gcloud run services list --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/services.json"
if python3 - "$WEATHER_WORK/services.json" <<'PY'
import json,sys
sys.exit(0 if any(s.get('metadata',{}).get('name')=='weather-current-collector' for s in json.load(open(sys.argv[1]))) else 1)
PY
then
  gcloud run services delete weather-current-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
fi
echo "Step 3/3: checking weather-lab.cloud.run."
if gcloud beta run domain-mappings describe --domain=weather-lab.cloud.run --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/domain.json" 2>"$WEATHER_WORK/domain.err"; then
  python3 - "$WEATHER_WORK/domain.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
if d.get('spec',{}).get('routeName')!='weather-lab':raise SystemExit('The custom address points to a different service; left unchanged.')
ready=any(c.get('type')=='Ready' and c.get('status')=='True' for c in d.get('status',{}).get('conditions',[]))
print('Custom address is ready.' if ready else 'Custom address exists; routing is still pending. Use the direct URL meanwhile.')
PY
elif grep -qi 'NOT_FOUND|not found|does not exist' "$WEATHER_WORK/domain.err"; then
  gcloud beta run domain-mappings create --service=weather-lab --domain=weather-lab.cloud.run --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
  echo 'Custom address requested; routing may still be pending.'
else
  cat "$WEATHER_WORK/domain.err" >&2
  exit 1
fi
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nFinish complete. No container was rebuilt or redeployed.\nWebsite: https://weather-lab.cloud.run\nDirect URL: %s\nDiagnostics: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
