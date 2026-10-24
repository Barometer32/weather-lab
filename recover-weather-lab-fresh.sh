#!/usr/bin/env bash
# Recover the saved site in one fresh project, reusing that project on retries.
set -euo pipefail
WEATHER_SOURCE_PROJECT="${1:-j-weather-261020012817}"
WEATHER_SOURCE_COMMIT=f4ede1f4fad8983d6859ab3c91ea3f082a24143e
WEATHER_REGION=us-central1
WEATHER_WORK="$HOME/weather-lab-fresh-20261024"
mkdir -p "$WEATHER_WORK"
trap 'echo "Recovery stopped at line $LINENO. Rerun this same command to resume; project details are in $WEATHER_WORK." >&2' ERR

echo 'Step 1/4: checking the saved website source and existing billing account.'
if [[ ! -d "$WEATHER_WORK/source/.git" ]]; then
  git clone --quiet --no-checkout https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
if [[ "$(git -C "$WEATHER_WORK/source" rev-parse HEAD)" != "$WEATHER_SOURCE_COMMIT" ]]; then
  echo 'The recovery source folder is on another revision. Stopping to preserve it.' >&2
  exit 1
fi
test -f "$WEATHER_WORK/source/restore-j-weather-airport-metars.sh"
if [[ ! -s "$WEATHER_WORK/billing-account.txt" ]]; then
  WEATHER_BILLING="$(gcloud billing projects describe "$WEATHER_SOURCE_PROJECT" --format='value(billingAccountName)')"
  WEATHER_BILLING="${WEATHER_BILLING##*/}"
  if [[ -z "$WEATHER_BILLING" ]]; then
    echo "Link an active billing account to $WEATHER_SOURCE_PROJECT first." >&2
    exit 1
  fi
  printf '%s\n' "$WEATHER_BILLING" >"$WEATHER_WORK/billing-account.txt"
fi
WEATHER_BILLING="$(cat "$WEATHER_WORK/billing-account.txt")"
WEATHER_BILLING_OPEN="$(gcloud billing accounts describe "$WEATHER_BILLING" --format='value(open)')"
if [[ "${WEATHER_BILLING_OPEN,,}" != true ]]; then
  echo 'The saved billing account must be open before recovery.' >&2
  exit 1
fi

echo 'Step 2/4: creating or resuming the fresh Weather Lab project.'
if [[ ! -s "$WEATHER_WORK/project-id.txt" ]]; then
  printf 'weather-lab-%s\n' "$(date -u +%y%m%d-%H%M%S)" >"$WEATHER_WORK/project-id.txt"
fi
WEATHER_PROJECT="$(cat "$WEATHER_WORK/project-id.txt")"
printf 'NEW PROJECT ID: %s\n' "$WEATHER_PROJECT"
if [[ ! -f "$WEATHER_WORK/project-created" ]]; then
  if gcloud projects create "$WEATHER_PROJECT" --name='Weather Lab' 2>"$WEATHER_WORK/project-create.err"; then
    touch "$WEATHER_WORK/project-created"
  elif grep -q ALREADY_EXISTS "$WEATHER_WORK/project-create.err"; then
    gcloud projects describe "$WEATHER_PROJECT" --format='value(projectId)'
    touch "$WEATHER_WORK/project-created"
  else
    cat "$WEATHER_WORK/project-create.err" >&2
    exit 1
  fi
fi
if [[ "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" != ACTIVE ]]; then
  echo 'The recovery project is not ACTIVE. Stopping without creating another project.' >&2
  exit 1
fi
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
gcloud billing projects link "$WEATHER_PROJECT" --billing-account="$WEATHER_BILLING"
gcloud config set project "$WEATHER_PROJECT"

echo 'Step 3/4: rebuilding all six tabs, schedules and twelve METAR hours.'
# The full restore prepares fresh images and data in this project only.
if [[ ! -f "$WEATHER_WORK/site-restored" ]]; then
  WEATHER_ARTIFACT_REPOSITORY=weather-lab bash "$WEATHER_WORK/source/restore-j-weather-airport-metars.sh" "$WEATHER_PROJECT"
  touch "$WEATHER_WORK/site-restored"
fi
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
test -n "$WEATHER_WEB_URL"
printf '%s\n' "$WEATHER_WEB_URL" >"$WEATHER_WORK/website-url.txt"

echo 'Step 4/4: requesting weather-lab.cloud.run if the address is available.'
if gcloud beta run domain-mappings create --service=weather-lab --domain=weather-lab.cloud.run --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet >"$WEATHER_WORK/domain-result.txt" 2>"$WEATHER_WORK/domain-error.txt"; then
  cat "$WEATHER_WORK/domain-result.txt"
  echo 'Custom address requested: https://weather-lab.cloud.run'
  echo 'The address may need a moment to finish routing.'
else
  cat "$WEATHER_WORK/domain-error.txt" >&2
  echo 'The site was restored, but the custom address could not be newly claimed. Use the direct address below; the mapping error is saved for review.'
fi
printf '\nWeather Lab recovery complete.\nProject: %s\nDirect website: %s\nResume folder: %s\n' "$WEATHER_PROJECT" "$WEATHER_WEB_URL" "$WEATHER_WORK"
echo 'The original project and its billing were left unchanged.'
