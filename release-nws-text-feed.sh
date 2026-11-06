#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="nws-text-$(git rev-parse --short=12 HEAD)"
cloud=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
job=weather-live-forecast
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"

[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }
schedule_state="$(gcloud scheduler jobs describe "$job" "${scheduler[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["state"]," ".join(d["schedule"].split()))')"
[[ "$schedule_state" == 'ENABLED 0,30 * * * *' ]] || {
  echo 'Expected the enabled forecast job at :00 and :30. No changes made.' >&2
  exit 1
}
base="$(gcloud run services describe weather-collector "${cloud[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected collector image repository. No changes made.' >&2; exit 1 ;;
esac
image="$base:$tag"
echo 'Building the NWS text feed update...'
gcloud builds submit . "${cloud[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

echo 'Updating the collector that supplies the live Forecast tab...'
gcloud run services update weather-collector "${cloud[@]}" --image="$image" --no-traffic --tag="$tag"
revision="$(gcloud run services describe weather-collector "${cloud[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); print(next(t["revisionName"] for t in s["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
gcloud run services update-traffic weather-collector "${cloud[@]}" --to-revisions="$revision=100"
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gcloud scheduler jobs run "$job" "${scheduler[@]}"

for attempt in {1..12}; do
  if curl -fsS --max-time 15 "$site/api/forecast" |
    python3 -c '
import json, sys
from datetime import datetime

def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

try:
    data = json.load(sys.stdin)
    fresh = stamp(data["checkedAt"]) >= stamp(sys.argv[1])
except (ValueError, KeyError, TypeError):
    sys.exit(1)
if not fresh or data.get("forecastFeed") != "nws-mapclick-text" or not data.get("periods"):
    sys.exit(1)
print("Live Hopkins text forecast verified. NWS issuance:", data["updatedAt"])
' "$since"; then
    exit 0
  fi
  [[ "$attempt" == 12 ]] || sleep 5
done
echo 'Collector switched, but the public site has not confirmed a fresh NWS text result yet.' >&2
exit 1
