#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="forecast-compact-$(git rev-parse --short=12 HEAD)"
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

check_forecast() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c 'import sys; sys.exit("style.css?v=forecast-compact-rows-v1" not in sys.stdin.read())'
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/api/forecast" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(not (d.get("location")=="Hopkins, MN" and d.get("periods")))'
}

check_forecast "$candidate"
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_forecast "$site"
echo "Compact forecast verified on $site"
