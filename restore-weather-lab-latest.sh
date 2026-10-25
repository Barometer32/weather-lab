#!/usr/bin/env bash
# Restore the latest saved layout in the same project; never create a project.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261024-133205}"
WEATHER_REGION=us-central1
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-latest.XXXXXX")"
WEATHER_PAUSED=()
weather_cleanup() {
  local weather_code="$?" weather_job
  for weather_job in "${WEATHER_PAUSED[@]}"; do
    if ! gcloud scheduler jobs resume "$weather_job" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"; then weather_code=1; fi
  done
  if [[ "$weather_code" != 0 ]]; then echo "Restore stopped. Saved settings and diagnostics: $WEATHER_WORK" >&2; fi
  trap - EXIT
  exit "$weather_code"
}
trap weather_cleanup EXIT

echo "Step 1/6: restoring $WEATHER_PROJECT and checking billing."
WEATHER_STATE="$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')"
if [[ "$WEATHER_STATE" == DELETE_REQUESTED ]]; then gcloud projects undelete "$WEATHER_PROJECT"; fi
[[ "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" == ACTIVE ]] || { echo 'This project could not be restored; no replacement project was created.' >&2; exit 1; }
WEATHER_ENABLED="$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)')"
if [[ "${WEATHER_ENABLED,,}" != true ]]; then
  WEATHER_BILLING="${2:-}"
  if [[ -z "$WEATHER_BILLING" ]]; then
    gcloud billing accounts list --filter='open=true' --format=json >"$WEATHER_WORK/open-billing.json"
    WEATHER_BILLING="$(python3 - "$WEATHER_WORK/open-billing.json" <<'PY'
import json,sys
accounts=json.load(open(sys.argv[1]))
if len(accounts)==1:print(accounts[0]['name'].rsplit('/',1)[-1])
PY
)"
  fi
  if [[ -z "$WEATHER_BILLING" ]]; then
    echo 'Open your billing account at https://console.cloud.google.com/billing and link this project at https://console.cloud.google.com/billing/projects, then rerun this restore.' >&2
    echo 'If multiple accounts are open, pass the intended billing account ID as the second argument.' >&2
    exit 1
  fi
  WEATHER_OPEN="$(gcloud billing accounts describe "$WEATHER_BILLING" --format='value(open)')"
  [[ "${WEATHER_OPEN,,}" == true ]] || { echo 'Reopen the selected billing account in the Google Cloud console first.' >&2; exit 1; }
  gcloud billing projects link "$WEATHER_PROJECT" --billing-account="$WEATHER_BILLING"
fi
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
gcloud config set project "$WEATHER_PROJECT"
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
bash "$WEATHER_WORK/source/ensure-weather-apis.sh" "$WEATHER_PROJECT"
gcloud run services list --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/services-before.json"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
WEATHER_REPOSITORY="$(python3 - "$WEATHER_WORK/services-before.json" "$WEATHER_PROJECT" <<'PY'
import json,sys
prefix='us-central1-docker.pkg.dev/'+sys.argv[2]+'/'
for service in json.load(open(sys.argv[1])):
    if service.get('metadata',{}).get('name') not in ('weather-lab','weather-collector'):continue
    image=service['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
    if image.startswith(prefix) and image.endswith('/app'):
        print(image[len(prefix):].rsplit('/',1)[0]);break
else:print('weather-lab')
PY
)"
python3 - "$WEATHER_WORK/jobs-before.json" >"$WEATHER_WORK/pause-before.txt" <<'PY'
import json,sys
managed={'weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds','weather-live-air-quality','weather-live-observation-stations'}
for job in json.load(open(sys.argv[1])):
    name=job['name'].rsplit('/',1)[-1]
    if name in managed and job.get('state')=='ENABLED':print(name)
PY
while IFS= read -r WEATHER_JOB; do
  gcloud scheduler jobs pause "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  WEATHER_PAUSED+=("$WEATHER_JOB")
done <"$WEATHER_WORK/pause-before.txt"

echo 'Step 2/6: rebuilding the latest website and replacing missing weather resources.'
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/$WEATHER_REPOSITORY/app:restore-${WEATHER_COMMIT:0:12}"
(
  cd "$WEATHER_WORK/source"
  WEATHER_APIS_VERIFIED=true WEATHER_ARTIFACT_REPOSITORY="$WEATHER_REPOSITORY" WEATHER_DEPLOY_IMAGE="$WEATHER_IMAGE" WEATHER_DEFER_WEB=true WEATHER_DEFER_COLLECTION=true WEATHER_COLLECTOR_MEMORY=2Gi bash deploy.sh "$WEATHER_PROJECT"
)
for WEATHER_JOB in weather-live-radar weather-live-satellite weather-live-forecast weather-live-metar-clouds weather-live-air-quality; do
  if [[ " ${WEATHER_PAUSED[*]} " != *" $WEATHER_JOB "* ]]; then WEATHER_PAUSED+=("$WEATHER_JOB"); fi
done
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-after-deploy.json"
python3 - "$WEATHER_WORK/jobs-after-deploy.json" >"$WEATHER_WORK/retired-observations.txt" <<'PYINNER'
import json,sys
for job in json.load(open(sys.argv[1])):
    name=job['name'].rsplit('/',1)[-1]
    if name in {'weather-live-observation-stations','weather-live-current','weather-live-madis','weather-live-observations'}:print(name)
PYINNER
while IFS= read -r WEATHER_JOB; do
  gcloud scheduler jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
  WEATHER_KEPT=()
  for WEATHER_PAUSED_JOB in "${WEATHER_PAUSED[@]}"; do if [[ "$WEATHER_PAUSED_JOB" != "$WEATHER_JOB" ]]; then WEATHER_KEPT+=("$WEATHER_PAUSED_JOB"); fi; done
  WEATHER_PAUSED=("${WEATHER_KEPT[@]}")
done <"$WEATHER_WORK/retired-observations.txt"

echo 'Step 3/6: collecting twelve airport METAR hours, radar and satellite history.'
WEATHER_JOB="weather-latest-$(date -u +%y%m%d-%H%M%S)-${WEATHER_WORK##*.}"
WEATHER_JOB="${WEATHER_JOB,,}"
printf '%s\n' "$WEATHER_JOB" >"$WEATHER_WORK/data-job.txt"
gcloud run jobs deploy "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="weather-collector@$WEATHER_PROJECT.iam.gserviceaccount.com" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --command=python --args='-u,restore_latest_data.py' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=1800s --quiet
if ! gcloud run jobs execute "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait; then
  gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$WEATHER_JOB\"" --project="$WEATHER_PROJECT" --freshness=1h --limit=30 --format=json || true
  exit 1
fi

echo 'Step 4/6: publishing the latest five-tab website.'
gcloud run deploy weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --allow-unauthenticated --service-account="weather-web@$WEATHER_PROJECT.iam.gserviceaccount.com" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data,WEATHER_PREPARED_ONLY=true" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90 --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/station-plots" -o "$WEATHER_WORK/clouds.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,re,sys
from pathlib import Path
work=Path(sys.argv[1]);html=(work/'page.html').read_text();clouds=json.loads((work/'clouds.json').read_text())
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['metar','radar','satellite','forecast','air-quality']:
    raise SystemExit('Latest saved tabs were not verified.')
if len(clouds.get('history',[]))!=12 or any(not f.get('stations') for f in clouds['history']):
    raise SystemExit('The twelve airport cloud frames are not populated.')
if 'metar-product' not in html or 'metar-products-v1' not in html:raise SystemExit('The four METAR products are missing.')
print('Verified four-product METAR, Radar, Satellite, Forecast and Air Q with twelve airport hours.')
PY

echo 'Step 5/6: enabling all five weather collection schedules.'
for WEATHER_JOB in "${WEATHER_PAUSED[@]}"; do
  gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done
WEATHER_PAUSED=()

echo 'Step 6/6: checking the weather-lab.cloud.run address.'
if gcloud beta run domain-mappings describe --domain=weather-lab.cloud.run --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/domain.json" 2>"$WEATHER_WORK/domain.err"; then
  python3 - "$WEATHER_WORK/domain.json" <<'PY'
import json,sys
mapping=json.load(open(sys.argv[1]))
print('Existing custom address points to:',mapping.get('spec',{}).get('routeName','unknown'))
PY
else
  if ! gcloud beta run domain-mappings create --service=weather-lab --domain=weather-lab.cloud.run --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet >"$WEATHER_WORK/domain-create.txt" 2>"$WEATHER_WORK/domain.err"; then
    cat "$WEATHER_WORK/domain.err" >&2
    echo 'The website is restored. Use the direct address while the custom address is resolved.'
  fi
fi
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nLatest Weather Lab restore complete.\nProject: %s\nDirect website: %s\nCustom address, once routing is ready: https://weather-lab.cloud.run\nSaved settings: %s\n' "$WEATHER_PROJECT" "$WEATHER_URL" "$WEATHER_WORK"
