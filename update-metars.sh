#!/usr/bin/env bash
# Restore the saved cloud-circle METAR model and immediately import 12 real hours.
set -euo pipefail
WEATHER_PROJECT="weather-orig-261019-183538"
WEATHER_REGION="us-central1"
WEATHER_BRANCH="metar-cloud-history-20261019"
WEATHER_WORK="$(mktemp -d "$HOME/weather-metar-cloud-update.XXXXXX")"
WEATHER_PAUSED=0
WEATHER_UPDATE_METAR_HISTORY="${WEATHER_UPDATE_METAR_HISTORY:-1}"
WEATHER_JOB="weather-live-metar-clouds"

weather_cleanup() {
  local weather_exit="$?"
  if [[ "$WEATHER_PAUSED" == "1" ]]; then
    echo "Resuming the hourly METAR schedule."
    gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" || true
  fi
  if [[ "$weather_exit" != "0" ]]; then
    echo "Update stopped. Settings and diagnostic output are saved in $WEATHER_WORK." >&2
  fi
}
trap weather_cleanup EXIT

echo "Step 1/5: fetching the METAR update and saving existing service settings."
git clone --quiet --depth=1 --branch "$WEATHER_BRANCH" https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:metar-${WEATHER_COMMIT:0:12}"
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/$WEATHER_SERVICE-before.yaml"
done
WEATHER_COLLECTOR_SA="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.serviceAccountName)')"
WEATHER_BUCKET="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(e["value"] for e in d["spec"]["template"]["spec"]["containers"][0]["env"] if e["name"]=="WEATHER_DATA_BUCKET"))')"
WEATHER_STATE="$(gcloud scheduler jobs describe "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')"

echo "Step 2/5: building the updated image."
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi

echo "Step 3/5: updating the METAR renderer and hourly collector."
if [[ "$WEATHER_STATE" == "ENABLED" ]]; then
  gcloud scheduler jobs pause "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  WEATHER_PAUSED=1
fi
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud scheduler jobs update http "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='2 * * * *' --time-zone=Etc/UTC --quiet

if [[ "$WEATHER_UPDATE_METAR_HISTORY" == "1" ]]; then
echo "Step 4/5: importing the last 12 completed hours from NOAA."
if ! gcloud run jobs deploy weather-metar-backfill --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args=metar_history.py --tasks=1 --parallelism=1 --cpu=1 --memory=1Gi --max-retries=0 --task-timeout=1200s --execute-now --wait --quiet; then
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="weather-metar-backfill"' --project="$WEATHER_PROJECT" --freshness=30m --limit=30 --format='value(textPayload,jsonPayload.message)' || true
  exit 1
fi

else
  echo "Step 4/5: keeping the existing twelve-hour history; no new archive import."
fi

echo "Step 5/5: resuming hourly collection and verifying the published timeline."
gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
WEATHER_PAUSED=0
gcloud scheduler jobs run "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
echo "Requested an authenticated Scheduler refresh. Submission does not confirm collection; checking the completed archive import below."
gcloud storage cat "gs://$WEATHER_BUCKET/live/metar-clouds.json" >"$WEATHER_WORK/published-metar-history.json"
python3 - "$WEATHER_WORK/published-metar-history.json" <<'PY'
import json,sys
from datetime import datetime,timezone,timedelta
with open(sys.argv[1]) as f:
    data=json.load(f)
frames=data.get("history",[])
if len(frames)!=12 or any(not frame.get("stations") for frame in frames):
    raise SystemExit("The published timeline does not yet contain 12 populated hours.")
for frame in frames:
    print(f'{frame["hour"]}: {len(frame["stations"])} official airport reports')
target=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
if datetime.fromisoformat(frames[-1]["hour"].replace("Z","+00:00")) < target-timedelta(hours=1):
    raise SystemExit("The published history is not current.")
if not all("skyCover" in row and "ceiling" in row for frame in frames for row in frame["stations"]):
    raise SystemExit("Cloud-model fields are missing from some published reports.")
print("Verified: 12 populated hours with cloud-model fields.")
PY
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl -fsS --max-time 90 "$WEATHER_URL" >"$WEATHER_WORK/published-page.html"
if ! grep -q 'metar-model.js' "$WEATHER_WORK/published-page.html"; then
  echo "The website is not yet serving the updated station-model page." >&2
  exit 1
fi
printf '\nUpdate complete. Open and hard-refresh: %s\nSource: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT"
echo "METARs: :45–:59 reports; hourly collection at :02. The published twelve-hour timeline has been verified."

