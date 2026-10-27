#!/usr/bin/env bash
# Restore the saved airport METAR layout and stop retired mesonet pulls.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261027-024631-5ff2}"
WEATHER_REGION=us-central1
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-metars.XXXXXX")"
trap 'echo "METAR update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"

echo 'Step 1/5: saving the working website and collection settings.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/website-before.json"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
WEATHER_CURRENT_IMAGE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["spec"]["template"]["spec"]["containers"][0]["image"])' "$WEATHER_WORK/website-before.json")"
WEATHER_IMAGE_PATH="${WEATHER_CURRENT_IMAGE%%@*}";WEATHER_IMAGE_PATH="${WEATHER_IMAGE_PATH%:*}"
case "$WEATHER_IMAGE_PATH" in
  "$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/"*"/app") ;;
  *) echo 'Unexpected image registry; no deployment started.' >&2; exit 1 ;;
esac
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_IMAGE_PATH:metars-${WEATHER_COMMIT:0:12}"

echo 'Step 2/5: building the saved METAR layout and prepared-data loading.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
test -n "$WEATHER_COLLECTOR_URL"

echo 'Step 3/5: stopping mesonet collection and refreshing the prepared weather products.'
python3 - "$WEATHER_WORK/jobs-before.json" >"$WEATHER_WORK/retired.txt" <<'PY'
import json,sys
for job in json.load(open(sys.argv[1])):
    name=job['name'].rsplit('/',1)[-1]
    if name in {'weather-live-observation-stations','weather-live-current','weather-live-madis','weather-live-observations'}:print(name)
PY
while IFS= read -r WEATHER_JOB; do
  gcloud scheduler jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
done <"$WEATHER_WORK/retired.txt"
for WEATHER_KIND in metar-clouds radar-KMPX satellite forecast air-quality; do
  printf 'Preparing %s\n' "$WEATHER_KIND"
  curl -fsS --max-time 300 -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$WEATHER_COLLECTOR_URL/collect/$WEATHER_KIND" -o "$WEATHER_WORK/$WEATHER_KIND.json"
done

echo 'Step 4/5: publishing METAR, Radar, Satellite, Forecast and Air Q.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --update-env-vars=WEATHER_PREPARED_ONLY=true --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/station-plots" -o "$WEATHER_WORK/metars.json"
python3 - "$WEATHER_WORK" <<'PY'
from pathlib import Path
import json,re,sys
work=Path(sys.argv[1]);html=(work/'page.html').read_text();data=json.loads((work/'metars.json').read_text())
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['metar','radar','satellite','forecast','air-quality']:
    raise SystemExit('The five expected tabs were not verified.')
combined='data-station-model="combined-v1"' in html and 'metar-model.js?v=metar-combined-v1' in html
separate=all(f'<option value="{mode}">' in html for mode in ('clouds','wind','dewpoint','temperature'))
if not (combined or separate) or 'prepared-data.js?v=metar-products-v1' not in html:
    raise SystemExit('The METAR station model or preloading assets are missing.')
frames=data.get('history',[])
if data.get('sourcePolicy')!='airport-routine-only' or data.get('stationPolicy')!='all-airports-v1' or len(frames)!=12 or any(not f.get('stations') for f in frames):
    raise SystemExit('Twelve populated all-airport hourly frames were not verified.')
if any(r.get('reportType')!='METAR' or not 45<=int(r['time'][14:16])<=59 for f in frames for r in f['stations']):
    raise SystemExit('An ineligible observation reached the airport page.')
print('Verified: saved METAR station model, twelve routine airport hours, Sun angle and five tabs.')
PY

echo 'Step 5/5: checking the other pages and warming their newest prepared files.'
python3 - "$WEATHER_URL" <<'PY'
import json,sys
from urllib.request import urlopen,Request
base=sys.argv[1]
for endpoint in ('radar?site=KMPX','satellite/truecolor','satellite/dcphase','satellite/ntmicro','forecast','air-quality'):
    with urlopen(Request(base+'/api/'+endpoint,headers={'User-Agent':'Weather Lab deploy readiness check'}),timeout=90) as response:data=json.load(response)
    frames=data.get('frames',[])
    if endpoint=='forecast':
        if not data.get('periods'):raise SystemExit('The prepared forecast is empty.')
    elif not frames:raise SystemExit('No prepared frames for '+endpoint)
    if frames and frames[-1].get('url','').startswith('/api/prepared/'):
        with urlopen(base+frames[-1]['url'],timeout=90) as response:response.read()
    print(endpoint,': ready')
PY
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nMETAR update complete.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
