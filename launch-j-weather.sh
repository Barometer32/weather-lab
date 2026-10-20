#!/usr/bin/env bash
# Launch the latest saved Weather Lab site in its own J-Weather project.
set -euo pipefail
WEATHER_OLD_PROJECT="weather-lab-511113"
WEATHER_SOURCE_COMMIT="a2a337bef10204c84768da198b72f0e2ad348272"
WEATHER_REGION="us-central1"
WEATHER_WORK="$HOME/j-weather-launch"
mkdir -p "$WEATHER_WORK"
trap 'echo "Migration stopped at line $LINENO. Rerun the same command to resume; project information is in $WEATHER_WORK." >&2' ERR

weather_retry() {
  local weather_attempt
  for weather_attempt in 1 2 3 4 5 6; do
    if "$@"; then return 0; fi
    if [[ "$weather_attempt" == "6" ]]; then return 1; fi
    echo "Waiting 10 seconds for Google Cloud setup to propagate (attempt $weather_attempt/6)." >&2
    sleep 10
  done
}

echo "Step 1/7: checking the source and billing account."
if [[ ! -d "$WEATHER_WORK/source/.git" ]]; then
  git clone --quiet --no-checkout https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
if [[ "$(git -C "$WEATHER_WORK/source" rev-parse HEAD)" != "$WEATHER_SOURCE_COMMIT" ]]; then
  echo "The source directory is on a different revision. Stopping to preserve it." >&2
  exit 1
fi
WEATHER_BILLING="$(gcloud billing projects describe "$WEATHER_OLD_PROJECT" --format='value(billingAccountName)')"
WEATHER_BILLING="${WEATHER_BILLING##*/}"
if [[ -z "$WEATHER_BILLING" ]]; then
  echo "The old project has no linked billing account. Link it before running this migration." >&2
  exit 1
fi
WEATHER_BILLING_OPEN="$(gcloud billing accounts describe "$WEATHER_BILLING" --format='value(open)')"
if [[ "$WEATHER_BILLING_OPEN" != "True" && "$WEATHER_BILLING_OPEN" != "true" ]]; then
  echo "The linked billing account is not open." >&2
  exit 1
fi

echo "Step 2/7: creating or resuming the new project."
if [[ ! -s "$WEATHER_WORK/project-id.txt" ]]; then
  printf 'j-weather-%s\n' "$(date -u +%y%m%d%H%M%S)" >"$WEATHER_WORK/project-id.txt"
fi
WEATHER_PROJECT="$(cat "$WEATHER_WORK/project-id.txt")"
echo "NEW PROJECT ID: $WEATHER_PROJECT"
if [[ ! -f "$WEATHER_WORK/project-created" ]]; then
  if gcloud projects create "$WEATHER_PROJECT" --name="J-Weather" 2>"$WEATHER_WORK/project-create.err"; then
    touch "$WEATHER_WORK/project-created"
  elif grep -q 'ALREADY_EXISTS' "$WEATHER_WORK/project-create.err"; then
    gcloud projects describe "$WEATHER_PROJECT" --format='value(projectId)'
    touch "$WEATHER_WORK/project-created"
  else
    cat "$WEATHER_WORK/project-create.err" >&2
    exit 1
  fi
fi
WEATHER_STATE="$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')"
if [[ "$WEATHER_STATE" != "ACTIVE" ]]; then
  echo "The migration project is not ACTIVE. Stopping without creating another project." >&2
  exit 1
fi
gcloud billing projects link "$WEATHER_PROJECT" --billing-account="$WEATHER_BILLING"
gcloud config set project "$WEATHER_PROJECT"
weather_retry gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com iam.googleapis.com --project="$WEATHER_PROJECT"

WEATHER_BUCKET="gs://$WEATHER_PROJECT-weather-data"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:j-weather-a2a337bef102"
WEATHER_WEB_SA="weather-web@$WEATHER_PROJECT.iam.gserviceaccount.com"
WEATHER_COLLECTOR_SA="weather-collector@$WEATHER_PROJECT.iam.gserviceaccount.com"
WEATHER_BUILD_SA="weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com"
WEATHER_SCHEDULER_SA="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com"

echo "Step 3/7: preparing registry, identities, and private storage."
WEATHER_CREATOR="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
if [[ -z "$WEATHER_CREATOR" || "$WEATHER_CREATOR" == *$'\n'* ]]; then
  echo "Select one active gcloud account before continuing." >&2
  exit 1
fi
WEATHER_CREATOR_MEMBER="user:$WEATHER_CREATOR"
if [[ "$WEATHER_CREATOR" == *.gserviceaccount.com ]]; then WEATHER_CREATOR_MEMBER="serviceAccount:$WEATHER_CREATOR"; fi
weather_retry gcloud projects add-iam-policy-binding "$WEATHER_PROJECT" --member="$WEATHER_CREATOR_MEMBER" --role=roles/artifactregistry.admin --condition=None --quiet >/dev/null
if ! gcloud artifacts repositories describe weather-lab --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" >/dev/null 2>&1; then
  weather_retry gcloud artifacts repositories create weather-lab --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --repository-format=docker
fi
for WEATHER_SA in weather-web weather-collector weather-builder weather-scheduler; do
  if ! gcloud iam service-accounts describe "$WEATHER_SA@$WEATHER_PROJECT.iam.gserviceaccount.com" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
    weather_retry gcloud iam service-accounts create "$WEATHER_SA" --project="$WEATHER_PROJECT"
  fi
done
weather_retry gcloud projects add-iam-policy-binding "$WEATHER_PROJECT" --member="serviceAccount:$WEATHER_BUILD_SA" --role=roles/cloudbuild.builds.builder --condition=None --quiet >/dev/null
if ! gcloud storage buckets describe "$WEATHER_BUCKET" >/dev/null 2>&1; then
  weather_retry gcloud storage buckets create "$WEATHER_BUCKET" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets update "$WEATHER_BUCKET" --lifecycle-file="$WEATHER_WORK/source/data-lifecycle.json" --clear-soft-delete --no-versioning --public-access-prevention
weather_retry gcloud storage buckets add-iam-policy-binding "$WEATHER_BUCKET" --member="serviceAccount:$WEATHER_COLLECTOR_SA" --role=roles/storage.objectAdmin >/dev/null
weather_retry gcloud storage buckets add-iam-policy-binding "$WEATHER_BUCKET" --member="serviceAccount:$WEATHER_WEB_SA" --role=roles/storage.objectViewer >/dev/null

echo "Step 4/7: building the latest saved website source."
if [[ -f "$WEATHER_WORK/image-built" ]] && gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  echo "Using the migration image already built in this project."
else
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --tag="$WEATHER_IMAGE" --region="$WEATHER_REGION" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/$WEATHER_BUILD_SA" --default-buckets-behavior=regional-user-owned-bucket
  touch "$WEATHER_WORK/image-built"
fi

echo "Step 5/7: deploying J-Weather’s collector and website."
weather_retry gcloud run deploy weather-collector --project="$WEATHER_PROJECT" --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --no-allow-unauthenticated --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=4 --timeout=300 --command=gunicorn --args=--bind,0.0.0.0:8080,--workers,1,--threads,4,--timeout,300,collector:app --quiet
weather_retry gcloud run services add-iam-policy-binding weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --member="serviceAccount:$WEATHER_SCHEDULER_SA" --role=roles/run.invoker >/dev/null
weather_retry gcloud run deploy weather-lab --project="$WEATHER_PROJECT" --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --allow-unauthenticated --service-account="$WEATHER_WEB_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90 --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
printf 'Website: %s\n' "$WEATHER_WEB_URL"
printf '%s\n' "$WEATHER_WEB_URL" >"$WEATHER_WORK/website-url.txt"

echo "Step 6/7: importing twelve METAR hours and recovering two-hour image loops."
WEATHER_PAUSED_JOBS=()
weather_cleanup() {
  local weather_exit="$?"
  for weather_job in "${WEATHER_PAUSED_JOBS[@]}"; do
    gcloud scheduler jobs resume "$weather_job" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" || true
  done
  if [[ "$weather_exit" != "0" ]]; then echo "J-Weather setup stopped. Rerun the same launcher to resume project $WEATHER_PROJECT. Diagnostics: $WEATHER_WORK" >&2; fi
}
trap weather_cleanup EXIT
# On a resumed launch, pause existing schedules while the recovery job writes.
for WEATHER_JOB in weather-live-radar weather-live-satellite weather-live-forecast weather-live-metar-clouds; do
  if WEATHER_JOB_STATE="$(gcloud scheduler jobs describe "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)' 2>"$WEATHER_WORK/job-lookup.err")"; then
    if [[ "$WEATHER_JOB_STATE" == "ENABLED" ]]; then
      gcloud scheduler jobs pause "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
      WEATHER_PAUSED_JOBS+=("$WEATHER_JOB")
    fi
  elif ! grep -q 'NOT_FOUND' "$WEATHER_WORK/job-lookup.err"; then
    cat "$WEATHER_WORK/job-lookup.err" >&2
    exit 1
  fi
done
WEATHER_BOOTSTRAP='import metar_history; import refresh_media; import collector; metar_history.main(); refresh_media.main(); print(collector.collect_metar_clouds(collector.get_store(),collector.weather.utcnow()))'
if ! gcloud run jobs deploy weather-initial-data --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --command=python --args="^|^-c|$WEATHER_BOOTSTRAP" --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=1800s --execute-now --wait --quiet; then
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="weather-initial-data"' --project="$WEATHER_PROJECT" --freshness=45m --limit=35 --format='value(textPayload,jsonPayload.message)'
  exit 1
fi

echo "Step 7/7: enabling authenticated background schedules and checking the data."
weather_schedule() {
  local weather_name="$1" weather_cron="$2" weather_endpoint="$3" weather_action=create
  if gcloud scheduler jobs describe "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" >/dev/null 2>"$WEATHER_WORK/job-lookup.err"; then
    weather_action=update
  elif ! grep -q 'NOT_FOUND' "$WEATHER_WORK/job-lookup.err"; then
    cat "$WEATHER_WORK/job-lookup.err" >&2
    return 1
  fi
  weather_retry gcloud scheduler jobs "$weather_action" http "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule="$weather_cron" --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/$weather_endpoint" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER_SA" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
  if [[ "$(gcloud scheduler jobs describe "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  fi
}
weather_schedule weather-live-radar '* * * * *' radar-KMPX
weather_schedule weather-live-satellite '*/5 * * * *' satellite
weather_schedule weather-live-forecast '0,30 * * * *' forecast
weather_schedule weather-live-metar-clouds '2 * * * *' metar-clouds
WEATHER_PAUSED_JOBS=()
for WEATHER_JOB in weather-live-radar weather-live-satellite weather-live-metar-clouds; do
  gcloud scheduler jobs run "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done
python3 - "$WEATHER_WEB_URL" <<'CHECK'
import json,sys,urllib.request
from datetime import datetime,timezone,timedelta
base=sys.argv[1]
def read(path):
    with urllib.request.urlopen(base+path,timeout=90) as response:
        return json.load(response)
metars=read('/api/metar-clouds')
if len(metars.get('history',[]))!=12 or any(not h.get('stations') for h in metars['history']):
    raise SystemExit('The site is deployed, but the twelve-hour METAR history is incomplete.')
print('METAR: twelve populated hourly snapshots with cloud-circle station models.')
for path in ['/api/radar?site=KMPX','/api/satellite/truecolor','/api/satellite/dcphase','/api/satellite/ntmicro']:
    data=read(path)
    times=sorted(datetime.fromisoformat(f['time'].replace('Z','+00:00')) for f in data['frames'])
    if not times: raise SystemExit(path+': no prepared images')
    now=datetime.now(timezone.utc)
    print(f'{path}: {len(times)} frames, {times[0].isoformat()} to {times[-1].isoformat()}',flush=True)
    if times[-1]<now-timedelta(minutes=20): raise SystemExit(path+': latest imagery is not yet current')
    if times[0]>now-timedelta(minutes=105): raise SystemExit(path+': earlier two-hour history is incomplete')
    if any(b-a>timedelta(minutes=20) for a,b in zip(times,times[1:])): raise SystemExit(path+': an image gap exceeds 20 minutes')
forecast=read('/api/forecast')
if not forecast.get('periods'): raise SystemExit('Forecast periods are unavailable')
print('Forecast: prepared NWS periods are available.')
CHECK
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name.basename():label=JOB,state,schedule,status.code:label=LAST_STATUS)'
printf '\nJ-WEATHER\nProject: %s\nWebsite: %s\nSource: %s\nResume folder: %s\n' "$WEATHER_PROJECT" "$WEATHER_WEB_URL" "$WEATHER_SOURCE_COMMIT" "$WEATHER_WORK"
echo "Initial data verified. Scheduled run submission alone does not confirm automatic execution; check data timestamps after the next scheduled run."
echo "The old project's billing was left unchanged. Once J-Weather is working, the old project can be disconnected from billing."
