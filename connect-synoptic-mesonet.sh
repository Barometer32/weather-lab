#!/usr/bin/env bash
# Run only with the user's own Synoptic token authorized for this public map.
set +x
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
secret=weather-hennepin-synoptic-token
trap 'unset WEATHER_SYNOPTIC_TOKEN' EXIT
read -r -s -p 'Your Synoptic API token (input hidden): ' WEATHER_SYNOPTIC_TOKEN
printf '\n'
[[ -n "$WEATHER_SYNOPTIC_TOKEN" ]] || { echo 'No token entered.' >&2; exit 1; }
export WEATHER_SYNOPTIC_TOKEN
# Verify actual fresh coverage BEFORE changing Cloud configuration.
python3 -m hennepin_synoptic
gcloud services enable secretmanager.googleapis.com --project="$project"
if ! gcloud secrets describe "$secret" --project="$project" >/dev/null 2>&1; then
  gcloud secrets create "$secret" --project="$project" --replication-policy=automatic
fi
version="$(printf '%s' "$WEATHER_SYNOPTIC_TOKEN" | gcloud secrets versions add "$secret" --project="$project" --data-file=- --format='value(name)')"
unset WEATHER_SYNOPTIC_TOKEN
version="${version##*/}"
[[ "$version" =~ ^[0-9]+$ ]] || { echo 'Could not identify stored secret version.' >&2; exit 1; }
collector_identity="$(gcloud run services describe weather-collector --project="$project" --region="$region" --format='value(spec.template.spec.serviceAccountName)')"
[[ -n "$collector_identity" ]] || { echo 'Could not identify collector service account.' >&2; exit 1; }
gcloud secrets add-iam-policy-binding "$secret" --project="$project" \
  --member="serviceAccount:$collector_identity" --role=roles/secretmanager.secretAccessor >/dev/null
gcloud run services update weather-collector --project="$project" --region="$region" \
  --update-secrets="WEATHER_SYNOPTIC_TOKEN=$secret:$version"
gcloud scheduler jobs run weather-live-hennepin-mesonet --project="$project" --location="$region"
printf 'Direct Synoptic configured. Check /api/mesonet directFeedStatus and actual station report times after collection completes.\n'
