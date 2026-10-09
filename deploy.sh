#!/usr/bin/env bash
# Run in your authenticated Google Cloud Shell: bash deploy.sh NEW_PROJECT_ID
set -euo pipefail
WEATHER_PROJECT="${1:?Pass your new Google Cloud project ID}"
WEATHER_REGION="us-central1"
WEATHER_BUCKET="${WEATHER_PROJECT}-forecast"
WEATHER_IMAGE="${WEATHER_REGION}-docker.pkg.dev/${WEATHER_PROJECT}/weather-lab/app:latest"
WEATHER_WEB_SA="weather-web@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_JOB_SA="weather-collector@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_TRIGGER_SA="weather-scheduler@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_BUILD_SA="weather-builder@${WEATHER_PROJECT}.iam.gserviceaccount.com"

gcloud config set project "$WEATHER_PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com

if ! gcloud artifacts repositories describe weather-lab --location="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create weather-lab --repository-format=docker --location="$WEATHER_REGION"
fi
if ! gcloud storage buckets describe "gs://${WEATHER_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${WEATHER_BUCKET}" --location="$WEATHER_REGION" --uniform-bucket-level-access --public-access-prevention
fi
for WEATHER_SA_NAME in weather-web weather-collector weather-scheduler weather-builder; do
  if ! gcloud iam service-accounts describe "${WEATHER_SA_NAME}@${WEATHER_PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$WEATHER_SA_NAME"
  fi
done
gcloud projects add-iam-policy-binding "$WEATHER_PROJECT" --member="serviceAccount:${WEATHER_BUILD_SA}" --role=roles/cloudbuild.builds.builder --condition=None
gcloud storage buckets add-iam-policy-binding "gs://${WEATHER_BUCKET}" --member="serviceAccount:${WEATHER_WEB_SA}" --role=roles/storage.objectViewer
gcloud storage buckets add-iam-policy-binding "gs://${WEATHER_BUCKET}" --member="serviceAccount:${WEATHER_JOB_SA}" --role=roles/storage.objectUser

gcloud builds submit --tag "$WEATHER_IMAGE" --region="$WEATHER_REGION" --service-account="projects/${WEATHER_PROJECT}/serviceAccounts/${WEATHER_BUILD_SA}" --default-buckets-behavior=regional-user-owned-bucket .
gcloud run deploy weather-lab --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --allow-unauthenticated --service-account="$WEATHER_WEB_SA" --set-env-vars="FORECAST_BUCKET=${WEATHER_BUCKET}" --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90

if gcloud run jobs describe weather-forecast --region="$WEATHER_REGION" >/dev/null 2>&1; then
  WEATHER_JOB_ACTION=update
else
  WEATHER_JOB_ACTION=create
fi
gcloud run jobs "$WEATHER_JOB_ACTION" weather-forecast --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --service-account="$WEATHER_JOB_SA" --set-env-vars="FORECAST_BUCKET=${WEATHER_BUCKET}" --command=python --args=forecast_worker.py --cpu=2 --memory=4Gi --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=900s
gcloud run jobs add-iam-policy-binding weather-forecast --region="$WEATHER_REGION" --member="serviceAccount:${WEATHER_TRIGGER_SA}" --role=roles/run.invoker

WEATHER_URI="https://run.googleapis.com/v2/projects/${WEATHER_PROJECT}/locations/${WEATHER_REGION}/jobs/weather-forecast:run"
if gcloud scheduler jobs describe weather-hourly --location="$WEATHER_REGION" >/dev/null 2>&1; then
  WEATHER_SCHEDULE_ACTION=update
else
  WEATHER_SCHEDULE_ACTION=create
fi
# :45 targets the previous hourly model cycle. :55 is a cheap availability retry;
# the collector exits early when that same cycle has already been published.
gcloud scheduler jobs "$WEATHER_SCHEDULE_ACTION" http weather-hourly --location="$WEATHER_REGION" --schedule='45,55 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_URI" --http-method=POST --oauth-service-account-email="$WEATHER_TRIGGER_SA" --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform --message-body='{}'

if ! gcloud run jobs execute weather-forecast --region="$WEATHER_REGION" --wait; then
  printf '%s\n' 'First forecast collection did not complete. Observations/radar are deployed; check the job logs and the next scheduled attempt.'
fi
gcloud run services describe weather-lab --region="$WEATHER_REGION" --format='value(status.url)'
