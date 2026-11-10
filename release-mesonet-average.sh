#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="mesonet-average-$(git rev-parse --short=12 HEAD)"
run=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
job=weather-live-observation-stations
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

base="$(gcloud run services describe weather-lab "${run[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected Weather Lab image repository.' >&2; exit 1 ;;
esac
collector="$(gcloud run services describe weather-collector "${run[@]}" --format='value(status.url)')"
[[ "$collector" == https://*.run.app ]]
image="$base:$tag"
gcloud builds submit . "${run[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

gcloud run services update weather-lab "${run[@]}" --image="$image" --no-traffic --tag="$tag"
read -r revision candidate < <(gcloud run services describe weather-lab "${run[@]}" --format=json |
  python3 -c 'import json,sys; t=next(t for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]); print(t["revisionName"],t["url"])' "$tag")

check_layout() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c '
import re, sys
s=sys.stdin.read()
assert re.findall(r"<button role=\"tab\" id=\"tab-([^\"]+)\"",s)==["observations","metar","radar","satellite","forecast","air-quality"]
assert "id=\"tab-observations\" aria-selected=\"true\"" in s and "HENNEPIN WEST MESONET" in s
assert "rolling-observation-views.js?v=mesonet-average-v1" in s
assert "<option value=\"clouds\" selected>" in s and "id=\"observations-sun\"" in s
'
}

check_data() {
  curl -fsS --max-time 15 "$1/api/observations/mesonet" |
    python3 -c '
import json,sys
from datetime import datetime
from observation_stations import MAP_STATION_POLICY, RETAINED_STATIONS
d=json.load(sys.stdin)
assert d["stationPolicy"] == MAP_STATION_POLICY and d["stationCount"] == len(RETAINED_STATIONS)
assert d["checkedAt"] and datetime.fromisoformat(d["checkedAt"]).timestamp() >= int(sys.argv[1])
r=d["current"]
assert r and r["stationIds"] and set(r["stationIds"]) <= RETAINED_STATIONS
assert r["tempF"] is not None and r["dewpointF"] is not None and r["wind"]["speedMph"] is not None
count=len(r["stationIds"])
print(f"Verified Mesonet averages from {count} of {len(RETAINED_STATIONS)} retained stations.")
' "$since"
}

check_layout "$candidate"
gcloud run services update weather-collector "${run[@]}" --image="$image" --no-traffic --tag="$tag"
collector_revision="$(gcloud run services describe weather-collector "${run[@]}" --format=json |
  python3 -c 'import json,sys; print(next(t["revisionName"] for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
gcloud run services update-traffic weather-collector "${run[@]}" --to-revisions="$collector_revision=100"

jobs="$(gcloud scheduler jobs list "${scheduler[@]}" --format='value(name)')"
action=create
if grep -Eq "(^|/)$job$" <<< "$jobs"; then action=update; fi
gcloud scheduler jobs "$action" http "$job" "${scheduler[@]}" --schedule='*/5 * * * *' --time-zone=Etc/UTC \
  --uri="$collector/collect/observation-stations" --http-method=POST \
  --oidc-service-account-email="weather-scheduler@$project.iam.gserviceaccount.com" \
  --oidc-token-audience="$collector" --attempt-deadline=240s --max-retry-attempts=0
if [[ "$(gcloud scheduler jobs describe "$job" "${scheduler[@]}" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume "$job" "${scheduler[@]}"
fi
since="$(date +%s)"
gcloud scheduler jobs run "$job" "${scheduler[@]}"
for attempt in {1..24}; do
  if check_data "$candidate" 2>/dev/null; then break; fi
  if [[ "$attempt" == 24 ]]; then
    echo 'No fresh Mesonet averages from the collector. Website traffic was not switched.' >&2
    exit 1
  fi
  sleep 5
done
gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$revision=100"
check_layout "$site"
check_data "$site"
echo "The five-minute Hennepin West Mesonet Observations are live at $site"
