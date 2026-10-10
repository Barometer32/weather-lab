#!/usr/bin/env bash
# Run in your authenticated Google Cloud Shell: bash deploy.sh PROJECT_ID
set -euo pipefail
WEATHER_PROJECT="${1:?Pass your Google Cloud project ID}"
WEATHER_REGION="us-central1"
WEATHER_IMAGE="${WEATHER_REGION}-docker.pkg.dev/${WEATHER_PROJECT}/weather-lab/app:latest"
WEATHER_WEB_SA="weather-web@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_BUILD_SA="weather-builder@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_COLLECTOR_SA="weather-collector@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_SCHEDULER_SA="weather-scheduler@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_DATA_BUCKET="${WEATHER_PROJECT}-weather-data"

gcloud config set project "$WEATHER_PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com

# Stop the retired model collector before building. Only Weather Lab's own job
# names are touched; observations, radar and the replacement NWS forecast stay.
if gcloud scheduler jobs describe weather-hourly --location="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs delete weather-hourly --location="$WEATHER_REGION" --quiet
fi
# Remove the retired Eglin radar's background job; KMPX keeps its minute job.
if gcloud scheduler jobs describe weather-live-radar-KEVX --location="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs delete weather-live-radar-KEVX --location="$WEATHER_REGION" --quiet
fi
if gcloud run jobs describe weather-forecast --region="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud run jobs delete weather-forecast --region="$WEATHER_REGION" --quiet
fi

if ! gcloud artifacts repositories describe weather-lab --location="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create weather-lab --repository-format=docker --location="$WEATHER_REGION"
fi
for WEATHER_SA_NAME in weather-web weather-builder weather-collector weather-scheduler; do
  if ! gcloud iam service-accounts describe "${WEATHER_SA_NAME}@${WEATHER_PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$WEATHER_SA_NAME"
  fi
done
gcloud projects add-iam-policy-binding "$WEATHER_PROJECT" --member="serviceAccount:${WEATHER_BUILD_SA}" --role=roles/cloudbuild.builds.builder --condition=None

if ! gcloud storage buckets describe "gs://${WEATHER_DATA_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${WEATHER_DATA_BUCKET}" --location="$WEATHER_REGION" --uniform-bucket-level-access
fi
# This dedicated bucket contains replaceable prepared data, not user documents.
gcloud storage buckets update "gs://${WEATHER_DATA_BUCKET}" --lifecycle-file=data-lifecycle.json --clear-soft-delete --no-versioning --public-access-prevention
gcloud storage buckets add-iam-policy-binding "gs://${WEATHER_DATA_BUCKET}" --member="serviceAccount:${WEATHER_COLLECTOR_SA}" --role=roles/storage.objectAdmin
gcloud storage buckets add-iam-policy-binding "gs://${WEATHER_DATA_BUCKET}" --member="serviceAccount:${WEATHER_WEB_SA}" --role=roles/storage.objectViewer

gcloud builds submit --tag "$WEATHER_IMAGE" --region="$WEATHER_REGION" --service-account="projects/${WEATHER_PROJECT}/serviceAccounts/${WEATHER_BUILD_SA}" --default-buckets-behavior=regional-user-owned-bucket .
gcloud run deploy weather-collector --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --no-allow-unauthenticated --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=${WEATHER_DATA_BUCKET}" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=4 --timeout=300 --command=gunicorn --args=--bind,0.0.0.0:8080,--workers,1,--threads,4,--timeout,300,collector:app
gcloud run services add-iam-policy-binding weather-collector --region="$WEATHER_REGION" --member="serviceAccount:${WEATHER_SCHEDULER_SA}" --role=roles/run.invoker
for WEATHER_RETIRED_OBJECT in live/radar-KEVX.json live/radar-state-KEVX.json; do
  if gcloud storage objects describe "gs://${WEATHER_DATA_BUCKET}/${WEATHER_RETIRED_OBJECT}" >/dev/null 2>&1; then
    gcloud storage rm "gs://${WEATHER_DATA_BUCKET}/${WEATHER_RETIRED_OBJECT}"
  fi
done
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --region="$WEATHER_REGION" --format='value(status.url)')"

weather_schedule() {
  local weather_kind="$1" weather_cron="$2" weather_endpoint="${3:-$1}" weather_action=create
  if gcloud scheduler jobs describe "weather-live-${weather_kind}" --location="$WEATHER_REGION" >/dev/null 2>&1; then
    weather_action=update
  fi
  gcloud scheduler jobs "$weather_action" http "weather-live-${weather_kind}" --location="$WEATHER_REGION" --schedule="$weather_cron" --time-zone=Etc/UTC --uri="${WEATHER_COLLECTOR_URL}/collect/${weather_endpoint}" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER_SA" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=2 --min-backoff=60s --max-backoff=120s
  # Updating an existing job preserves its paused state. Restore background
  # collection when redeploying a previously stopped WEATHER LAB project.
  if [[ "$(gcloud scheduler jobs describe "weather-live-${weather_kind}" --location="$WEATHER_REGION" --format='value(state)')" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "weather-live-${weather_kind}" --location="$WEATHER_REGION"
  fi
  gcloud scheduler jobs run "weather-live-${weather_kind}" --location="$WEATHER_REGION"
}
weather_schedule radar '* * * * *' radar-KMPX
weather_schedule satellite '*/5 * * * *'
weather_schedule observations '3,56,59 * * * *'
weather_schedule forecast '*/5 * * * *'
weather_schedule metar-clouds '3,56,59 * * * *'

gcloud run deploy weather-lab --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --allow-unauthenticated --service-account="$WEATHER_WEB_SA" --set-env-vars="WEATHER_DATA_BUCKET=${WEATHER_DATA_BUCKET}" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90

# Remove only the obsolete model output, then the empty forecast bucket.
# Leave unrelated objects alone if this bucket has been used for anything else.
WEATHER_OLD_BUCKET="${WEATHER_PROJECT}-forecast"
if gcloud storage buckets describe "gs://${WEATHER_OLD_BUCKET}" >/dev/null 2>&1; then
  for WEATHER_OLD_OBJECT in forecast/latest.json; do
    if gcloud storage objects describe "gs://${WEATHER_OLD_BUCKET}/${WEATHER_OLD_OBJECT}" >/dev/null 2>&1; then
      gcloud storage rm "gs://${WEATHER_OLD_BUCKET}/${WEATHER_OLD_OBJECT}"
    fi
  done
  if ! gcloud storage buckets delete "gs://${WEATHER_OLD_BUCKET}" --quiet; then
    printf '%s\n' 'The retired forecast bucket is not empty; remaining objects were retained. No model collection jobs remain.'
  fi
fi
printf '%s\n' 'Background collection enabled. The first two-hour radar and satellite backfill can take a few minutes.'
gcloud run services describe weather-lab --region="$WEATHER_REGION" --format='value(status.url)'
