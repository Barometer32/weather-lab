#!/usr/bin/env bash
# Restore the original full METAR map in the existing J-Weather project.
set -euo pipefail
WEATHER_PROJECT="j-weather-261020012817"
WEATHER_REGION="us-central1"
WEATHER_BRANCH="metar-cloud-history-20261019"
WEATHER_WORK="$(mktemp -d "$HOME/j-weather-metar-restore.XXXXXX")"
WEATHER_RESUME_METARS=false
WEATHER_RESUME_MADIS=false
weather_cleanup() {
  local weather_exit=$?
  if [[ "$WEATHER_RESUME_METARS" == true ]]; then
    gcloud scheduler jobs resume weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" || true
  fi
  if [[ "$WEATHER_RESUME_MADIS" == true ]]; then
    gcloud scheduler jobs resume weather-live-madis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" || true
  fi
  if [[ "$weather_exit" != 0 ]]; then
    echo "Restore stopped. Send the error above to ChatGPT. Saved settings: $WEATHER_WORK" >&2
  fi
}
trap weather_cleanup EXIT

echo "Step 1/5: checking the restored project and saving service settings."
test "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" = ACTIVE
if [[ "$(gcloud billing projects describe "$WEATHER_PROJECT" --format='value(billingEnabled)')" != [Tt]rue ]]; then
  echo "Enable billing for $WEATHER_PROJECT before running this restore." >&2
  exit 1
fi
gcloud config set project "$WEATHER_PROJECT"
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/website-before.yaml"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=export >"$WEATHER_WORK/collector-before.yaml"
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1]);spec=json.loads((work/'collector-before.json').read_text())['spec']['template']['spec']
env={item['name']:item.get('value','') for item in spec['containers'][0].get('env',[])}
(work/'bucket.txt').write_text(env['WEATHER_DATA_BUCKET'])
(work/'collector-sa.txt').write_text(spec['serviceAccountName'])
PY
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket.txt")"
WEATHER_COLLECTOR_SA="$(cat "$WEATHER_WORK/collector-sa.txt")"
test -n "$WEATHER_BUCKET"
test -n "$WEATHER_COLLECTOR_SA"
gcloud storage buckets describe "gs://$WEATHER_BUCKET" >/dev/null
git clone --quiet --depth=1 --branch "$WEATHER_BRANCH" https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:metar-${WEATHER_COMMIT:0:12}"

echo "Step 2/5: building and restoring the full METAR map."
if ! gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
fi
gcloud run services update weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --memory=2Gi --quiet
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"

echo "Step 3/5: restoring the hourly METAR schedule and twelve-hour history."
WEATHER_METAR_ACTION="$(python3 - "$WEATHER_WORK/jobs-before.json" <<'PY'
import json,sys
jobs=json.load(open(sys.argv[1]))
print('update' if any(j['name'].rsplit('/',1)[-1]=='weather-live-metar-clouds' for j in jobs) else 'create')
PY
)"
gcloud scheduler jobs "$WEATHER_METAR_ACTION" http weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='0 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/metar-clouds" --http-method=POST --oidc-service-account-email="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
WEATHER_RESUME_METARS=true
WEATHER_MADIS_ACTION="$(python3 - "$WEATHER_WORK/jobs-before.json" <<'PY'
import json,sys
jobs=json.load(open(sys.argv[1]))
print('update' if any(j['name'].rsplit('/',1)[-1]=='weather-live-madis' for j in jobs) else 'create')
PY
)"
gcloud scheduler jobs "$WEATHER_MADIS_ACTION" http weather-live-madis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule='*/5 * * * *' --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/madis-stations" --http-method=POST --oidc-service-account-email="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
if [[ "$(gcloud scheduler jobs describe weather-live-madis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-madis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
WEATHER_RESUME_MADIS=true
# The existing archive reader validates all twelve frames before publishing.
WEATHER_IMPORT='import metar_history; import regional_madis; metar_history.main(); regional_madis.main()'
gcloud run jobs deploy weather-metar-history --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_BUCKET" --command=python --args="^|^-c|$WEATHER_IMPORT" --tasks=1 --parallelism=1 --cpu=1 --memory=2Gi --max-retries=0 --task-timeout=1800s --quiet
if ! gcloud run jobs execute weather-metar-history --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait; then
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="weather-metar-history"' --project="$WEATHER_PROJECT" --freshness=30m --limit=20 --format='value(textPayload,jsonPayload.message)'
  exit 1
fi
gcloud scheduler jobs resume weather-live-metar-clouds --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
WEATHER_RESUME_METARS=false
gcloud scheduler jobs resume weather-live-madis --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
WEATHER_RESUME_MADIS=false

echo "Step 4/5: resuming the existing background updates."
WEATHER_JOB_ROWS="$(gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(name,state)')"
while IFS=$'\t' read -r WEATHER_JOB WEATHER_STATE; do
  WEATHER_JOB="${WEATHER_JOB##*/}"
  case "$WEATHER_JOB" in
    weather-live-current|weather-live-radar|weather-live-satellite|weather-live-forecast|weather-live-metar-clouds|weather-live-madis)
      if [[ "$WEATHER_STATE" == PAUSED ]]; then
        gcloud scheduler jobs resume "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
      elif [[ "$WEATHER_STATE" != ENABLED ]]; then
        echo "Job $WEATHER_JOB is $WEATHER_STATE; inspect it in Cloud Scheduler." >&2
        continue
      fi
      gcloud scheduler jobs run "$WEATHER_JOB" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
      ;;
  esac
done <<< "$WEATHER_JOB_ROWS"

echo "Step 5/5: verifying the published map and saved history."
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/api/station-plots" -o "$WEATHER_WORK/metars.json"
python3 - "$WEATHER_WORK" <<'PY'
import json,sys
from pathlib import Path
work=Path(sys.argv[1]);page=(work/'page.html').read_text();data=json.loads((work/'metars.json').read_text())
if '/static/metar-model.js?v=madis-metar-20261023' not in page or 'id="metar-heading">METAR' not in page:
    raise SystemExit('The full METAR page is not published yet.')
frames=data.get('history',[])
if len(frames)!=12 or any(not frame.get('stations') for frame in frames):
    raise SystemExit('Twelve complete regional hourly snapshots are not available; inspect the history job.')
if not data.get('madis',{}).get('available') or not any(frame.get('madisCount') for frame in frames):
    raise SystemExit('MADIS history is not available; inspect the history job.')
print('Verified full METAR + public MADIS page and all 12 hourly snapshots.')
for frame in frames:print(frame['hour'],frame.get('airportCount',0),'airports;',frame.get('madisCount',0),'MADIS;',frame.get('hennepinCount',0),'Hennepin West')
PY
printf '\nOpen your usual J-Weather address and refresh.\nService URL: %s\nSource: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_COMMIT" "$WEATHER_WORK"
