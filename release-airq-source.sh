#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
job=weather-live-air-quality
tag="airq-direct-$(git rev-parse --short=12 HEAD)"
run=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

base="$(gcloud run services describe weather-collector "${run[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected Weather Lab collector image repository.' >&2; exit 1 ;;
esac
before="$(curl -fsS --retry 2 --max-time 20 "$site/api/air-quality" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["frames"][-1]["sourceTime"])')"
image="$base:$tag"
gcloud builds submit . "${run[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-collector "${run[@]}" --image="$image" --no-traffic --tag="$tag"
revision="$(gcloud run services describe weather-collector "${run[@]}" --format=json |
  python3 -c 'import json,sys; print(next(t["revisionName"] for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
gcloud run services update-traffic weather-collector "${run[@]}" --to-revisions="$revision=100"

if [[ "$(gcloud scheduler jobs describe "$job" "${scheduler[@]}" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume "$job" "${scheduler[@]}"
fi
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gcloud scheduler jobs run "$job" "${scheduler[@]}"
for attempt in {1..18}; do
  if result="$(curl -fsS --max-time 15 "$site/api/air-quality" |
    python3 -c '
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo
d=json.load(sys.stdin)
parse=datetime.fromisoformat
frame=d["frames"][-1]
latest=parse(frame["sourceTime"])
assert d.get("directCheckedAt") and parse(d["directCheckedAt"]) >= parse(sys.argv[2])
assert latest >= parse(sys.argv[1])
assert frame["url"].startswith("/api/prepared/air-quality/")
print(latest.astimezone(ZoneInfo("America/Chicago")).strftime("%b %d, %I:%M %p %Z"))
print(frame["url"])
' "$before" "$since" 2>/dev/null)"; then
    curl -fsS --max-time 15 -o /dev/null "$site${result##*$'\n'}"
    printf 'Direct AirNow feed verified. Newest map: %s\n' "${result%%$'\n'*}"
    exit 0
  fi
  sleep 10
done
echo 'The collector was updated, but a completed direct AirNow check has not reached the public map yet.' >&2
exit 1
