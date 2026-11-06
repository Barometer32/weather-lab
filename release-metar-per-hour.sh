#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="metar-per-hour-$(git rev-parse --short=12 HEAD)"
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
echo 'Building the METAR display update...'
gcloud builds submit . "${flags[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

gcloud run services update weather-lab "${flags[@]}" --image="$image" --no-traffic --tag="$tag"
gcloud run services describe weather-lab "${flags[@]}" --format=json >"$work/service.json"
read -r revision candidate < <(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); t=next(t for t in s["status"]["traffic"] if t.get("tag")==sys.argv[2]); print(t["revisionName"],t["url"])' "$work/service.json" "$tag")

check_layout() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" -o "$work/index.html"
  grep -Fq 'metar-views.js?v=metar-per-hour-v1' "$work/index.html"
  grep -Fq 'app.js?v=nws-temperature-v1' "$work/index.html"
}

check_layout "$candidate"
python3 verify_lowest_radar_site.py "$candidate" 4
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_layout "$site"
echo "Per-hour METAR plots live: $site"
