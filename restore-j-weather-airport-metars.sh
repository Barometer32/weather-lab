#!/usr/bin/env bash
# Restore the airport-only layout in the existing J-Weather project.
set -euo pipefail
WEATHER_PROJECT="${1:-j-weather-261020012817}"
WEATHER_REGION=us-central1
# Scope quota attribution only for this restore process and its children.
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-airports.XXXXXX")"
WEATHER_PAUSED=()
weather_cleanup() {
  local weather_code="$?" weather_job
  for weather_job in "${WEATHER_PAUSED[@]}"; do
    gcloud scheduler jobs resume "$weather_job" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" || true
  done
  if [[ "$weather_code" != 0 ]]; then echo "Restore stopped. Saved settings and source: $WEATHER_WORK" >&2; fi
}
trap weather_cleanup EXIT

echo 'Step 1/5: checking project restoration and billing.'
WEATHER_STATE="$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')"
if [[ "$WEATHER_STATE" == DELETE_REQUESTED ]]; then
  gcloud projects undelete "$WEATHER_PROJECT"
  WEATHER_STATE="$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')"
fi
if [[ "$WEATHER_STATE" != ACTIVE ]]; then echo 'Restore this project in Google Cloud first.' >&2; exit 1; fi
WEATHER_BILLING="$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)')"
if [[ "${WEATHER_BILLING,,}" != true ]]; then
  echo "Link an active billing account to $WEATHER_PROJECT at https://console.cloud.google.com/billing/projects and rerun this command." >&2
  exit 1
fi
gcloud config set project "$WEATHER_PROJECT"
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
bash "$WEATHER_WORK/source/ensure-weather-apis.sh" "$WEATHER_PROJECT"
gcloud run services list --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/services-before.json"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:airports-${WEATHER_COMMIT:0:12}"
WEATHER_BUCKET="$WEATHER_PROJECT-weather-data"
WEATHER_COLLECTOR_SA="weather-collector@$WEATHER_PROJECT.iam.gserviceaccount.com"

echo 'Step 2/5: rebuilding missing resources and deploying the collector.'
(
  cd "$WEATHER_WORK/source"
  WEATHER_APIS_VERIFIED=true WEATHER_DEPLOY_IMAGE="$WEATHER_IMAGE" WEATHER_DEFER_WEB=true bash deploy.sh "$WEATHER_PROJECT"
)
# Pause the four managed jobs while the one-time imports publish their objects.
for WEATHER_JOB in weather-live-radar weather-live-satellite weather-live-forecast weather-live-metar-clouds; do
  gcloud scheduler jobs pause "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  WEATHER_PAUSED+=("$WEATHER_JOB")
done

echo 'Step 3/5: downloading twelve hourly airport frames and recovering imagery.'
# No MADIS, mesonet or Current collection is imported.
gcloud run jobs deploy weather-airports-restore --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args='^|^-c|import metar_history; import refresh_media; metar_history.main(); refresh_media.main()' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=1800s --quiet
if ! gcloud run jobs execute weather-airports-restore --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait; then
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="weather-airports-restore"' --project="$WEATHER_PROJECT" --freshness=45m --limit=30 --format='value(textPayload,jsonPayload.message)'
  exit 1
fi

echo 'Step 4/5: publishing and verifying the airport-only METAR page.'
gcloud run deploy weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --allow-unauthenticated --service-account="weather-web@$WEATHER_PROJECT.iam.gserviceaccount.com" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90 --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/station-plots" -o "$WEATHER_WORK/metars.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,re,sys
from pathlib import Path
work=Path(sys.argv[1]);page=(work/'page.html').read_text();data=json.loads((work/'metars.json').read_text())
if re.findall(r'<button role="tab" id="tab-([^\"]+)"',page)!=['metar-clouds','radar','satellite','forecast','air-quality']:
    raise SystemExit('The five expected tabs are not published yet.')
if 'current-views.js' in page or data.get('sourcePolicy')!='airport-routine-only' or data.get('stationPolicy')!='all-airports-v1':
    raise SystemExit('The airport-only station policy has not been published.')
frames=data.get('history',[])
if len(frames)!=12 or any(not frame.get('stations') for frame in frames):
    raise SystemExit('Twelve populated hourly frames are not ready; inspect the restore job logs.')
for frame in frames:
    for row in frame['stations']:
        if row.get('reportType')!='METAR' or not 45<=int(row['time'][14:16])<=59:
            raise SystemExit('An ineligible report reached the airport map.')
    print(frame['hour'],len(frame['stations']),'airport METARs')
print('Verified: no Current tab, all-airport policy, twelve routine hourly frames.')
PY

echo 'Step 5/5: resuming hourly collection and removing retired rapid jobs.'
for WEATHER_JOB in "${WEATHER_PAUSED[@]}"; do
  gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done
WEATHER_PAUSED=()
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-after.json"
python3 - "$WEATHER_WORK/jobs-after.json" >"$WEATHER_WORK/retired.txt" <<'PY'
import json,sys
for row in json.load(open(sys.argv[1])):
    name=row['name'].rsplit('/',1)[-1]
    if name in {'weather-live-current','weather-live-madis','weather-live-observations'}:print(name)
PY
while IFS= read -r WEATHER_JOB; do
  gcloud scheduler jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
done <"$WEATHER_WORK/retired.txt"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nAirport METAR restore complete.\nWebsite: %s\nSource: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
