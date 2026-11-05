#!/usr/bin/env bash
# Run from a clean checkout of this release in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
WEATHER_PROJECT=weather-lab-261105-184200-1a9b
WEATHER_REGION=us-central1
WEATHER_DOMAIN=https://weather-lab.cloud.run
WEATHER_COMMIT="$(git rev-parse --short=12 HEAD)"
WEATHER_TAG="hourly-$WEATHER_COMMIT"
WEATHER_WORK="$(mktemp -d)"
trap 'rm -rf -- "$WEATHER_WORK"' EXIT

cloud_run=(--project="$WEATHER_PROJECT" --region="$WEATHER_REGION")
cloud_scheduler=(--project="$WEATHER_PROJECT" --location="$WEATHER_REGION")
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"

echo "Checking the live Weather Lab project and existing services..."
[[ -z "$(git status --porcelain)" ]] || { echo "Deploy from a clean release checkout."; exit 1; }
[[ "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" == ACTIVE ]]
gcloud beta run domain-mappings describe --domain=weather-lab.cloud.run "${cloud_run[@]}" --format=json |
  python3 -c 'import json, sys; m=json.load(sys.stdin); sys.exit(not (m.get("spec",{}).get("routeName")=="weather-lab" and any(c.get("type")=="Ready" and c.get("status")=="True" for c in m.get("status",{}).get("conditions",[]))))'
[[ "$(gcloud scheduler jobs describe weather-live-forecast "${cloud_scheduler[@]}" --format='value(state)')" == ENABLED ]]
WEATHER_IMAGE_BASE="$(gcloud run services describe weather-lab "${cloud_run[@]}" --format=json |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$WEATHER_IMAGE_BASE" in
  "$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/"*/app) ;;
  *) echo "Unexpected live image repository. No changes made." >&2; exit 1 ;;
esac
WEATHER_IMAGE="$WEATHER_IMAGE_BASE:$WEATHER_TAG"

echo "Building the forecast and performance update..."
gcloud builds submit . --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" \
  --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

echo "Starting the updated collector and asking it to prepare the Hopkins forecast..."
gcloud run services update weather-collector "${cloud_run[@]}" --image="$WEATHER_IMAGE"
gcloud run services update-traffic weather-collector "${cloud_run[@]}" --to-latest
gcloud scheduler jobs run weather-live-forecast "${cloud_scheduler[@]}"

echo "Preparing a candidate web revision without switching the public address..."
gcloud run services update weather-lab "${cloud_run[@]}" --image="$WEATHER_IMAGE" --no-traffic --tag="$WEATHER_TAG"
gcloud run services describe weather-lab "${cloud_run[@]}" --format=json > "$WEATHER_WORK/service.json"
WEATHER_REVISION="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(next(t["revisionName"] for t in s["status"]["traffic"] if t.get("tag")==sys.argv[2]))' "$WEATHER_WORK/service.json" "$WEATHER_TAG")"
WEATHER_CANDIDATE="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(next(t["url"] for t in s["status"]["traffic"] if t.get("tag")==sys.argv[2]))' "$WEATHER_WORK/service.json" "$WEATHER_TAG")"
check_hourly() {
  curl -fsS --max-time 15 "$1/api/forecast" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(not (d.get("hourlyUpdatedAt") and any(p.get("hourlyWindows") for p in d.get("periods",[]))))'
}

for weather_try in 1 2 3 4 5 6; do
  if check_hourly "$WEATHER_CANDIDATE"; then break; fi
  if [[ "$weather_try" == 6 ]]; then
    echo "Hourly NWS data is not ready. The public site still points at its previous revision." >&2
    exit 1
  fi
  sleep 10
done

python3 verify_lowest_radar_site.py "$WEATHER_CANDIDATE"
gcloud run services update-traffic weather-lab "${cloud_run[@]}" --to-revisions="$WEATHER_REVISION=100"
curl -fsS --retry 3 --retry-all-errors --max-time 20 "$WEATHER_DOMAIN/" -o "$WEATHER_WORK/index.html"
grep -q 'app.js?v=hourly-forecast-v1' "$WEATHER_WORK/index.html"
check_hourly "$WEATHER_DOMAIN"
echo "Weather Lab update live: $WEATHER_DOMAIN"
