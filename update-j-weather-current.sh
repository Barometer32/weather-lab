#!/usr/bin/env bash
# Apply Current/metro rendering to the existing J-Weather website.
set -euo pipefail
WEATHER_PROJECT="j-weather-261020012817"
WEATHER_REGION="us-central1"
WEATHER_BRANCH="metar-cloud-history-20261019"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-current-update.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings and output: $WEATHER_WORK" >&2' ERR

echo "Step 1/4: checking J-Weather and saving website settings."
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
WEATHER_PREVIOUS_IMAGE="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.containers[0].image)')"
printf '%s\n' "$WEATHER_PREVIOUS_IMAGE" >"$WEATHER_WORK/previous-image.txt"
git clone --quiet --depth=1 --branch "$WEATHER_BRANCH" https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:current-${WEATHER_COMMIT:0:12}"

echo "Step 2/4: building the Current and combined metro update."
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi

echo "Step 3/4: deploying the website update."
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet

echo "Step 4/4: verifying Current and the twelve-hour METAR response."
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/observations" -o "$WEATHER_WORK/current.json"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/metar-clouds" -o "$WEATHER_WORK/metar.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1])
html=(work/'page.html').read_text()
if 'id="tab-current"' not in html or 'current-views.js' not in html or 'id="hopkins-sun-angle"' not in html:
    raise SystemExit('Current is not present in the published page yet.')
summary=json.loads((work/'current.json').read_text())
metars=json.loads((work/'metar.json').read_text())
if len(summary.get('history',[]))!=12 or len(metars.get('history',[]))!=12:
    raise SystemExit('The published response does not contain twelve hourly positions.')
metro=metars.get('metro')
if not metro or metro.get('station')!='METRO' or any('metro' not in h for h in metars['history']):
    raise SystemExit('The combined metro plot is missing from the published response.')
if any('cloudSource' not in h['metro'] for h in metars['history']):
    raise SystemExit('The metro cloud-source metadata is missing.')
print('Verified: Current tab, Hopkins sun-angle element, and 12 hourly METAR positions.')
print(f'Metro hour: {metro["hour"]}; {metro["qa"]["stationsUsed"]}/3 airport reports passed basic QA.')
if not metro['available']:
    print('The newest metro average is incomplete; its popup identifies missing or invalid contributors.')
print('Populated regional hours:',sum(bool(h['stations']) for h in metars['history']),'/12')
PY
printf '\nUpdate complete. Open your usual J-Weather address and refresh.\nService URL: %s\nSource: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
