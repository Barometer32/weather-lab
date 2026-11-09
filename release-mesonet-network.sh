#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="mesonet-network-$(git rev-parse --short=12 HEAD)"
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
  python3 -c 'import json,sys; s=json.load(sys.stdin); t=next(t for t in s["status"]["traffic"] if t.get("tag")==sys.argv[1]); print(t["revisionName"],t["url"])' "$tag")

check_layout() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c 'import sys; h=sys.stdin.read(); assert all(s in h for s in ("metar-views.js?v=mesonet-network-v1", "<option value=\"mesonet\" selected>", "<option value=\"plots\">", "<option value=\"clouds\">", "id=\"sun-angle\""))'
  curl -fsS --compressed --retry 2 --retry-all-errors --max-time 20 "$1/api/station-plots?view=loop" |
    python3 -c 'import json,sys; from verify_weather_site import ready_metar_loop; d=json.load(sys.stdin); assert len(d["history"])==4 and ready_metar_loop(d,4) and d["stationPolicy"]=="airport-exclude-kcfe-v1"'
}

check_layout "$candidate"
gcloud scheduler jobs describe "$job" "${scheduler[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["state"]=="ENABLED" and d["schedule"]=="*/5 * * * *" and d["httpTarget"]["uri"]==sys.argv[1], "The existing five-minute Mesonet job is not active on the expected collector"' "$collector/collect/observation-stations"
gcloud run services update weather-collector "${run[@]}" --image="$image" --no-traffic --tag="$tag"
collector_revision="$(gcloud run services describe weather-collector "${run[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(t["revisionName"] for t in d["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
gcloud run services update-traffic weather-collector "${run[@]}" --to-revisions="$collector_revision=100"
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gcloud scheduler jobs run "$job" "${scheduler[@]}"

check_mesonet() {
  curl -fsS --max-time 15 "$1/api/observation-stations?view=mesonet" |
    python3 -c '
import json, re, sys
from datetime import datetime
from observation_stations import COVERAGE, in_county
data=json.load(sys.stdin)
rows=data.get("stations",[])
checked=data.get("checkedAt")
def stamp(s): return datetime.fromisoformat(s.replace("Z","+00:00"))
if not (data.get("coverage")==COVERAGE and checked and stamp(checked)>=stamp(sys.argv[1]) and rows):
    sys.exit(1)
assert all(re.fullmatch(r"HPN[0-9]+",r["station"]) and r["station"]!="HPN29" and not in_county(r["lat"],r["lon"],"dakota") for r in rows)
print(f"Verified {len(rows)} recent Hennepin West readings outside Dakota County.")
' "$since"
}

for attempt in {1..24}; do
  if check_mesonet "$candidate"; then break; fi
  if [[ "$attempt" == 24 ]]; then
    echo "No recent Mesonet data after the collection check. The live site has not switched." >&2
    exit 1
  fi
  sleep 5
done
gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$revision=100"
check_layout "$site"
check_mesonet "$site"
echo "Hennepin West MESONET is live and scheduled to check every five minutes: $site"
