#!/usr/bin/env bash
# Run from the pushed rtmetar-default-20261111 checkout in Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
job=weather-live-rtmetar
tag="metar-ready-$(git rev-parse --short=12 HEAD)"
run=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

# Read the actual services, image repository and Scheduler identity; retain
# runtime settings, IAM, existing data bucket, and all other weather schedules.
service_info() {
  gcloud run services describe "$1" "${run[@]}" --format=json |
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"]["url"]); print(d["spec"]["template"]["spec"]["containers"][0]["image"]); print(",".join(t["revisionName"]+"="+str(t["percent"]) for t in d["status"]["traffic"] if t.get("percent") and t.get("revisionName")))'
}
mapfile -t web < <(service_info weather-lab)
mapfile -t collector < <(service_info weather-collector)
[[ ${#web[@]} == 3 && ${#collector[@]} == 3 && -n "${web[2]}" && -n "${collector[2]}" ]] || { echo 'Could not identify active service traffic.' >&2; exit 1; }
base="${web[1]%%@*}"
base="${base%:*}"
case "$base" in
  "$region-docker.pkg.dev/$project/"*/app) ;;
  *) echo 'Unexpected Weather Lab image repository.' >&2; exit 1 ;;
esac
collector_base="${collector[1]%%@*}"
collector_base="${collector_base%:*}"
[[ "$collector_base" == "$base" ]] || { echo 'Web and collector image repositories differ; inspect before release.' >&2; exit 1; }
identity="$(gcloud scheduler jobs describe weather-live-metar-clouds "${scheduler[@]}" --format='value(httpTarget.oidcToken.serviceAccountEmail)')"
[[ "$identity" == *"@$project.iam.gserviceaccount.com" ]] || { echo 'Unexpected Scheduler identity.' >&2; exit 1; }
old_hourly_state="$(gcloud scheduler jobs describe weather-live-hourly-observations "${scheduler[@]}" --format='value(state)' 2>/dev/null || true)"
old_rt_state="$(gcloud scheduler jobs describe "$job" "${scheduler[@]}" --format='value(state)' 2>/dev/null || true)"
mapfile -t old_metar_job < <(gcloud scheduler jobs describe weather-live-metar-clouds "${scheduler[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["schedule"]); print(d.get("attemptDeadline","180s")); print(d["state"])')
[[ ${#old_metar_job[@]} == 3 ]] || { echo 'Could not save hourly collector configuration.' >&2; exit 1; }
old_min="$(gcloud run services describe weather-lab "${run[@]}" --format=json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("metadata",{}).get("annotations",{}).get("run.googleapis.com/minScale","default"))')"
warm_min=1
if [[ "$old_min" =~ ^[0-9]+$ ]] && (( old_min > 1 )); then warm_min="$old_min"; fi
rollback_dir="$(mktemp -d /tmp/weather-rtmetar-rollback.XXXXXX)"
rollback="$rollback_dir/rollback.sh"
{
  echo '#!/usr/bin/env bash'
  printf 'gcloud run services update-traffic weather-lab --project=%q --region=%q --to-revisions=%q\n' "$project" "$region" "${web[2]}"
  printf 'gcloud run services update-traffic weather-collector --project=%q --region=%q --to-revisions=%q\n' "$project" "$region" "${collector[2]}"
  if [[ "$old_hourly_state" == ENABLED ]]; then
    printf 'gcloud scheduler jobs resume weather-live-hourly-observations --project=%q --location=%q\n' "$project" "$region"
  fi
  rt_action=pause
  if [[ "$old_rt_state" == ENABLED ]]; then rt_action=resume; fi
  printf 'gcloud scheduler jobs %q %q --project=%q --location=%q\n' "$rt_action" "$job" "$project" "$region"
  printf 'gcloud scheduler jobs update http weather-live-metar-clouds --project=%q --location=%q --schedule=%q --attempt-deadline=%q\n' "$project" "$region" "${old_metar_job[0]}" "${old_metar_job[1]}"
  if [[ "${old_metar_job[2]}" == PAUSED ]]; then
    printf 'gcloud scheduler jobs pause weather-live-metar-clouds --project=%q --location=%q\n' "$project" "$region"
  fi
  printf 'gcloud run services update weather-lab --project=%q --region=%q --min=%q\n' "$project" "$region" "$old_min"
} > "$rollback"
printf 'Rollback commands saved at %s\n' "$rollback"

image="$base:$tag"
gcloud builds submit . "${run[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

stage() {
  local extra=()
  if [[ "$1" == weather-lab ]]; then extra=(--update-env-vars=WEATHER_PREPARED_ONLY=true); fi
  gcloud run services update "$1" "${run[@]}" --image="$image" --no-traffic --tag="$tag" "${extra[@]}" >&2
  gcloud run services describe "$1" "${run[@]}" --format=json |
    python3 -c 'import json,sys; t=next(t for t in json.load(sys.stdin)["status"]["traffic"] if t.get("tag")==sys.argv[1]); print(t["revisionName"],t["url"])' "$tag"
}
read -r web_revision candidate < <(stage weather-lab)
python3 verify_rtmetar_release.py "$candidate" --layout-only
read -r collector_revision _ < <(stage weather-collector)

# After the collector changes, automatically restore prior traffic if warming
# or verification fails. No weather objects or historic snapshots are deleted.
changed=false
on_failure() {
  code=$?
  if [[ "$changed" == true ]]; then bash "$rollback" || true; fi
  printf 'Release failed; inspect the error above. Rollback file: %s\n' "$rollback" >&2
  exit "$code"
}
trap on_failure ERR
changed=true
gcloud run services update-traffic weather-collector "${run[@]}" --to-revisions="$collector_revision=100"
action=create
if gcloud scheduler jobs describe "$job" "${scheduler[@]}" >/dev/null 2>&1; then action=update; fi
gcloud scheduler jobs "$action" http "$job" "${scheduler[@]}" \
  --schedule='*/5 * * * *' --time-zone=Etc/UTC \
  --uri="${collector[0]}/collect/rtmetar" --http-method=POST \
  --oidc-service-account-email="$identity" --oidc-token-audience="${collector[0]}" \
  --attempt-deadline=90s --max-retry-attempts=0
if [[ "$(gcloud scheduler jobs describe "$job" "${scheduler[@]}" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume "$job" "${scheduler[@]}"
fi
gcloud scheduler jobs run "$job" "${scheduler[@]}"
# Check every five minutes, but the collector skips source requests once the
# complete current-hour loop is ready. Recovery can continue outside :00/:10.
gcloud scheduler jobs update http weather-live-metar-clouds "${scheduler[@]}" \
  --schedule='*/5 * * * *' --attempt-deadline=300s
if [[ "$(gcloud scheduler jobs describe weather-live-metar-clouds "${scheduler[@]}" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-metar-clouds "${scheduler[@]}"
fi
gcloud scheduler jobs run weather-live-metar-clouds "${scheduler[@]}"
ready=false
for attempt in {1..72}; do
  if python3 verify_rtmetar_release.py "$candidate" --all-products > "$rollback_dir/verification.log" 2>&1; then
    cat "$rollback_dir/verification.log"
    ready=true
    break
  fi
  sleep 5
done
[[ "$ready" == true ]] || { cat "$rollback_dir/verification.log" >&2; echo 'Verified prepared RTMETAR and hourly map data did not arrive.' >&2; false; }
gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$web_revision=100"
gcloud run services update weather-lab "${run[@]}" --min="$warm_min"
python3 verify_rtmetar_release.py "$site" --all-products
if [[ "$old_hourly_state" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-hourly-observations "${scheduler[@]}"
fi
trap - ERR
echo "Weather Lab is live at $site. CLOUDS/PLOTS and RTMETAR are prepared in the background; the website keeps at least one instance warm."
