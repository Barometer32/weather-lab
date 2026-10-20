#!/usr/bin/env bash
# Recreate revisions from the exact original image digests; never use :latest.
set -euo pipefail
trap 'echo "Repair stopped at line $LINENO. Send the error above to ChatGPT." >&2' ERR
WEATHER_PROJECT="weather-lab-511113"
WEATHER_REGION="us-central1"
WEATHER_BACKUP="$(mktemp -d "$HOME/weather-service-repair.XXXXXX")"
WEATHER_RESTORE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
WEATHER_BILLING="$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)')"
if [[ "${WEATHER_BILLING,,}" != "true" ]]; then
  echo "Enable billing for weather-lab-511113 before restarting." >&2
  exit 1
fi
echo "Saving service settings in $WEATHER_BACKUP"

for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_BACKUP/$WEATHER_SERVICE.yaml"
done
WEATHER_COLLECTOR_REVISION="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.latestReadyRevisionName)')"
WEATHER_WEB_REVISION="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.latestReadyRevisionName)')"
gcloud run revisions describe "$WEATHER_COLLECTOR_REVISION" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_BACKUP/collector-revision.json"
gcloud run revisions describe "$WEATHER_WEB_REVISION" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_BACKUP/web-revision.json"

weather_pinned_image() {
  python3 - "$1" <<'PY'
import json,re,sys
with open(sys.argv[1]) as f:
    revision=json.load(f)
digest=revision.get("status",{}).get("imageDigest","")
original=revision.get("spec",{}).get("containers",[{}])[0].get("image","")
if re.fullmatch(r"sha256:[0-9a-f]{64}",digest):
    repository=original.split("@")[0]
    head,tail=repository.rsplit("/",1)
    repository=head+"/"+tail.split(":")[0]
    digest=repository+"@"+digest
if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}",digest):
    raise SystemExit("Cannot determine the exact original image digest; refusing to use a mutable tag.")
print(digest)
PY
}
WEATHER_COLLECTOR_IMAGE="$(weather_pinned_image "$WEATHER_BACKUP/collector-revision.json")"
WEATHER_WEB_IMAGE="$(weather_pinned_image "$WEATHER_BACKUP/web-revision.json")"
printf 'Original collector image: %s\nOriginal website image: %s\n' "$WEATHER_COLLECTOR_IMAGE" "$WEATHER_WEB_IMAGE"

echo "Creating a fresh collector revision with its original image."
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_COLLECTOR_IMAGE" --update-env-vars="WEATHER_RESTORE_ID=$WEATHER_RESTORE_ID" --quiet

echo "Creating a fresh website revision with its original image."
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_WEB_IMAGE" --update-env-vars="WEATHER_RESTORE_ID=$WEATHER_RESTORE_ID" --quiet

WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
echo "Checking the public website after revision restart."
WEATHER_HTTP="$(curl -sS --max-time 90 -o "$WEATHER_BACKUP/website-response.txt" -w '%{http_code}' "$WEATHER_WEB_URL/healthz")"
printf 'Website health: HTTP %s\n' "$WEATHER_HTTP"
if [[ "$WEATHER_HTTP" != "200" ]]; then
  cat "$WEATHER_BACKUP/website-response.txt"
  echo "Cloud Run is still not serving the restored project. No update jobs were triggered. Send this output to ChatGPT." >&2
  exit 1
fi
for WEATHER_JOB in weather-restored-20261019-radar weather-restored-20261019-satellite weather-restored-20261019-forecast weather-restored-20261019-metar; do
  WEATHER_JOB_STATE="$(gcloud scheduler jobs describe "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')"
  if [[ "$WEATHER_JOB_STATE" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  fi
  gcloud scheduler jobs run "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done
printf '\nWebsite: %s\nSaved settings: %s\n' "$WEATHER_WEB_URL" "$WEATHER_BACKUP"
echo "Website health returned HTTP 200. Background updates have been requested; job submission does not confirm successful data collection."
