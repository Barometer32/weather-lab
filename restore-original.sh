#!/usr/bin/env bash
# Restore the original saved Weather Lab services; never build or deploy an image.
set -euo pipefail
trap 'echo "Restore stopped at line $LINENO. Copy the error above back to ChatGPT." >&2' ERR

WEATHER_PROJECT="weather-lab-511113"
WEATHER_REGION="us-central1"
WEATHER_BUCKET="gs://weather-lab-511113-weather-data"
WEATHER_SCHEDULER="weather-scheduler@weather-lab-511113.iam.gserviceaccount.com"

echo "Restoring update jobs for $WEATHER_PROJECT"
WEATHER_BILLING="$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)')"
if [[ "$WEATHER_BILLING" != "True" && "$WEATHER_BILLING" != "true" ]]; then
  echo "Billing is not enabled for this project." >&2
  exit 1
fi

WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_COLLECTOR_SA="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.serviceAccountName)')"
WEATHER_WEB_SA="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.serviceAccountName)')"
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
if [[ -z "$WEATHER_COLLECTOR_URL" || -z "$WEATHER_COLLECTOR_SA" || -z "$WEATHER_WEB_SA" || -z "$WEATHER_WEB_URL" ]]; then
  echo "A saved service URL or runtime service account is missing. No jobs changed." >&2
  exit 1
fi

gcloud services enable cloudscheduler.googleapis.com storage.googleapis.com --project="$WEATHER_PROJECT"

if ! gcloud storage buckets describe "$WEATHER_BUCKET" >/dev/null 2>&1; then
  echo "Creating the missing prepared-weather data bucket."
  gcloud storage buckets create "$WEATHER_BUCKET" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets add-iam-policy-binding "$WEATHER_BUCKET" --member="serviceAccount:$WEATHER_COLLECTOR_SA" --role=roles/storage.objectAdmin >/dev/null
gcloud storage buckets add-iam-policy-binding "$WEATHER_BUCKET" --member="serviceAccount:$WEATHER_WEB_SA" --role=roles/storage.objectViewer >/dev/null

WEATHER_EXISTING_SA="$(gcloud iam service-accounts list --project="$WEATHER_PROJECT" --filter="email=$WEATHER_SCHEDULER" --format='value(email)')"
if [[ -z "$WEATHER_EXISTING_SA" ]]; then
  gcloud iam service-accounts create weather-scheduler --project="$WEATHER_PROJECT"
fi
gcloud run services add-iam-policy-binding weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --member="serviceAccount:$WEATHER_SCHEDULER" --role=roles/run.invoker >/dev/null

weather_restore_job() {
  local weather_name="$1" weather_cron="$2" weather_endpoint="$3"
  local weather_action="create" weather_state
  if gcloud scheduler jobs describe "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" >/dev/null 2>&1; then
    weather_action="update"
  fi
  echo "Restoring $weather_name"
  gcloud scheduler jobs "$weather_action" http "$weather_name" \
    --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" \
    --schedule="$weather_cron" --time-zone=Etc/UTC \
    --uri="$WEATHER_COLLECTOR_URL/collect/$weather_endpoint" --http-method=POST \
    --oidc-service-account-email="$WEATHER_SCHEDULER" \
    --oidc-token-audience="$WEATHER_COLLECTOR_URL" \
    --attempt-deadline=300s --max-retry-attempts=0 --quiet >/dev/null
  weather_state="$(gcloud scheduler jobs describe "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')"
  if [[ "$weather_state" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  fi
}
weather_restore_job weather-live-radar '* * * * *' radar-KMPX
weather_restore_job weather-live-satellite '*/5 * * * *' satellite
weather_restore_job weather-live-forecast '*/5 * * * *' forecast
weather_restore_job weather-live-metar-clouds '0 * * * *' metar-clouds

for WEATHER_JOB in weather-live-radar weather-live-satellite weather-live-forecast weather-live-metar-clouds; do
  echo "Requesting initial update: $WEATHER_JOB"
  gcloud scheduler jobs run "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done

gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name.basename():label=JOB,state,schedule,status.code:label=LAST_STATUS)'
printf '\nSchedules restored and initial updates requested.\nWebsite: %s\n' "$WEATHER_WEB_URL"
echo "Job submission does not confirm successful data collection. Refresh the page and check its data timestamps."
