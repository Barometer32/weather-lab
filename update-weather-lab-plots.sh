#!/usr/bin/env bash
# Update only the website currently serving weather-lab.cloud.run.
set -euo pipefail
WEATHER_REGION=us-central1
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-plots.XXXXXX")"
trap 'echo "Plot update stopped at line $LINENO. Settings and diagnostics: $WEATHER_WORK" >&2' ERR

echo 'Step 1/3: selecting the website project and saving its settings.'
if [[ -n "${1:-}" ]]; then
  WEATHER_PROJECT="$1"
else
WEATHER_CANDIDATES=(j-weather-261020012817 weather-lab-261024-133205)
WEATHER_OWNERS=()
for WEATHER_CANDIDATE in "${WEATHER_CANDIDATES[@]}"; do
  if gcloud beta run domain-mappings describe --domain=weather-lab.cloud.run --project="$WEATHER_CANDIDATE" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_CANDIDATE-mapping.json" 2>"$WEATHER_WORK/$WEATHER_CANDIDATE-mapping.err"; then
    if python3 - "$WEATHER_WORK/$WEATHER_CANDIDATE-mapping.json" <<'PY'
import json,sys
mapping=json.load(open(sys.argv[1]))
sys.exit(0 if mapping.get('metadata',{}).get('name')=='weather-lab.cloud.run' and mapping.get('spec',{}).get('routeName')=='weather-lab' else 1)
PY
    then WEATHER_OWNERS+=("$WEATHER_CANDIDATE"); fi
  fi
done
if [[ "${#WEATHER_OWNERS[@]}" != 1 ]]; then
  echo 'Could not verify exactly one project mapping weather-lab.cloud.run to weather-lab. Pass the confirmed project ID as the script argument. No build or deployment was started.' >&2
  for WEATHER_CANDIDATE in "${WEATHER_CANDIDATES[@]}"; do cat "$WEATHER_WORK/$WEATHER_CANDIDATE-mapping.err" >&2; done
  exit 1
fi
WEATHER_PROJECT="${WEATHER_OWNERS[0]}"
fi
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
printf 'Updating project: %s\n' "$WEATHER_PROJECT"
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
WEATHER_CURRENT_IMAGE="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.containers[0].image)')"
WEATHER_IMAGE_PATH="${WEATHER_CURRENT_IMAGE%%@*}"
WEATHER_IMAGE_PATH="${WEATHER_IMAGE_PATH%:*}"
case "$WEATHER_IMAGE_PATH" in
  "$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/"*"/app") ;;
  *) echo 'The website image uses an unexpected registry path. No build or deployment was started.' >&2; exit 1 ;;
esac
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_IMAGE_PATH:plots-${WEATHER_COMMIT:0:12}"

echo 'Step 2/3: building the combined station plots and updating only the website.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo 'Step 3/3: verifying the combined METAR plots and tabs.'
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_WEB_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK/page.html" <<'PY'
from pathlib import Path
import sys
html=Path(sys.argv[1]).read_text()
for asset in ['metar-model.js?v=combined-station-v1','cloud-views.js?v=combined-station-v1','app.js?v=combined-station-v1']:
    if '/static/'+asset not in html:raise SystemExit('The compact plot assets are not published yet.')
if 'id="tab-clouds"' in html or 'cloud-height-views.js' in html or 'id="metar-cloud-timeline"' not in html:
    raise SystemExit('The combined METAR page is not published yet.')
print('Verified combined cloud-cover station circles, wind barbs and 12-hour METAR history.')
PY
printf '\nPlot update complete.\nWebsite: https://weather-lab.cloud.run\nProject: %s\nDirect URL: %s\nSaved settings: %s\n' "$WEATHER_PROJECT" "$WEATHER_WEB_URL" "$WEATHER_WORK"
