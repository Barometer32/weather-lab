#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="airport-asos-$(git rev-parse --short=12 HEAD)"
flags=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
audit_job=weather-live-mn-asos-audit
old_job=weather-live-observation-stations
audit_object="gs://$project-weather-data/live/mn-asos-audit-v1.json"
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

base="$(gcloud run services describe weather-lab "${flags[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected Weather Lab image repository.' >&2; exit 1 ;;
esac
collector="$(gcloud run services describe weather-collector "${flags[@]}" --format='value(status.url)')"
[[ "$collector" == https://*.run.app ]]
image="$base:$tag"
gcloud builds submit . "${flags[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

gcloud run services update weather-lab "${flags[@]}" --image="$image" --no-traffic --tag="$tag"
read -r revision candidate < <(gcloud run services describe weather-lab "${flags[@]}" --format=json |
  python3 -c 'import json,sys; s=json.load(sys.stdin); t=next(t for t in s["status"]["traffic"] if t.get("tag")==sys.argv[1]); print(t["revisionName"],t["url"])' "$tag")

check_metars() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c 'import sys; s=sys.stdin.read(); sys.exit(not ("prepared-data.js?v=airport-only-v1" in s and "metar-views.js?v=airport-only-v1" in s and "metar-model.js?v=wind-mph-calm-v1" in s and "style.css?v=phone-sliders-70-v1" in s and "radar-roads.js?v=primary-roads-option-v1" in s and "PLOTS</option>" in s and "CLOUDS</option>" in s and "MESONET</option>" not in s))'
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

check_no_mesonet() {
  [[ "$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$1/api/observation-stations?view=mesonet")" == 404 ]]
}

check_metars "$candidate"
check_no_mesonet "$candidate"
gcloud run services update weather-collector "${flags[@]}" --image="$image" --no-traffic --tag="$tag"
collector_revision="$(gcloud run services describe weather-collector "${flags[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(t["revisionName"] for t in d["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
jobs="$(gcloud scheduler jobs list "${scheduler[@]}" --format='value(name)')"
action=create
if [[ "$jobs" == *"/jobs/$audit_job"* ]]; then action=update; fi
gcloud scheduler jobs "$action" http "$audit_job" "${scheduler[@]}" \
  --schedule='2-57/5 * * * *' --time-zone=Etc/UTC --uri="$collector/collect/mn-asos-audit" \
  --http-method=POST --oidc-service-account-email="weather-scheduler@$project.iam.gserviceaccount.com" \
  --oidc-token-audience="$collector" --attempt-deadline=60s --max-retry-attempts=0 --quiet
gcloud run services update-traffic weather-collector "${flags[@]}" --to-revisions="$collector_revision=100"
if [[ "$(gcloud scheduler jobs describe "$audit_job" "${scheduler[@]}" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume "$audit_job" "${scheduler[@]}"
fi
since="$(date +%s)"
gcloud scheduler jobs run "$audit_job" "${scheduler[@]}"
for attempt in {1..12}; do
  if gcloud storage cat "$audit_object" --project="$project" 2>/dev/null |
      python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["checkedAt"]>=int(sys.argv[1]) and d["reports"] and len(d["polls"][-1][1])<2' "$since" 2>/dev/null; then
    break
  fi
  if [[ "$attempt" == 12 ]]; then
    echo "ASOS audit has not produced a fresh result. The public website has not switched." >&2
    exit 1
  fi
  sleep 5
done
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_metars "$site"
check_no_mesonet "$site"
if [[ "$jobs" == *"/jobs/$old_job"* ]]; then
  gcloud scheduler jobs delete "$old_job" "${scheduler[@]}" --quiet
fi
echo "Airport PLOTS and CLOUDS are live at $site. The private Minnesota ASOS audit is running every five minutes."
echo "Read the audit: gcloud storage cat $audit_object --project=$project | python3 mn_asos_audit.py"
