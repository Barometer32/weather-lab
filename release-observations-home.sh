#!/usr/bin/env bash
# Run from a clean checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
tag="obs-cards-$(git rev-parse --short=12 HEAD)"
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

check_home() {
  curl -fsS --retry 2 --retry-all-errors --max-time 20 "$1/" |
    python3 -c '
import re,sys
s=sys.stdin.read()
assert re.findall(r"<button role=\"tab\" id=\"tab-([^\"]+)\"",s)==["observations","metar","radar","satellite","forecast","air-quality"]
assert "id=\"tab-observations\" aria-selected=\"true\"" in s
assert "style.css?v=observations-cards-v2" in s and "rolling-observation-views.js?v=3" in s
section=s.split("<section id=\"observations\"",1)[1].split("</section>",1)[0]
assert " hidden" not in section.split(">",1)[0] and "<table" not in section
assert re.findall(r"<h2>([^<]+)</h2>",section)==["Temperature","Dew point","Wind","Sun angle"]
'
  curl -fsS --retry 2 --max-time 15 "$1/api/observations/rolling" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); assert "current" in d and d["windQcVersion"]=="madis-advisory-wind-v1"'
}

check_home "$candidate"
gcloud run services update-traffic weather-lab "${flags[@]}" --to-revisions="$revision=100"
check_home "$site"
echo "The updated Observations cards are live at $site."
