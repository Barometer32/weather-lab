#!/usr/bin/env bash
# Update the existing Weather Lab services without retaining rollback copies.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
run=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

# Validate existing service identity before building or changing traffic.
mapfile -t existing < <(gcloud run services describe weather-lab "${run[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["spec"]["template"]["spec"]["containers"][0]["image"]); print(d.get("metadata",{}).get("annotations",{}).get("run.googleapis.com/minScale","0"))')
[[ ${#existing[@]} == 2 ]] || { echo 'Could not read existing website settings.' >&2; exit 1; }
base="${existing[0]%%@*}"
base="${base%:*}"
case "$base" in "$region-docker.pkg.dev/$project/"*/app) ;; *) echo 'Unexpected image repository.' >&2; exit 1 ;; esac
collector_image="$(gcloud run services describe weather-collector "${run[@]}" --format='value(spec.template.spec.containers[0].image)')"
collector_base="${collector_image%%@*}"
collector_base="${collector_base%:*}"
[[ "$collector_base" == "$base" ]] || { echo 'Collector and website repositories differ.' >&2; exit 1; }
warm_min=1
if [[ "${existing[1]}" =~ ^[0-9]+$ ]] && (( existing[1] > 1 )); then warm_min="${existing[1]}"; fi
python3 -c 'from configure_live_jobs import plan; from cleanup_weather_jobs import jobs,service; plan(jobs(),service("weather-collector")); print("Verified six current job targets")'
tag="live-ready-$(git rev-parse --short=12 HEAD)"
image="$base:$tag"
gcloud builds submit . "${run[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

gcloud run services update weather-lab "${run[@]}" --image="$image" --no-traffic --tag="$tag" --update-env-vars=WEATHER_PREPARED_ONLY=true
candidate="$(gcloud run services describe weather-lab "${run[@]}" --format=json |
  python3 -c 'import json,sys; print(next(t["url"] for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
python3 verify_weather_release.py "$candidate" --layout-only
gcloud run services update weather-collector "${run[@]}" --image="$image" --no-traffic --tag="$tag"
collector_revision="$(gcloud run services describe weather-collector "${run[@]}" --format=json |
  python3 -c 'import json,sys; print(next(t["revisionName"] for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
gcloud run services update-traffic weather-collector "${run[@]}" --to-revisions="$collector_revision=100"
python3 configure_live_jobs.py
for job in weather-live-current weather-live-metar-clouds weather-live-radar weather-live-satellite weather-live-forecast weather-live-air-quality; do
  gcloud scheduler jobs run "$job" "${scheduler[@]}"
done
log="$(mktemp /tmp/weather-ready.XXXXXX)"
ready=false
for attempt in {1..36}; do
  if python3 verify_weather_release.py "$candidate" --all-products >"$log" 2>&1; then cat "$log"; ready=true; break; fi
  printf 'Waiting for prepared weather (%s/36):\n' "$attempt"
  tail -n 2 "$log"
  sleep 5
done
[[ "$ready" == true ]] || { cat "$log" >&2; echo 'Prepared data failed verification; website traffic was not switched.' >&2; exit 1; }
web_revision="$(gcloud run services describe weather-lab "${run[@]}" --format=json |
  python3 -c 'import json,sys; print(next(t["revisionName"] for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$web_revision=100"
gcloud run services update weather-lab "${run[@]}" --min="$warm_min"
python3 verify_weather_release.py "$site" --all-products
python3 cleanup_weather_jobs.py --apply --only-job weather-live-rapmetar
printf 'Weather Lab is live at %s. AVGMETAR opens first.\n' "$site"
