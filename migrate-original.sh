#!/usr/bin/env bash
# Migrate the October 12 Weather Lab source and accessible data to a new project.
set -euo pipefail
WEATHER_OLD_PROJECT="weather-lab-511113"
WEATHER_SOURCE_COMMIT="eb6871d2b467647d4b362e8c36e56fba8c629213"
WEATHER_REGION="us-central1"
WEATHER_WORK="$HOME/weather-original-migration-20261019"
mkdir -p "$WEATHER_WORK"
trap 'echo "Migration stopped at line $LINENO. Rerun the same command to resume; project information is in $WEATHER_WORK." >&2' ERR

weather_retry() {
  local weather_attempt
  for weather_attempt in 1 2 3 4 5 6; do
    if "$@"; then return 0; fi
    if [[ "$weather_attempt" == "6" ]]; then return 1; fi
    echo "Waiting 10 seconds for Google Cloud setup to propagate (attempt $weather_attempt/6)." >&2
    sleep 10
  done
}

echo "Step 1/8: checking the source and billing account."
if [[ ! -d "$WEATHER_WORK/source/.git" ]]; then
  git clone --quiet --no-checkout https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
if [[ "$(git -C "$WEATHER_WORK/source" rev-parse HEAD)" != "$WEATHER_SOURCE_COMMIT" ]]; then
  echo "The source directory is on a different revision. Stopping to preserve it." >&2
  exit 1
fi
WEATHER_BILLING="$(gcloud billing projects describe "$WEATHER_OLD_PROJECT" --format='value(billingAccountName)')"
WEATHER_BILLING="${WEATHER_BILLING##*/}"
if [[ -z "$WEATHER_BILLING" ]]; then
  echo "The old project has no linked billing account. Link it before running this migration." >&2
  exit 1
fi
WEATHER_BILLING_OPEN="$(gcloud billing accounts describe "$WEATHER_BILLING" --format='value(open)')"
if [[ "$WEATHER_BILLING_OPEN" != "True" && "$WEATHER_BILLING_OPEN" != "true" ]]; then
  echo "The linked billing account is not open." >&2
  exit 1
fi

echo "Step 2/8: creating or resuming the new project."
if [[ ! -s "$WEATHER_WORK/project-id.txt" ]]; then
  printf 'weather-orig-%s\n' "$(date -u +%y%m%d-%H%M%S)" >"$WEATHER_WORK/project-id.txt"
fi
WEATHER_PROJECT="$(cat "$WEATHER_WORK/project-id.txt")"
echo "NEW PROJECT ID: $WEATHER_PROJECT"
if [[ ! -f "$WEATHER_WORK/project-created" ]]; then
  if gcloud projects create "$WEATHER_PROJECT" --name="Weather Lab Original Restored" 2>"$WEATHER_WORK/project-create.err"; then
    touch "$WEATHER_WORK/project-created"
  elif grep -q 'ALREADY_EXISTS' "$WEATHER_WORK/project-create.err"; then
    gcloud projects describe "$WEATHER_PROJECT" --format='value(projectId)'
    touch "$WEATHER_WORK/project-created"
  else
    cat "$WEATHER_WORK/project-create.err" >&2
    exit 1
  fi
fi
WEATHER_STATE="$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')"
if [[ "$WEATHER_STATE" != "ACTIVE" ]]; then
  echo "The migration project is not ACTIVE. Stopping without creating another project." >&2
  exit 1
fi
gcloud billing projects link "$WEATHER_PROJECT" --billing-account="$WEATHER_BILLING"
gcloud config set project "$WEATHER_PROJECT"
weather_retry gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com iam.googleapis.com --project="$WEATHER_PROJECT"

WEATHER_BUCKET="gs://$WEATHER_PROJECT-weather-data"
WEATHER_IMAGE="$WEATHER_REGION-docker.pkg.dev/$WEATHER_PROJECT/weather-lab/app:original-eb6871d2"
WEATHER_WEB_SA="weather-web@$WEATHER_PROJECT.iam.gserviceaccount.com"
WEATHER_COLLECTOR_SA="weather-collector@$WEATHER_PROJECT.iam.gserviceaccount.com"
WEATHER_BUILD_SA="weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com"
WEATHER_SCHEDULER_SA="weather-scheduler@$WEATHER_PROJECT.iam.gserviceaccount.com"

echo "Step 3/8: preparing registry, identities, and private storage."
if ! gcloud artifacts repositories describe weather-lab --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" >/dev/null 2>&1; then
  weather_retry gcloud artifacts repositories create weather-lab --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --repository-format=docker
fi
for WEATHER_SA in weather-web weather-collector weather-builder weather-scheduler; do
  if ! gcloud iam service-accounts describe "$WEATHER_SA@$WEATHER_PROJECT.iam.gserviceaccount.com" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
    weather_retry gcloud iam service-accounts create "$WEATHER_SA" --project="$WEATHER_PROJECT"
  fi
done
weather_retry gcloud projects add-iam-policy-binding "$WEATHER_PROJECT" --member="serviceAccount:$WEATHER_BUILD_SA" --role=roles/cloudbuild.builds.builder --condition=None --quiet >/dev/null
if ! gcloud storage buckets describe "$WEATHER_BUCKET" >/dev/null 2>&1; then
  weather_retry gcloud storage buckets create "$WEATHER_BUCKET" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets update "$WEATHER_BUCKET" --lifecycle-file="$WEATHER_WORK/source/data-lifecycle.json" --clear-soft-delete --no-versioning --public-access-prevention
weather_retry gcloud storage buckets add-iam-policy-binding "$WEATHER_BUCKET" --member="serviceAccount:$WEATHER_COLLECTOR_SA" --role=roles/storage.objectAdmin >/dev/null
weather_retry gcloud storage buckets add-iam-policy-binding "$WEATHER_BUCKET" --member="serviceAccount:$WEATHER_WEB_SA" --role=roles/storage.objectViewer >/dev/null

echo "Step 4/8: copying saved prepared data."
if [[ ! -f "$WEATHER_WORK/data-copy-attempted" ]]; then
  if gcloud storage rsync "gs://$WEATHER_OLD_PROJECT-weather-data" "$WEATHER_BUCKET" --recursive; then
    echo "Saved weather data copied."
    touch "$WEATHER_WORK/data-copy-complete"
  else
    echo "NOTICE: Some old data could not be copied. Continuing so the collectors can fetch fresh weather data." >&2
  fi
  touch "$WEATHER_WORK/data-copy-attempted"
else
  echo "Keeping data already present in the new project."
fi

echo "Step 5/8: building the pinned October 12 source."
if [[ -f "$WEATHER_WORK/image-built" ]] && gcloud artifacts docker images describe "$WEATHER_IMAGE" --project="$WEATHER_PROJECT" >/dev/null 2>&1; then
  echo "Using the migration image already built in this project."
else
  gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --tag="$WEATHER_IMAGE" --region="$WEATHER_REGION" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/$WEATHER_BUILD_SA" --default-buckets-behavior=regional-user-owned-bucket
  touch "$WEATHER_WORK/image-built"
fi

echo "Step 6/8: deploying the original collector and website."
weather_retry gcloud run deploy weather-collector --project="$WEATHER_PROJECT" --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --no-allow-unauthenticated --service-account="$WEATHER_COLLECTOR_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=4 --timeout=300 --command=gunicorn --args=--bind,0.0.0.0:8080,--workers,1,--threads,4,--timeout,300,collector:app --quiet
weather_retry gcloud run services add-iam-policy-binding weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --member="serviceAccount:$WEATHER_SCHEDULER_SA" --role=roles/run.invoker >/dev/null
weather_retry gcloud run deploy weather-lab --project="$WEATHER_PROJECT" --image="$WEATHER_IMAGE" --region="$WEATHER_REGION" --allow-unauthenticated --service-account="$WEATHER_WEB_SA" --set-env-vars="WEATHER_DATA_BUCKET=$WEATHER_PROJECT-weather-data" --cpu-throttling --cpu=1 --memory=1Gi --min-instances=0 --max-instances=1 --concurrency=8 --timeout=90 --quiet
WEATHER_COLLECTOR_URL="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
WEATHER_WEB_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
printf 'Website: %s\n' "$WEATHER_WEB_URL"
printf '%s\n' "$WEATHER_WEB_URL" >"$WEATHER_WORK/website-url.txt"

echo "Step 7/8: restoring the original update schedules."
weather_schedule() {
  local weather_name="$1" weather_cron="$2" weather_endpoint="$3" weather_action=create
  if gcloud scheduler jobs describe "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" >/dev/null 2>&1; then
    weather_action=update
  fi
  weather_retry gcloud scheduler jobs "$weather_action" http "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --schedule="$weather_cron" --time-zone=Etc/UTC --uri="$WEATHER_COLLECTOR_URL/collect/$weather_endpoint" --http-method=POST --oidc-service-account-email="$WEATHER_SCHEDULER_SA" --oidc-token-audience="$WEATHER_COLLECTOR_URL" --attempt-deadline=300s --max-retry-attempts=0 --quiet
  if [[ "$(gcloud scheduler jobs describe "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='value(state)')" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "$weather_name" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  fi
}
weather_schedule weather-live-radar '* * * * *' radar-KMPX
weather_schedule weather-live-satellite '*/5 * * * *' satellite
weather_schedule weather-live-forecast '*/5 * * * *' forecast
weather_schedule weather-live-metar-clouds '0 * * * *' metar-clouds

echo "Step 8/8: requesting fresh data and testing responses."
WEATHER_TOKEN="$(gcloud auth print-identity-token)"
WEATHER_FAILED=0
for WEATHER_ENDPOINT in forecast metar-clouds satellite radar-KMPX; do
  echo "Refreshing $WEATHER_ENDPOINT; this can take a few minutes."
  if WEATHER_HTTP="$(curl -sS --max-time 310 -o "$WEATHER_WORK/response-$WEATHER_ENDPOINT.txt" -w '%{http_code}' -X POST -H "Authorization: Bearer $WEATHER_TOKEN" "$WEATHER_COLLECTOR_URL/collect/$WEATHER_ENDPOINT")"; then
    printf '%s: HTTP %s\n' "$WEATHER_ENDPOINT" "$WEATHER_HTTP"
    cat "$WEATHER_WORK/response-$WEATHER_ENDPOINT.txt"
    printf '\n'
    if [[ "$WEATHER_HTTP" != "200" ]]; then WEATHER_FAILED=1; fi
  else
    WEATHER_FAILED=1
    echo "The direct request did not complete. Scheduled updates will continue." >&2
  fi
done
WEATHER_WEB_STATUS="$(curl -sS --max-time 90 -o "$WEATHER_WORK/website-response.html" -w '%{http_code}' "$WEATHER_WEB_URL" || true)"
printf 'Website HTTP status: %s\n' "$WEATHER_WEB_STATUS"
if [[ "$WEATHER_WEB_STATUS" != "200" ]]; then WEATHER_FAILED=1; fi
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name.basename():label=JOB,state,schedule,status.code:label=LAST_STATUS)'
for WEATHER_MANIFEST in forecast metar-clouds satellite-truecolor satellite-dcphase satellite-ntmicro radar-KMPX; do
  if gcloud storage cat "$WEATHER_BUCKET/live/$WEATHER_MANIFEST.json" >"$WEATHER_WORK/manifest-$WEATHER_MANIFEST.json"; then
    if ! python3 -c 'import json,sys; from datetime import datetime,timezone,timedelta; d=json.load(open(sys.argv[1])); stamp=d.get("checkedAt"); print(sys.argv[2]+": checkedAt="+str(stamp)); valid=bool(stamp) and abs(datetime.now(timezone.utc)-datetime.fromisoformat(stamp.replace("Z","+00:00")))<=timedelta(minutes=20); sys.exit(0 if valid else 1)' "$WEATHER_WORK/manifest-$WEATHER_MANIFEST.json" "$WEATHER_MANIFEST"; then
      WEATHER_FAILED=1
      echo "Fresh data is not yet confirmed for $WEATHER_MANIFEST." >&2
    fi
  else
    WEATHER_FAILED=1
  fi
done
printf '\nNEW PROJECT: %s\nSOURCE COMMIT: %s\nWEBSITE: %s\nRESUME FOLDER: %s\n' "$WEATHER_PROJECT" "$WEATHER_SOURCE_COMMIT" "$WEATHER_WEB_URL" "$WEATHER_WORK"
if [[ "$WEATHER_FAILED" != "0" ]]; then
  echo "Deployment completed, but a feed or website check needs attention. Send this final output to ChatGPT."
  exit 1
fi
echo "Website and all four direct feed requests returned HTTP 200. Automatic scheduled execution still needs verification."
echo "The old project's billing remains linked. Verify the new website before removing it."
