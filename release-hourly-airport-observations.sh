#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="hourly-airports-$(git rev-parse --short=12 HEAD)"
run=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
job=weather-live-hourly-observations
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

live_html="$(curl -fsS --retry 2 --max-time 20 "$site/")"
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

stage() {
  gcloud run services update "$1" "${run[@]}" --image="$image" --no-traffic --tag="$tag" >&2
  gcloud run services describe "$1" "${run[@]}" --format=json |
    python3 -c 'import json,sys; t=next(t for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]); print(t["revisionName"],t["url"])' "$tag"
}

check_layout() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c '
import re, sys
s=sys.stdin.read()
assert re.findall(r"<button role=\"tab\" id=\"tab-([^\"]+)\"",s)==["observations","metar","radar","satellite","forecast","air-quality"]
assert "id=\"tab-observations\" aria-selected=\"true\"" in s and "TWIN CITIES · HOURLY METAR" in s
assert "style.css?v=hourly-airport-v4" in s and "hourly-observation-views.js?v=4" in s
assert "Last 12 hours" in s and "observations-temperature" not in s
assert s.index("hourly-observation-views.js") < s.index("vendor/leaflet.js")
assert "/api/observations/hourly?view=table" in s
assert "count toward the following hour" not in s
assert "<th scope=\"col\">Airports</th>" not in s
assert "<option value=\"clouds\" selected>" in s and "id=\"observations-sun\"" in s
'
  curl -fsS --max-time 15 "$1/api/observations/hourly?view=table" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["history"]) == 12 and "stations" not in d["history"][0]'
}

check_data() {
  curl -fsS --max-time 15 "$1/api/observations/hourly" |
    python3 -c '
import json, re, sys
from datetime import datetime, timedelta
d=json.load(sys.stdin)
assert d["source"] == "NOAA Aviation Weather Center" and d["stationCount"] == 3
history=d["history"]
assert len(history) == 12
times=[datetime.fromisoformat(h["hour"]) for h in history]
assert all(a-b == timedelta(hours=1) for a,b in zip(times,times[1:]))
for h in history:
    assert {s["code"] for s in h["stations"]} == {"KFCM","KMSP","KMIC"}
    for s in h["stations"]:
        if s["available"]:
            assert datetime.fromisoformat(s["observedAt"]).minute in range(50,60)
            assert not s["rawMetar"].startswith("SPECI")
            assert s["tempF"] is None or re.search(r"\bT[01][0-9]{3}(?:[01][0-9]{3})?\b",s["rawMetar"].partition(" RMK")[2])
complete=sum(h["complete"] for h in history)
assert d["current"] and complete >= int(sys.argv[1])
print(f"Verified {complete} complete hourly three-airport METAR sets.")
' "$2"
}

read -r revision candidate < <(stage weather-lab)
check_layout "$candidate"
if [[ "$live_html" == *'hourly-observation-views.js?v=3"'* || "$live_html" == *'hourly-observation-views.js?v=4"'* ]]; then
  check_data "$candidate" 11
  gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$revision=100"
  check_layout "$site"
  check_data "$site" 11
  echo "The faster Weather Lab startup is live at $site"
  exit 0
fi
read -r collector_revision _ < <(stage weather-collector)
gcloud run services update-traffic weather-collector "${run[@]}" --to-revisions="$collector_revision=100"

jobs="$(gcloud scheduler jobs list "${scheduler[@]}" --format='value(name)')"
job_exists() { grep -Eq "(^|/)$1$" <<< "$jobs"; }
job_state() { gcloud scheduler jobs describe "$1" "${scheduler[@]}" --format='value(state)'; }
action=create
if job_exists "$job"; then action=update; fi
gcloud scheduler jobs "$action" http "$job" "${scheduler[@]}" --schedule='*/2 * * * *' --time-zone=Etc/UTC \
  --uri="$collector/collect/hourly-observations" --http-method=POST \
  --oidc-service-account-email="weather-scheduler@$project.iam.gserviceaccount.com" \
  --oidc-token-audience="$collector" --attempt-deadline=60s --max-retry-attempts=0
if [[ "$(job_state "$job")" == PAUSED ]]; then
  gcloud scheduler jobs resume "$job" "${scheduler[@]}"
fi
gcloud scheduler jobs run "$job" "${scheduler[@]}"
for attempt in {1..24}; do
  if check_data "$candidate" 12 2>/dev/null; then break; fi
  if [[ "$attempt" == 24 ]]; then
    echo 'A complete 12-hour METAR history was not verified. Website traffic was not switched.' >&2
    exit 1
  fi
  sleep 5
done
gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$revision=100"
check_layout "$site"
# Allow the next hour to become pending if the clock rolled over at cutover.
check_data "$site" 11
for retired in weather-live-observation-stations weather-live-mn-asos-audit; do
  if job_exists "$retired" && [[ "$(job_state "$retired")" == ENABLED ]]; then
    gcloud scheduler jobs pause "$retired" "${scheduler[@]}"
  fi
done
echo "Hourly METAR Observations are live at $site"
