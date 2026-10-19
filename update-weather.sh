#!/usr/bin/env bash
# Update this restored site; keep station history and restore background media.
set -euo pipefail
WEATHER_PROJECT="weather-orig-261019-183538"
WEATHER_REGION="us-central1"
WEATHER_BRANCH="metar-cloud-history-20261019"
WEATHER_WORK="$(mktemp -d "$HOME/weather-background-update.XXXXXX")"
WEATHER_PAUSED_JOBS=()
weather_cleanup() {
  local weather_exit="$?"
  for weather_job in "${WEATHER_PAUSED_JOBS[@]}"; do
    gcloud scheduler jobs resume "$weather_job" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" || true
  done
  if [[ "$weather_exit" != "0" ]]; then echo "Update needs attention. Diagnostic files: $WEATHER_WORK" >&2; fi
}
trap weather_cleanup EXIT

echo "Step 1/5: fetching the update and saving existing service settings."
git clone --quiet --depth=1 --branch "$WEATHER_BRANCH" https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:background-${WEATHER_COMMIT:0:12}"
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/$WEATHER_SERVICE-before.yaml"
done
WEATHER_COLLECTOR_SA="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(spec.template.spec.serviceAccountName)')"
WEATHER_BUCKET="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(e["value"] for e in d["spec"]["template"]["spec"]["containers"][0]["env"] if e["name"]=="WEATHER_DATA_BUCKET"))')"
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="weather-collector" AND severity>=ERROR' --project="$WEATHER_PROJECT" --freshness=2h --limit=15 --format='value(timestamp,textPayload,jsonPayload.message)' >"$WEATHER_WORK/previous-collector-errors.txt"

echo "Step 2/5: building the updated image."
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi
for WEATHER_JOB in weather-live-radar weather-live-satellite weather-live-forecast; do
  gcloud scheduler jobs pause "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  WEATHER_PAUSED_JOBS+=("$WEATHER_JOB")
done

echo "Step 3/5: updating services and authenticated background schedules."
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_SCHEDULER_SA="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com"
gcloud run services add-iam-policy-binding weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --member="serviceAccount:$WEATHER_SCHEDULER_SA" --role=roles/run.invoker >/dev/null
weather_schedule() {
  local weather_job="$1" weather_cron="$2" weather_endpoint="$3"
  gcloud scheduler jobs update http "$weather_job" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule="$weather_cron" --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/$weather_endpoint" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER_SA" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
}
weather_schedule weather-live-radar '* * * * *' radar-KMPX
weather_schedule weather-live-satellite '*/5 * * * *' satellite
weather_schedule weather-live-forecast '0,30 * * * *' forecast

echo "Step 4/5: recovering real two-hour image histories. This may take several minutes."
if ! gcloud run jobs deploy weather-media-refresh --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args=refresh_media.py --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=1200s --execute-now --wait --quiet; then
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="weather-media-refresh"' --project="$WEATHER_PROJECT" --freshness=30m --limit=25 --format='value(textPayload,jsonPayload.message)'
  exit 1
fi
for WEATHER_JOB in "${WEATHER_PAUSED_JOBS[@]}"; do
  gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done
WEATHER_PAUSED_JOBS=()

echo "Step 5/5: checking saved timestamps and requesting authenticated background runs."
for WEATHER_JOB in weather-live-radar weather-live-satellite; do
  gcloud scheduler jobs run "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 - "$WEATHER_WEB_URL" <<'PY'
import json,sys,urllib.request
from datetime import datetime,timezone,timedelta
base=sys.argv[1]
issues=[]
for path in ['/api/radar?site=KMPX','/api/satellite/truecolor','/api/satellite/dcphase','/api/satellite/ntmicro']:
    with urllib.request.urlopen(base+path,timeout=90) as response:
        data=json.load(response)
    times=[datetime.fromisoformat(f['time'].replace('Z','+00:00')) for f in data['frames']]
    if not times:
        issues.append(path+': no frames'); continue
    now=datetime.now(timezone.utc)
    print(f'{path}: {len(times)} frames; {min(times).isoformat()} to {max(times).isoformat()}',flush=True)
    if max(times)<now-timedelta(minutes=20): issues.append(path+': latest image is over 20 minutes old')
    if min(times)>now-timedelta(minutes=105): issues.append(path+': the two-hour history still has a large gap at its beginning')
    ordered=sorted(times)
    if any(b-a>timedelta(minutes=20) for a,b in zip(ordered,ordered[1:])): issues.append(path+': an interior image gap is over 20 minutes')
if issues:
    raise SystemExit('\n'.join(issues))
print('Verified: recent imagery and coverage near the start of each two-hour window.')
PY
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name.basename():label=JOB,state,schedule,status.code:label=LAST_STATUS)'
printf '\nWebsite: %s\nSource: %s\nDiagnostics: %s\n' "$WEATHER_WEB_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
echo "Radar checks every minute; satellite every five minutes; forecast at :00/:30; METAR remains at :02."
echo "The sun elevation appears only on the METAR tab. Refresh with Ctrl+Shift+R."
echo "Scheduled run submission alone does not confirm execution. If a feed stalls, send the timestamps and saved collector errors above."
