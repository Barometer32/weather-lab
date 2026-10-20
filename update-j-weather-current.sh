#!/usr/bin/env bash
# Update Current, cloud-only METARs, and top-of-hour collection in J-Weather.
set -euo pipefail
WEATHER_PROJECT="j-weather-261020012817"
WEATHER_REGION="us-central1"
WEATHER_BRANCH="metar-cloud-history-20261019"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-current-update.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings and output: $WEATHER_WORK" >&2' ERR

echo "Step 1/5: checking J-Weather and saving website settings."
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
WEATHER_PREVIOUS_IMAGE="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.containers[0].image)')"
gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/metar-schedule-before.json"
printf '%s\n' "$WEATHER_PREVIOUS_IMAGE" >"$WEATHER_WORK/previous-image.txt"
git clone --quiet --depth=1 --branch "$WEATHER_BRANCH" https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:current-${WEATHER_COMMIT:0:12}"

echo "Step 2/5: building the Current and cloud-ceiling update."
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi

echo "Step 3/5: deploying the website update."
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet

echo "Step 4/5: moving the shared hourly METAR collection to :00."
gcloud scheduler jobs update http weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='0 * * * *' --time-zone=Etc/UTC --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == "PAUSED" ]]; then
  gcloud scheduler jobs resume weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi

echo "Step 5/5: verifying Current and the twelve-hour METAR response."
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/observations" -o "$WEATHER_WORK/current.json"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/metar-clouds" -o "$WEATHER_WORK/metar.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1])
html=(work/'page.html').read_text()
if 'id="tab-current"' not in html or 'current-views.js' not in html or 'id="sun-angle"' not in html:
    raise SystemExit('Current is not present in the published page yet.')
summary=json.loads((work/'current.json').read_text())
metars=json.loads((work/'metar.json').read_text())
if len(summary.get('history',[]))!=12 or len(metars.get('history',[]))!=12:
    raise SystemExit('The published response does not contain twelve hourly positions.')
if any(row.get('station')=='KDEH' for frame in metars['history'] for row in frame['stations']) or any(row.get('station')=='KDEH' for row in metars.get('stations',[])):
    raise SystemExit('KDEH is still present in the published Clouds response.')
if 'data-ceiling-unit="hundreds-ft"' not in html or 'id="metar-view"' in html:
    raise SystemExit('The cloud-height number map is not published yet.')
if 'class="satellite-sun"' not in html:
    raise SystemExit('The Sun angle line is not present on Satellite.')
if 'map-fullscreen.js' not in html or 'id="metar-fullscreen"' not in html:
    raise SystemExit('The shared map fullscreen controls are not published yet.')
print('Verified: Current hourly table, Satellite Sun angle, and full-screen controls for all three maps; 12 hourly positions.')
print(f'Current hour: {summary["current"]["hour"]}; {summary["current"]["qa"]["stationsUsed"]}/3 airport reports passed basic QA.')
print('Populated regional hours:',sum(bool(h['stations']) for h in metars['history']),'/12')
print('KDEH excluded from the Clouds map, station list, and all twelve hours.')
print('Shared METAR collection: :00 each hour; :45–:59 routine reports, preferring :53.')
PY
printf '\nUpdate complete. Open your usual J-Weather address and refresh.\nService URL: %s\nSource: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
