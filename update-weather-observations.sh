#!/usr/bin/env bash
# Publish the Hennepin station list; retain the airport collector for CLOUDS.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261024-133205}"
WEATHER_REGION=us-central1
WEATHER_WORK="$(mktemp -d "$HOME/weather-observations.XXXXXX")"
trap 'echo "Observation update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"

echo "Step 1/4: saving settings for $WEATHER_PROJECT."
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/website-before.json"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
WEATHER_CURRENT_IMAGE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["spec"]["template"]["spec"]["containers"][0]["image"])' "$WEATHER_WORK/website-before.json")"
WEATHER_IMAGE_PATH="${WEATHER_CURRENT_IMAGE%%@*}"
WEATHER_IMAGE_PATH="${WEATHER_IMAGE_PATH%:*}"
case "$WEATHER_IMAGE_PATH" in
  "$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/"*"/app") ;;
  *) echo 'Unexpected website registry path; no changes started.' >&2; exit 1 ;;
esac
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_IMAGE_PATH:observations-${WEATHER_COMMIT:0:12}"

echo 'Step 2/4: building the Observations page and its background collector.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --memory=2Gi --timeout=300 --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
test -n "$WEATHER_COLLECTOR_URL"

echo 'Step 3/4: collecting the station list and enabling two-minute checks.'
WEATHER_SCHEDULER="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com"
gcloud run services add-iam-policy-binding weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --member="serviceAccount:$WEATHER_SCHEDULER" --role=roles/run.invoker --quiet >/dev/null
for WEATHER_TRY in 1 2 3; do
  curl -fsS --max-time 300 -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$WEATHER_COLLECTOR_URL/collect/observation-stations" -o "$WEATHER_WORK/initial-collection.json"
  if python3 -c 'import json,sys;sys.exit(0 if json.load(open(sys.argv[1])).get("status")=="prepared" else 1)' "$WEATHER_WORK/initial-collection.json"; then break; fi
  if [[ "$WEATHER_TRY" == 3 ]]; then echo 'The station collector is still busy; rerun this update after it finishes.' >&2; exit 1; fi
  echo 'A scheduled collection is already running; checking again shortly.'
  sleep 10
done
WEATHER_ACTION="$(python3 -c 'import json,sys;print("update" if any(j["name"].rsplit("/",1)[-1]=="weather-live-observation-stations" for j in json.load(open(sys.argv[1]))) else "create")' "$WEATHER_WORK/jobs-before.json")"
gcloud scheduler jobs "$WEATHER_ACTION" http weather-live-observation-stations --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='*/2 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/observation-stations" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-observation-stations --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-observation-stations --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi

echo 'Step 4/4: publishing and verifying Observations and CLOUDS.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/observation-stations" -o "$WEATHER_WORK/stations.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,re,sys
from pathlib import Path
work=Path(sys.argv[1]);html=(work/'page.html').read_text();data=json.loads((work/'stations.json').read_text())
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['observations','radar','clouds','satellite','forecast','air-quality']:
    raise SystemExit('The expected Observations page is not published yet.')
if data.get('version')!='hennepin-west-station-list-v1' or not data.get('stations') or any(row.get('network')!='Hennepin West' for row in data['stations']) or data.get('average') is not None:
    raise SystemExit('The station list is not ready; inspect the saved collection response.')
if 'id="clouds-timeline"' not in html or 'cloud-dots-v2' not in html:
    raise SystemExit('The CLOUDS history or exact-location dot update is missing.')
print('Verified',len(data['stations']),'Hennepin West sites in Hennepin County. No average has been selected.')
for row in data['stations']:
    print(row['station'],row['displayName'],row['network'],row['time'])
PY
printf '\nObservations update complete.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
