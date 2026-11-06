#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="nws-$(git rev-parse --short=12 HEAD)"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT

run_flags=(--project="$project" --region="$region")
scheduler_flags=(--project="$project" --location="$region")
keep_jobs=(weather-live-radar weather-live-satellite weather-live-forecast weather-live-metar-clouds weather-live-air-quality)

[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }
state="$(gcloud projects describe "$project" --format='value(lifecycleState)')"
if [[ "$state" == DELETE_REQUESTED ]]; then gcloud projects undelete "$project"; fi
[[ "$(gcloud projects describe "$project" --format='value(lifecycleState)')" == ACTIVE ]]
billing="$(gcloud billing projects describe "$project" --format='value(billingEnabled)')"
[[ "${billing,,}" == true ]] || { echo "Link $project to your enabled billing account at https://console.cloud.google.com/billing/projects, then rerun." >&2; exit 1; }
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"

gcloud scheduler jobs list "${scheduler_flags[@]}" --format=json >"$work/schedules.json"
python3 - "$work/schedules.json" "${keep_jobs[@]}" <<'PY'
import json, sys
jobs = {job["name"].rsplit("/", 1)[-1]: job["state"] for job in json.load(open(sys.argv[1]))}
missing = set(sys.argv[2:]) - jobs.keys()
if missing:
    raise SystemExit("Missing Weather Lab schedules: " + ", ".join(sorted(missing)))
if any(jobs[name] not in {"PAUSED", "ENABLED"} for name in sys.argv[2:]):
    raise SystemExit("An expected Weather Lab schedule is disabled outside this release.")
PY
gcloud run services describe weather-collector "${run_flags[@]}" --format='value(status.url)' >/dev/null
base="$(gcloud run services describe weather-lab "${run_flags[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected image repository.' >&2; exit 1 ;;
esac
image="$base:$tag"

echo 'Building the official NWS forecast release...'
gcloud builds submit . --project="$project" --region="$region" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

echo 'Preparing a candidate web revision...'
gcloud run services update weather-lab "${run_flags[@]}" --image="$image" --no-traffic --tag="$tag"
gcloud run services describe weather-lab "${run_flags[@]}" --format=json >"$work/service.json"
read -r revision candidate < <(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); t=next(t for t in s["status"]["traffic"] if t.get("tag")==sys.argv[2]); print(t["revisionName"],t["url"])' "$work/service.json" "$tag")

check_forecast() {
  curl -fsS --retry 2 --retry-all-errors --max-time 15 "$1/api/forecast" -o "$work/forecast.json"
  python3 - "$work/forecast.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("forecastVersion") == "nws-mapclick-v1" and d.get("location") == "Hopkins, MN"
assert d.get("periods") and all(p.get("detailedForecast") for p in d["periods"])
assert any(isinstance(p.get("temperature"), (int, float)) for p in d["periods"])
PY
}

check_layout() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" -o "$work/index.html"
  grep -Fq 'app.js?v=nws-temperature-v1' "$work/index.html"
  grep -Fq 'style.css?v=nws-temperature-v1' "$work/index.html"
  if grep -Fq 'id="tab-models"' "$work/index.html"; then
    echo 'Models tab unexpectedly present.' >&2; return 1
  fi
}

check_layout "$candidate"
check_forecast "$candidate"
python3 verify_lowest_radar_site.py "$candidate"

echo 'Switching the collector to official NWS and pausing the model schedule...'
nbm_state="$(python3 -c 'import json,sys; print(next((j["state"] for j in json.load(open(sys.argv[1])) if j["name"].endswith("/weather-live-nbm")), ""))' "$work/schedules.json")"
if [[ "$nbm_state" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-nbm "${scheduler_flags[@]}"
fi
gcloud run services update weather-collector "${run_flags[@]}" --image="$image"
gcloud run services update-traffic weather-collector "${run_flags[@]}" --to-latest
for job in "${keep_jobs[@]}"; do
  if [[ "$(gcloud scheduler jobs describe "$job" "${scheduler_flags[@]}" --format='value(state)')" == PAUSED ]]; then
    gcloud scheduler jobs resume "$job" "${scheduler_flags[@]}"
  fi
done
gcloud scheduler jobs run weather-live-forecast "${scheduler_flags[@]}"

echo 'Sending public traffic to the verified website...'
gcloud run services update-traffic weather-lab "${run_flags[@]}" --to-revisions="$revision=100"
check_layout "$site"
check_forecast "$site"
echo "Weather Lab update live: $site"
