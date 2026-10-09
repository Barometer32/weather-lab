#!/usr/bin/env bash
# Run in your authenticated Google Cloud Shell: bash deploy.sh PROJECT_ID
set -euo pipefail
WEATHER_PROJECT="${1:?Pass your Google Cloud project ID}"
WEATHER_REGION="us-central1"
WEATHER_IMAGE="${WEATHER_REGION}-docker.pkg.dev/${WEATHER_PROJECT}/weather-lab/app:latest"
WEATHER_WEB_SA="weather-web@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_BUILD_SA="weather-builder@${WEATHER_PROJECT}.iam.gserviceaccount.com"

gcloud config set project "$WEATHER_PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# Stop the retired model collector before building. Only Weather Lab's own job
# names are touched; observations, radar and the replacement NWS forecast stay.
if gcloud scheduler jobs describe weather-hourly --location="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs delete weather-hourly --location="$WEATHER_REGION" --quiet
fi
if gcloud run jobs describe weather-forecast --region="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud run jobs delete weather-forecast --region="$WEATHER_REGION" --quiet
fi

if ! gcloud artifacts repositories describe weather-lab --location="$WEATHER_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create weather-lab --repository-format=docker --location="$WEATHER_REGION"
fi
for WEATHER_SA_NAME in weather-web weather-builder; do
  if ! gcloud iam service-accounts describe "${WEATHER_SA_NAME}@${WEATHER_PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$WEATHER_SA_NAME"
  fi
done
gcloud projects add-iam-policy-binding "$WEATHER_PROJECT" --member="serviceAccount:${WEATHER_BUILD_SA}" --role=roles/cloudbuild.builds.builder --condition=None

gcloud builds submit --tag "$WEATHER_IMAGE" --region="$WEATHER_REGION" --service-account="projects/${WEATHER_PROJECT}/serviceAccounts/${WEATHER_BUILD_SA}" --default-buckets-behavior=regional-user-owned-bucket .
gcloud run deploy weather-lab --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --allow-unauthenticated --service-account="$WEATHER_WEB_SA" --clear-env-vars --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90

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
gcloud run services describe weather-lab --region="$WEATHER_REGION" --format='value(status.url)'
