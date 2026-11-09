#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="rolling-obs-$(git rev-parse --short=12 HEAD)"
flags=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
audit_job=weather-live-mn-asos-audit
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
    python3 -c 'import sys; s=sys.stdin.read(); sys.exit(not ("prepared-data.js?v=rolling-observations-v1" in s and "metar-views.js?v=rolling-observations-v1" in s and "metar-model.js?v=hrmetar-celsius-v1" in s and "style.css?v=rolling-observations-v1" in s and "radar-roads.js?v=primary-roads-option-v1" in s and "PLOTS</option>" in s and "CLOUDS</option>" in s and "HRMETAR</option>" not in s and "rolling-observation-views.js?v=1" in s and "MESONET</option>" not in s))'
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

check_observations() {
  curl -fsS --max-time 15 "$1/api/observations/rolling" |
    python3 -c '
import json,sys
from datetime import datetime
d=json.load(sys.stdin)
assert d["windowMinutes"]==30 and len(d["history"])==12
assert set(d["stationNames"])=={"KMSP","KFCM","KMIC"}
assert int(datetime.fromisoformat(d["checkedAt"]).timestamp())>=int(sys.argv[1])
assert all(datetime.fromisoformat(r["time"]).minute==0 for r in d["history"])
assert d["current"] or any(row["reading"] for row in d["history"]), "No matching observations yet"
' "$since"
}

check_metars "$candidate"
gcloud run services update weather-collector "${flags[@]}" --image="$image" --no-traffic --tag="$tag"
collector_revision="$(gcloud run services describe weather-collector "${flags[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(t["revisionName"] for t in d["status"]["traffic"] if t.get("tag")==sys.argv[1]))' "$tag")"
gcloud scheduler jobs describe "$audit_job" "${scheduler[@]}" --format=json |
  python3 -c '
import json, sys
d=json.load(sys.stdin)
assert d["state"] == "ENABLED" and d["schedule"] == "2-57/5 * * * *" and d["httpTarget"]["uri"] == sys.argv[1], "The five-minute ASOS audit must already be enabled on the expected collector"
' "$collector/collect/mn-asos-audit"
gcloud run services update-traffic weather-collector "${flags[@]}" --to-revisions="$collector_revision=100"
since="$(date +%s)"
gcloud scheduler jobs run "$audit_job" "${scheduler[@]}"
for attempt in {1..12}; do
  if check_observations "$candidate" 2>/dev/null && gcloud storage cat "$audit_object" --project="$project" 2>/dev/null |
      python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["checkedAt"]>=int(sys.argv[1]) and d["reports"] and len(d["polls"][-1][1])<2' "$since" 2>/dev/null; then
    break
  fi
  if [[ "$attempt" == 12 ]]; then
    echo "The collector has not produced a fresh three-airport result. The public website has not switched." >&2
    exit 1
  fi
  sleep 5
done
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_metars "$site"
check_observations "$site"
echo "PLOTS, CLOUDS, and OBSERVATIONS are live at $site. The existing five-minute collection schedule is unchanged."
echo "Read the audit: gcloud storage cat $audit_object --project=$project | python3 mn_asos_audit.py"
