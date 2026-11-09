#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="obs-wind-$(git rev-parse --short=12 HEAD)"
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

check_observations() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c '
import re, sys
s=sys.stdin.read()
assert "rolling-observation-views.js?v=2" in s and "id=\"observations-sun\"" in s
table=re.search(r"<table>.*?</table>",s.split("<section id=\"observations\"",1)[1],re.S)[0]
assert re.findall(r"<th scope=\"col\">([^<]+)</th>",table)==["Time","Temp","Dew point","Wind"]
'
  curl -fsS --max-time 15 "$1/api/observations/rolling" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["checkedAt"] and len(d["history"]) == 12'
}

check_observations "$candidate"
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_observations "$site"
echo "Updated Observations is live at $site. The collector and its schedule were not changed."
