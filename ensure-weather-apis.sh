#!/usr/bin/env bash
# Read before mutating, with explicit quota attribution to this project.
set -euo pipefail
WEATHER_API_PROJECT="${1:?Pass the target project ID}"
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_API_PROJECT"
WEATHER_API_REQUIRED=(run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com iam.googleapis.com)
WEATHER_API_ERROR="$(mktemp)"
trap 'rm -f "$WEATHER_API_ERROR"' EXIT
for WEATHER_API_ATTEMPT in 1 2 3 4; do
  # A failed read is never interpreted as a list of missing APIs.
  WEATHER_API_ENABLED="$(gcloud services list --enabled --project="$WEATHER_API_PROJECT" --billing-project="$WEATHER_API_PROJECT" --format='value(config.name)')"
  WEATHER_API_MISSING=()
  for WEATHER_API in "${WEATHER_API_REQUIRED[@]}"; do
    if [[ $'\n'"$WEATHER_API_ENABLED"$'\n' != *$'\n'"$WEATHER_API"$'\n'* ]]; then
      WEATHER_API_MISSING+=("$WEATHER_API")
    fi
  done
  if [[ "${#WEATHER_API_MISSING[@]}" == 0 ]]; then
    echo 'Required APIs are already enabled; no API-enablement request needed.'
    exit 0
  fi
  echo "Enabling only missing APIs: ${WEATHER_API_MISSING[*]}"
  if gcloud services enable "${WEATHER_API_MISSING[@]}" --project="$WEATHER_API_PROJECT" --billing-project="$WEATHER_API_PROJECT" >"$WEATHER_API_ERROR" 2>&1; then
    cat "$WEATHER_API_ERROR"
    exit 0
  fi
  cat "$WEATHER_API_ERROR" >&2
  if ! grep -Eq '429|RATE_LIMIT_EXCEEDED|Mutate requests' "$WEATHER_API_ERROR"; then
    exit 1
  fi
  if [[ "$WEATHER_API_ATTEMPT" == 4 ]]; then
    echo 'API-enablement quota is still exhausted. No build or deployment was started.' >&2
    exit 1
  fi
  WEATHER_API_DELAY=$((WEATHER_API_ATTEMPT*20))
  echo "Google API setup rate-limited; rechecking enabled APIs in $WEATHER_API_DELAY seconds ($WEATHER_API_ATTEMPT/4)." >&2
  sleep "$WEATHER_API_DELAY"
done
