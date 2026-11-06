#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="airq-source-$(git rev-parse --short=12 HEAD)"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
flags=(--project="$project" --region="$region")
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"

gcloud run services describe weather-lab "${flags[@]}" --format=json >"$work/current.json"
base="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(s["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])' "$work/current.json")"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected Weather Lab image repository.' >&2; exit 1 ;;
esac
image="$base:$tag"
echo 'Building the AirNow source fallback...'
gcloud builds submit . "${flags[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

gcloud run services update weather-lab "${flags[@]}" --image="$image" --no-traffic --tag="$tag"
gcloud run services describe weather-lab "${flags[@]}" --format=json >"$work/service.json"
read -r revision candidate < <(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); t=next(t for t in s["status"]["traffic"] if t.get("tag")==sys.argv[2]); print(t["revisionName"],t["url"])' "$work/service.json" "$tag")

check_layout() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" -o "$work/index.html"
  grep -Fq 'air-quality-views.js?v=airq-source-fallback-v1' "$work/index.html"
  grep -Fq 'metar-views.js?v=metar-compact-start-v1' "$work/index.html"
}

check_layout "$candidate"
python3 verify_lowest_radar_site.py "$candidate" 4
curl -fsS --retry 2 --retry-all-errors --max-time 20 "$candidate/api/air-quality" -o "$work/air-before.json"

echo 'Updating the collector and requesting a new AirNow map check...'
gcloud run services update weather-collector "${flags[@]}" --image="$image"
gcloud run services update-traffic weather-collector "${flags[@]}" --to-latest
scheduler=(--project="$project" --location="$region")
state="$(gcloud scheduler jobs describe weather-live-air-quality "${scheduler[@]}" --format='value(state)')"
if [[ "$state" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-air-quality "${scheduler[@]}"
fi
# Wait for a check made by the new collector, rather than an earlier run.
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gcloud scheduler jobs run weather-live-air-quality "${scheduler[@]}"

check_airq() {
  curl -fsS --max-time 15 "$1/api/air-quality" -o "$work/air-after.json" &&
  python3 - "$work/air-before.json" "$work/air-after.json" "$since" <<'PY'
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo

def stamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))

with open(sys.argv[1]) as f:
    before=json.load(f)
with open(sys.argv[2]) as f:
    after=json.load(f)
latest=after['frames'][-1]['sourceTime']
if (stamp(after['checkedAt']) < stamp(sys.argv[3])
    or stamp(latest) < stamp(before['frames'][-1]['sourceTime'])
    or 'sourceDelayed' not in after):
    raise SystemExit(1)
zone=ZoneInfo('America/Chicago')
print('Newest AirNow map:', stamp(latest).astimezone(zone).strftime('%b %d, %I:%M %p %Z'))
if after['sourceDelayed']:
    print('AirNow source is delayed; the website labels the latest map accordingly.')
PY
}
for attempt in {1..12}; do
  if check_airq "$candidate"; then break; fi
  if [[ "$attempt" == 12 ]]; then
    echo 'No completed new AirNow check yet. The collector was updated; public website traffic has not changed.' >&2
    exit 1
  fi
  sleep 10
done
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_layout "$site"
for attempt in 1 2 3; do
  if check_airq "$site"; then break; fi
  if [[ "$attempt" == 3 ]]; then
    echo 'Public traffic switched, but the final public Air Q check did not complete.' >&2
    exit 1
  fi
  sleep 5
done
echo "Weather Lab Air Q update live: $site"
