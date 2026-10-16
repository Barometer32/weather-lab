#!/usr/bin/env bash
# Optional manual retraining. The initial trained model ships with the branch.
set -euo pipefail
WEATHER_PROJECT="${1:?Pass your existing Google Cloud project ID}"
WEATHER_REGION=us-central1
WEATHER_ARTIFACT_REPOSITORY="${WEATHER_ARTIFACT_REPOSITORY:-weather-lab-images}"
WEATHER_AI_IMAGE="${WEATHER_REGION}-docker.pkg.dev/${WEATHER_PROJECT}/${WEATHER_ARTIFACT_REPOSITORY}/ai-trainer:latest"
WEATHER_BUILD_SA="weather-builder@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_COLLECTOR_SA="weather-collector@${WEATHER_PROJECT}.iam.gserviceaccount.com"
WEATHER_DATA_BUCKET="${WEATHER_PROJECT}-weather-data"
cd "$(dirname "$0")"
python3 build_access.py "$WEATHER_PROJECT"
printf '%s\n' 'Building optional CPU trainer. The training task is limited to 30 minutes, one task, and zero retries.'
gcloud builds submit --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" \
  --config=cloudbuild-ai.yaml --substitutions="_AI_IMAGE=${WEATHER_AI_IMAGE}" \
  --service-account="projects/${WEATHER_PROJECT}/serviceAccounts/${WEATHER_BUILD_SA}" \
  --default-buckets-behavior=regional-user-owned-bucket .
gcloud run jobs deploy weather-ai-train --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" \
  --image="$WEATHER_AI_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" \
  --cpu=4 --memory=8Gi --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=1800s \
  --set-env-vars="WEATHER_DATA_BUCKET=${WEATHER_DATA_BUCKET},OMP_NUM_THREADS=2,OPENBLAS_NUM_THREADS=2,MKL_NUM_THREADS=2"
printf '%s\n' 'Open AI Forecast to follow saved progress. Building the container is separate from training progress.'
gcloud run jobs execute weather-ai-train --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait
gcloud scheduler jobs run weather-live-stations --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
printf '%s\n' 'Training finished. Hourly collection is preparing maps with the newly saved model.'
