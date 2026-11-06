#!/usr/bin/env bash
# Run from a clean checkout of this release in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
WEATHER_PROJECT=weather-lab-261105-184200-1a9b
WEATHER_REGION=us-central1
WEATHER_DOMAIN=https://weather-lab.cloud.run
WEATHER_COMMIT="$(git rev-parse --short=12 HEAD)"
WEATHER_TAG="nbm-outlook-$WEATHER_COMMIT"
WEATHER_WORK="$(mktemp -d)"
trap 'rm -rf -- "$WEATHER_WORK"' EXIT

cloud_run=(--project="$WEATHER_PROJECT" --region="$WEATHER_REGION")
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"

echo "Checking the live Weather Lab project and existing services..."
[[ -z "$(git status --porcelain)" ]] || { echo "Deploy from a clean release checkout."; exit 1; }
[[ "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" == ACTIVE ]]
gcloud beta run domain-mappings describe --domain=weather-lab.cloud.run "${cloud_run[@]}" --format=json |
  python3 -c 'import json, sys; m=json.load(sys.stdin); sys.exit(not (m.get("spec",{}).get("routeName")=="weather-lab" and any(c.get("type")=="Ready" and c.get("status")=="True" for c in m.get("status",{}).get("conditions",[]))))'
WEATHER_IMAGE_BASE="$(gcloud run services describe weather-lab "${cloud_run[@]}" --format=json |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0]["image"].split("@",1)[0].split(":",1)[0])')"
case "$WEATHER_IMAGE_BASE" in
  "$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/"*/app) ;;
  *) echo "Unexpected live image repository. No changes made." >&2; exit 1 ;;
esac
WEATHER_IMAGE="$WEATHER_IMAGE_BASE:$WEATHER_TAG"

echo "Building the NOAA NBM update..."
gcloud builds submit . --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" \
  --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

echo "Updating the existing private weather collector..."
gcloud run services update weather-collector "${cloud_run[@]}" --image="$WEATHER_IMAGE"
gcloud run services update-traffic weather-collector "${cloud_run[@]}" --to-latest
COLLECTOR_URL="$(gcloud run services describe weather-collector "${cloud_run[@]}" --format='value(status.url)')"
SCHEDULER_SA="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com"
SCHEDULER=(--project="$WEATHER_PROJECT" --location="$WEATHER_REGION")
SCHEDULE_ACTION=create
if gcloud scheduler jobs describe weather-live-nbm "${SCHEDULER[@]}" >/dev/null 2>&1; then
  SCHEDULE_ACTION=update
fi
gcloud scheduler jobs "$SCHEDULE_ACTION" http weather-live-nbm "${SCHEDULER[@]}" \
  --schedule='0,15,30,45 * * * *' --time-zone=Etc/UTC --http-method=POST \
  --uri="$COLLECTOR_URL/collect/nbm" --oidc-token-audience="$COLLECTOR_URL" \
  --oidc-service-account-email="$SCHEDULER_SA" --attempt-deadline=180s
if [[ "$(gcloud scheduler jobs describe weather-live-nbm "${SCHEDULER[@]}" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-nbm "${SCHEDULER[@]}"
fi
gcloud scheduler jobs run weather-live-nbm "${SCHEDULER[@]}"

echo "Preparing a candidate web revision without switching the public address..."
gcloud run services update weather-lab "${cloud_run[@]}" --image="$WEATHER_IMAGE" --no-traffic --tag="$WEATHER_TAG"
gcloud run services describe weather-lab "${cloud_run[@]}" --format=json > "$WEATHER_WORK/service.json"
WEATHER_REVISION="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(next(t["revisionName"] for t in s["status"]["traffic"] if t.get("tag")==sys.argv[2]))' "$WEATHER_WORK/service.json" "$WEATHER_TAG")"
WEATHER_CANDIDATE="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(next(t["url"] for t in s["status"]["traffic"] if t.get("tag")==sys.argv[2]))' "$WEATHER_WORK/service.json" "$WEATHER_TAG")"
check_nbm() {
  curl -fsS --retry 2 --retry-all-errors --max-time 15 "$1/api/nbm" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(not (d.get("station") == "KFCM" and d.get("product") == "NBH" and d.get("cycleAt") and d.get("hours") and d.get("outlookVersion") == 3 and 9 <= len(d.get("days", [])) <= 10 and all([p.get("kind") for p in day.get("periods", [])] == ["day", "night"] for day in d["days"]) and d.get("horizonHours", 0) >= 250 and d.get("stale") is False))'
}

for weather_try in 1 2 3 4 5 6 7 8; do
  if check_nbm "$WEATHER_CANDIDATE"; then break; fi
  if [[ "$weather_try" == 8 ]]; then
    echo "NOAA NBM data is not ready. The public site still points at its previous revision." >&2
    exit 1
  fi
  sleep 10
done

curl -fsS --max-time 20 "$WEATHER_CANDIDATE/" -o "$WEATHER_WORK/candidate.html"
grep -Fq 'app.js?v=nbm-outlook-v3' "$WEATHER_WORK/candidate.html"
python3 verify_lowest_radar_site.py "$WEATHER_CANDIDATE"
gcloud run services update-traffic weather-lab "${cloud_run[@]}" --to-revisions="$WEATHER_REVISION=100"
curl -fsS --retry 3 --retry-all-errors --max-time 20 "$WEATHER_DOMAIN/" -o "$WEATHER_WORK/index.html"
grep -q 'app.js?v=nbm-outlook-v3' "$WEATHER_WORK/index.html"
check_nbm "$WEATHER_DOMAIN"
echo "Weather Lab update live: $WEATHER_DOMAIN"
