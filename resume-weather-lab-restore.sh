#!/usr/bin/env bash
# Resume a completed build without rebuilding images or reusing a restored job.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261024-133205}"
WEATHER_REGION=us-central1
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-resume.XXXXXX")"
WEATHER_PAUSED=()
weather_cleanup() {
  local weather_code="$?" weather_job
  for weather_job in "${WEATHER_PAUSED[@]}"; do
    if ! gcloud scheduler jobs resume "$weather_job" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"; then
      echo "Could not resume $weather_job; check this job's state." >&2
      weather_code=1
    fi
  done
  if [[ "$weather_code" != 0 ]]; then echo "Resume stopped. Saved settings and diagnostics: $WEATHER_WORK" >&2; fi
  trap - EXIT
  exit "$weather_code"
}
trap weather_cleanup EXIT

echo 'Step 1/4: checking the existing project, built image and collection settings.'
[[ "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" == ACTIVE ]] || { echo 'Restore the project first.' >&2; exit 1; }
[[ "$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)' | tr '[:upper:]' '[:lower:]')" == true ]] || { echo 'Link active billing first.' >&2; exit 1; }
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" "$WEATHER_REGION" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1]);project,region=sys.argv[2:]
spec=json.loads((work/'collector-before.json').read_text())['spec']['template']['spec']
container=spec['containers'][0];image=container['image'];account=spec.get('serviceAccountName','')
bucket=next((e.get('value','') for e in container.get('env',[]) if e.get('name')=='WEATHER_DATA_BUCKET'),'')
image_path=image.split('@',1)[0].split(':',1)[0]
if not image_path.startswith(f'{region}-docker.pkg.dev/{project}/') or not image_path.endswith('/app'):
    raise SystemExit('Unexpected collector image; no recovery job or website update started.')
if account!=f'weather-collector@{project}.iam.gserviceaccount.com' or bucket!=f'{project}-weather-data':
    raise SystemExit('Unexpected collector identity or bucket; stopping to preserve existing settings.')
for filename,value in [('image.txt',image),('account.txt',account),('bucket.txt',bucket)]:
    (work/filename).write_text(value+'\n')
managed={'weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds','weather-live-air-quality'}
with (work/'pause-jobs.txt').open('w') as output:
    for job in json.loads((work/'jobs-before.json').read_text()):
        name=job['name'].rsplit('/',1)[-1]
        if name in managed and job.get('state')=='ENABLED':print(name,file=output)
PY
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image.txt")"
WEATHER_COLLECTOR_SA="$(cat "$WEATHER_WORK/account.txt")"
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket.txt")"
printf 'Reusing built image: %s\n' "$WEATHER_IMAGE"
# Retain the full earlier audit entry, including protoPayload omitted by the
# original diagnostic formatter. A missing log entry does not block recovery.
gcloud logging read 'resource.type="cloud_run_job" AND labels."run.googleapis.com/execution_name"="weather-airports-restore-x4vh9"' --project="$WEATHER_PROJECT" --freshness=1d --limit=10 --format=json >"$WEATHER_WORK/previous-failure.json" || true

while IFS= read -r WEATHER_JOB; do
  gcloud scheduler jobs pause "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  WEATHER_PAUSED+=("$WEATHER_JOB")
done <"$WEATHER_WORK/pause-jobs.txt"

echo 'Step 2/4: testing a fresh recovery job and importing the weather history.'
WEATHER_JOB="weather-recover-$(date -u +%y%m%d-%H%M%S)-${WEATHER_WORK##*.}"
WEATHER_JOB="${WEATHER_JOB,,}"
printf '%s\n' "$WEATHER_JOB" >"$WEATHER_WORK/recovery-job.txt"
gcloud run jobs deploy "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args='^|^-u|-c|print("Recovery container started", flush=True); import metar_history; import refresh_media; import air_quality; metar_history.main(); refresh_media.main(); air_quality.main()' --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=1800s --quiet
if ! gcloud run jobs execute "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait; then
  echo 'The fresh job failed. Showing complete task and audit diagnostics; website publication stopped.' >&2
  WEATHER_EXECUTION="$(gcloud run jobs describe "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.latestCreatedExecution.name)')"
  if [[ -n "$WEATHER_EXECUTION" ]]; then
    gcloud run jobs executions describe "${WEATHER_EXECUTION##*/}" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json || true
    gcloud run jobs executions tasks list --execution="${WEATHER_EXECUTION##*/}" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json || true
  fi
  gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$WEATHER_JOB\"" --project="$WEATHER_PROJECT" --freshness=1h --limit=20 --format=json || true
  cat "$WEATHER_WORK/previous-failure.json"
  exit 1
fi

echo 'Step 3/4: publishing the already-built website and verifying the data.'
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --update-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/station-plots" -o "$WEATHER_WORK/metars.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,re,sys
from pathlib import Path
work=Path(sys.argv[1]);page=(work/'page.html').read_text();data=json.loads((work/'metars.json').read_text())
if re.findall(r'<button role="tab" id="tab-([^\"]+)"',page)!=['metar-clouds','radar','satellite','forecast','air-quality'] or 'metar-model.js?v=combined-vector-' not in page:
    raise SystemExit('The latest five-tab layout and compact downwind vectors were not verified.')
frames=data.get('history',[])
if data.get('sourcePolicy')!='airport-routine-only' or data.get('stationPolicy')!='all-airports-v1' or len(frames)!=12 or any(not frame.get('stations') for frame in frames):
    raise SystemExit('Twelve populated airport-only frames were not verified.')
for frame in frames:
    if any(row.get('reportType')!='METAR' or not 45<=int(row['time'][14:16])<=59 for row in frame['stations']):
        raise SystemExit('An ineligible report reached the map.')
    print(frame['hour'],len(frame['stations']),'airport METARs')
print('Verified latest compact station plots and twelve hourly airport frames.')
PY

echo 'Step 4/4: restoring the previously enabled background schedules.'
for WEATHER_JOB in "${WEATHER_PAUSED[@]}"; do
  gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
done
WEATHER_PAUSED=()
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nWeather Lab resume complete.\nDirect website: %s\nUsual address, if its mapping is ready: https://weather-lab.cloud.run\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
