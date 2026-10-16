#!/usr/bin/env bash
# Creates one new project, then resumes it safely on subsequent runs.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
WEATHER_STATE_FILE="${WEATHER_STATE_FILE:-$HOME/weather-lab-metar-project.txt}"
WEATHER_BILLING_ACCOUNT="${WEATHER_BILLING_ACCOUNT:-}"
command -v gcloud >/dev/null
command -v docker >/dev/null
docker info >/dev/null
if [[ -z "$WEATHER_BILLING_ACCOUNT" ]]; then
  mapfile -t WEATHER_OPEN_ACCOUNTS < <(gcloud billing accounts list --filter='open=true' --format='value(name)')
  if [[ "${#WEATHER_OPEN_ACCOUNTS[@]}" != 1 ]]; then
    echo 'Choose your active billing account below, then rerun with WEATHER_BILLING_ACCOUNT=ACCOUNT_ID bash start-fresh.sh' >&2
    gcloud billing accounts list --filter='open=true' --format='table(name,displayName,open)'
    exit 1
  fi
  WEATHER_BILLING_ACCOUNT="${WEATHER_OPEN_ACCOUNTS[0]}"
fi
WEATHER_BILLING_ACCOUNT="${WEATHER_BILLING_ACCOUNT##*/}"
WEATHER_BILLING_OPEN="$(gcloud billing accounts describe "$WEATHER_BILLING_ACCOUNT" --format='value(open)')"
[[ "${WEATHER_BILLING_OPEN,,}" == true ]] || { echo 'Reopen your billing account first.' >&2; exit 1; }
if [[ -z "${WEATHER_PROJECT:-}" ]]; then
  if [[ -s "$WEATHER_STATE_FILE" ]]; then
    WEATHER_PROJECT="$(cat "$WEATHER_STATE_FILE")"
    printf 'Resuming saved METAR project: %s\n' "$WEATHER_PROJECT"
  else
    WEATHER_PROJECT="weather-metar-$(date -u +%y%m%d-%H%M%S)"
  fi
fi
[[ "$WEATHER_PROJECT" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || { echo 'Invalid project ID.' >&2; exit 1; }
# Save the exact ID before creating anything; a rerun cannot create extra projects.
printf '%s\n' "$WEATHER_PROJECT" > "$WEATHER_STATE_FILE"
if ! gcloud projects describe "$WEATHER_PROJECT" --format='value(projectId)' >/dev/null 2>&1; then
  gcloud projects create "$WEATHER_PROJECT" --name='Weather Lab METAR Fresh'
fi
WEATHER_STATE="$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')"
[[ "$WEATHER_STATE" == ACTIVE ]] || { echo "Project is $WEATHER_STATE. Use a new WEATHER_PROJECT ID to start over." >&2; exit 1; }
gcloud billing projects link "$WEATHER_PROJECT" --billing-account="$WEATHER_BILLING_ACCOUNT"
gcloud config set project "$WEATHER_PROJECT"
printf '\nNEW WEATHER PROJECT: %s\n' "$WEATHER_PROJECT"
# METAR collection is paused during the one-time import, preventing concurrent
# writers. Always resume it, including after an import error or interruption.
weather_resume_hourly() {
  gcloud scheduler jobs resume weather-live-stations --project="$WEATHER_PROJECT" --location=us-central1 || true
  gcloud scheduler jobs run weather-live-stations --project="$WEATHER_PROJECT" --location=us-central1 || true
}
trap weather_resume_hourly EXIT
WEATHER_BUILD_MODE=docker WEATHER_INITIAL_BACKFILL=true bash deploy.sh "$WEATHER_PROJECT"
WEATHER_IMAGE="us-central1-docker.pkg.dev/${WEATHER_PROJECT}/${WEATHER_ARTIFACT_REPOSITORY:-weather-lab-images}/app:latest"
gcloud run jobs deploy weather-metar-backfill --project="$WEATHER_PROJECT" --region=us-central1 \
  --image="$WEATHER_IMAGE" --service-account="weather-collector@${WEATHER_PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars="WEATHER_DATA_BUCKET=${WEATHER_PROJECT}-weather-data" \
  --cpu=1 --memory=1Gi --tasks=1 --max-retries=0 --task-timeout=1800s \
  --command=python --args=-u,backfill_metars.py
if ! gcloud run jobs execute weather-metar-backfill --project="$WEATHER_PROJECT" --region=us-central1 --wait; then
  echo 'The site is deployed, but the 12-hour METAR import did not finish. Rerun this same script to retry.' >&2
  exit 1
fi
weather_resume_hourly
trap - EXIT
printf '\nYour Weather Lab URL:\n'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region=us-central1 --format='value(status.url)'
printf '\nProject saved in %s. Rerun this script to update or retry this project.\n' "$WEATHER_STATE_FILE"
