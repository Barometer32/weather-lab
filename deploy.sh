#!/usr/bin/env bash
# Run in your authenticated Google Cloud Shell: bash deploy.sh PROJECT_ID
set -euo pipefail
WEATHER_PROJECT="${1:?Pass your Google Cloud project ID}"
WEATHER_REGION="us-central1"
# Build in Google Cloud by default; local Docker remains an explicit option.
WEATHER_BUILD_MODE="${WEATHER_BUILD_MODE:-cloudbuild}"
case "$WEATHER_BUILD_MODE" in
  cloudbuild) ;;
  docker)
    command -v docker >/dev/null || { echo 'Docker is required for WEATHER_BUILD_MODE=docker.' >&2; exit 1; }
    docker info >/dev/null
    ;;
  *) echo 'WEATHER_BUILD_MODE must be cloudbuild or docker.' >&2; exit 1 ;;
esac
# A recovered Artifact Registry repository may reject pushes after project deletion.
# Use a fresh repository; callers can select another unused name after a restore.
WEATHER_ARTIFACT_REPOSITORY="${WEATHER_ARTIFACT_REPOSITORY:-weather-lab-images}"
WEATHER_IMAGE="${WEATHER_REGION}-docker.pkg.dev/${WEATHER_PROJECT}/${WEATHER_ARTIFACT_REPOSITORY}/app:latest"
WEATHER_WEB_SA="weather-web@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_BUILD_SA="weather-builder@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_COLLECTOR_SA="weather-collector@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_SCHEDULER_SA="weather-scheduler@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_DATA_BUCKET="${WEATHER_PROJECT}-weather-data"

# Stop before builds or resource changes if project restoration/billing is incomplete.
WEATHER_PROJECT_STATE="$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')"
if [[ "$WEATHER_PROJECT_STATE" != "ACTIVE" ]]; then
  printf 'Project %s is %s. Restore it before deploying.\n' "$WEATHER_PROJECT" "$WEATHER_PROJECT_STATE" >&2
  exit 1
fi
WEATHER_BILLING_ENABLED="$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)')"
if [[ "${WEATHER_BILLING_ENABLED,,}" != "true" ]]; then
  printf 'Billing is not enabled for %s. Link an active billing account before deploying.\n' "$WEATHER_PROJECT" >&2
  exit 1
fi

gcloud config set project "$WEATHER_PROJECT"
WEATHER_REQUIRED_APIS=(run.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com)
if [[ "$WEATHER_BUILD_MODE" == cloudbuild ]]; then
  WEATHER_REQUIRED_APIS+=(cloudbuild.googleapis.com)
fi
weather_retry() {
  local weather_attempt
  for weather_attempt in 1 2 3 4 5 6; do
    if "$@"; then return 0; fi
    if [[ "$weather_attempt" == 6 ]]; then return 1; fi
    printf 'New-project permissions may still be propagating; retry %s/6.\n' "$weather_attempt" >&2
    sleep "$((weather_attempt*5))"
  done
}
weather_retry gcloud services enable "${WEATHER_REQUIRED_APIS[@]}" iam.googleapis.com --project="$WEATHER_PROJECT"
# Create this NEW project's own managed identities; no deleted-project IDs.
WEATHER_IDENTITY_SERVICES=(artifactregistry.googleapis.com run.googleapis.com cloudscheduler.googleapis.com)
if [[ "$WEATHER_BUILD_MODE" == cloudbuild ]]; then
  WEATHER_IDENTITY_SERVICES+=(cloudbuild.googleapis.com)
fi
for WEATHER_SERVICE in "${WEATHER_IDENTITY_SERVICES[@]}"; do
  weather_retry gcloud beta services identity create --service="$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --quiet
done

if ! gcloud artifacts repositories describe "$WEATHER_ARTIFACT_REPOSITORY" --location="$WEATHER_REGION" >/dev/null 2>&1; then
  weather_retry gcloud artifacts repositories create "$WEATHER_ARTIFACT_REPOSITORY" --repository-format=docker --location="$WEATHER_REGION"
fi
for WEATHER_SA_NAME in weather-web weather-builder weather-collector weather-scheduler; do
  if [[ "$WEATHER_SA_NAME" == weather-builder && "$WEATHER_BUILD_MODE" == docker ]]; then
    continue
  fi
  if ! gcloud iam service-accounts describe "${WEATHER_SA_NAME}@${WEATHER_PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    weather_retry gcloud iam service-accounts create "$WEATHER_SA_NAME"
  fi
done
if [[ "$WEATHER_BUILD_MODE" == cloudbuild ]]; then
  weather_retry gcloud projects add-iam-policy-binding "$WEATHER_PROJECT" --member="serviceAccount:${WEATHER_BUILD_SA}" --role=roles/cloudbuild.builds.builder --condition=None
fi

if ! gcloud storage buckets describe "gs://${WEATHER_DATA_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${WEATHER_DATA_BUCKET}" --location="$WEATHER_REGION" --uniform-bucket-level-access
fi
# This dedicated bucket contains replaceable prepared data, not user documents.
gcloud storage buckets update "gs://${WEATHER_DATA_BUCKET}" --lifecycle-file=data-lifecycle.json --clear-soft-delete --no-versioning --public-access-prevention
weather_retry gcloud storage buckets add-iam-policy-binding "gs://${WEATHER_DATA_BUCKET}" --member="serviceAccount:${WEATHER_COLLECTOR_SA}" --role=roles/storage.objectAdmin
weather_retry gcloud storage buckets add-iam-policy-binding "gs://${WEATHER_DATA_BUCKET}" --member="serviceAccount:${WEATHER_WEB_SA}" --role=roles/storage.objectViewer

if [[ "$WEATHER_BUILD_MODE" == docker ]]; then
  gcloud auth configure-docker "${WEATHER_REGION}-docker.pkg.dev" --quiet
  docker build --platform=linux/amd64 --tag "$WEATHER_IMAGE" .
  WEATHER_PUSH_OK=false
  for WEATHER_PUSH_ATTEMPT in 1 2 3; do
    if docker push "$WEATHER_IMAGE"; then
      WEATHER_PUSH_OK=true
      break
    fi
    if [[ "$WEATHER_PUSH_ATTEMPT" != 3 ]]; then
      printf 'Upload failed; retrying the same built image (%s/3).\n' "$WEATHER_PUSH_ATTEMPT" >&2
      sleep 5
    fi
  done
  if [[ "$WEATHER_PUSH_OK" != true ]]; then
    printf 'Image upload failed. Existing services were not replaced. Rerun this command to retry.\n' >&2
    exit 1
  fi
else
  gcloud builds submit --tag "$WEATHER_IMAGE" --region="$WEATHER_REGION" --service-account="projects/${WEATHER_PROJECT}/serviceAccounts/${WEATHER_BUILD_SA}" --default-buckets-behavior=regional-user-owned-bucket .
fi
weather_retry gcloud run deploy weather-collector --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --no-allow-unauthenticated --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=${WEATHER_DATA_BUCKET}" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=4 --timeout=300 --command=gunicorn --args=--bind,0.0.0.0:8080,--workers,1,--threads,4,--timeout,300,collector:app
weather_retry gcloud run services add-iam-policy-binding weather-collector --region="$WEATHER_REGION" --member="serviceAccount:${WEATHER_SCHEDULER_SA}" --role=roles/run.invoker
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --region="$WEATHER_REGION" --format='value(status.url)')"

weather_schedule() {
  local weather_kind="$1" weather_cron="$2" weather_endpoint="${3:-$1}" weather_deadline="${4:-300}" weather_retries="${5:-2}" weather_action=create
  if gcloud scheduler jobs describe "weather-live-${weather_kind}" --location="$WEATHER_REGION" >/dev/null 2>&1; then
    weather_action=update
  fi
  gcloud scheduler jobs "$weather_action" http "weather-live-${weather_kind}" --location="$WEATHER_REGION" --schedule="$weather_cron" --time-zone=Etc/UTC --uri="${WEATHER_COLLECTOR_URL}/collect/${weather_endpoint}" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER_SA" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline="${weather_deadline}s" --max-retry-attempts="$weather_retries" --min-backoff=60s --max-backoff=120s
  if [[ "$weather_kind" == stations && "${WEATHER_INITIAL_BACKFILL:-false}" == true ]]; then
    gcloud scheduler jobs pause "weather-live-${weather_kind}" --location="$WEATHER_REGION"
  else
    if [[ "$(gcloud scheduler jobs describe "weather-live-${weather_kind}" --location="$WEATHER_REGION" --format='value(state)')" == PAUSED ]]; then
      gcloud scheduler jobs resume "weather-live-${weather_kind}" --location="$WEATHER_REGION"
    fi
    gcloud scheduler jobs run "weather-live-${weather_kind}" --location="$WEATHER_REGION"
  fi
}
weather_schedule radar '* * * * *' radar-KMPX
weather_schedule satellite '*/5 * * * *'
weather_schedule forecast '*/5 * * * *'
weather_schedule stations '5 * * * *' stations 300 0

weather_retry gcloud run deploy weather-lab --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --allow-unauthenticated --service-account="$WEATHER_WEB_SA" --set-env-vars="WEATHER_DATA_BUCKET=${WEATHER_DATA_BUCKET}" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90

printf '%s\n' 'Radar and satellite history are preparing in the background. The setup script imports twelve METAR hours.'
gcloud run services describe weather-lab --region="$WEATHER_REGION" --format='value(status.url)'
