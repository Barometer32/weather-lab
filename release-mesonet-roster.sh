#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="mesonet-roster-$(git rev-parse --short=12 HEAD)"
flags=(--project="$project" --region="$region")
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

base="$(gcloud run services describe weather-lab "${flags[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected Weather Lab image repository.' >&2; exit 1 ;;
esac
image="$base:$tag"
gcloud builds submit . "${flags[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

gcloud run services update weather-lab "${flags[@]}" --image="$image" --no-traffic --tag="$tag"
read -r revision candidate < <(gcloud run services describe weather-lab "${flags[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); t=next(t for t in s["status"]["traffic"] if t.get("tag")==sys.argv[1]); print(t["revisionName"],t["url"])' "$tag")

check_metars() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c 'import sys; s=sys.stdin.read(); sys.exit(not ("prepared-data.js?v=mesonet-roster-v1" in s and "metar-views.js?v=mesonet-primary-roads-v1" in s and "metar-model.js?v=mesonet-calm-dot-v1" in s and "style.css?v=phone-sliders-70-v1" in s and "radar-roads.js?v=primary-roads-option-v1" in s))'
  curl -fsS --compressed --retry 2 --retry-all-errors --max-time 20 "$1/api/station-plots?view=loop" |
    python3 -c '
import json, sys
from verify_weather_site import ready_metar_loop
d = json.load(sys.stdin)
frames = d["history"]
assert d["stationPolicy"] == "airport-exclude-kcfe-v1"
assert len(frames) == 4 and ready_metar_loop(d, 4), "Expected four ready METAR hours"
assert not any(s["station"] == "KCFE" for f in frames for s in f["stations"]), "KCFE is still present"
'
}

check_mesonet() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/api/observation-stations?view=mesonet" |
    python3 -c '
import json, sys
from observation_stations import COVERAGE, MAP_STATION_POLICY, included_on_map
d = json.load(sys.stdin)
assert d["coverage"] == COVERAGE and d["stationPolicy"] == MAP_STATION_POLICY, "Unexpected Mesonet roster"
assert d["stations"] and all(s["station"] != "HPN29" and included_on_map(s) for s in d["stations"]), "Incorrect Mesonet coverage"
'
}
check_metars "$candidate"
check_mesonet "$candidate"
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_metars "$site"
check_mesonet "$site"
echo "Trimmed Mesonet roster verified on $site"
