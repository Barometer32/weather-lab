#!/usr/bin/env bash
# Recreate revisions from the exact original image digests; never use :latest.
set -euo pipefail
trap 'echo "Repair stopped at line $LINENO. Send the error above to ChatGPT." >&2' ERR
WEATHER_PROJECT="weather-lab-511113"
WEATHER_REGION="us-central1"
WEATHER_BACKUP="$(mktemp -d "$HOME/weather-service-repair.XXXXXX")"
WEATHER_RESTORE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
echo "Saving service settings in $WEATHER_BACKUP"

for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_BACKUP/$WEATHER_SERVICE.yaml"
done
gcloud run revisions describe weather-collector-00025-mlv --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_BACKUP/collector-revision.json"
gcloud run revisions describe weather-lab-00035-z9r --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_BACKUP/web-revision.json"

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
WEATHER_TOKEN="$(gcloud auth print-identity-token)"
WEATHER_FAILED=0
for WEATHER_ENDPOINT in forecast metar-clouds satellite radar-KMPX; do
  echo "Testing and refreshing $WEATHER_ENDPOINT (may take a few minutes)."
  if WEATHER_HTTP="$(curl -sS --max-time 310 -o "$WEATHER_BACKUP/response-$WEATHER_ENDPOINT.txt" -w '%{http_code}' -X POST -H "Authorization: Bearer $WEATHER_TOKEN" "$WEATHER_COLLECTOR_URL/collect/$WEATHER_ENDPOINT")"; then
    printf 'HTTP %s\n' "$WEATHER_HTTP"
    cat "$WEATHER_BACKUP/response-$WEATHER_ENDPOINT.txt"
    printf '\n'
    if [[ "$WEATHER_HTTP" != "200" ]]; then
      WEATHER_FAILED=1
    fi
    if [[ "$WEATHER_HTTP" == "404" || "$WEATHER_HTTP" == "401" || "$WEATHER_HTTP" == "403" ]]; then
      echo "Stopping direct refresh tests; send this response to ChatGPT."
      break
    fi
  else
    WEATHER_FAILED=1
    echo "Request did not complete; checking saved data below."
  fi
done

echo "Prepared data timestamps:"
gcloud storage ls -l 'gs://weather-lab-511113-weather-data/live/*'
printf '\nWebsite: %s\nBackup settings: %s\n' "$WEATHER_WEB_URL" "$WEATHER_BACKUP"
if [[ "$WEATHER_FAILED" != "0" ]]; then
  echo "At least one direct refresh failed. Send the output to ChatGPT."
  exit 1
fi
echo "All four direct refreshes returned HTTP 200. Automatic Scheduler runs still need verification."
