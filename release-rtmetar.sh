#!/usr/bin/env bash
# Run from the pushed rtmetar-default-20261111 checkout in Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
job=weather-live-rtmetar
tag="rtmetar-$(git rev-parse --short=12 HEAD)"
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
rollback_dir="$(mktemp -d /tmp/weather-rtmetar-rollback.XXXXXX)"
rollback="$rollback_dir/rollback.sh"
{
  echo '#!/usr/bin/env bash'
  printf 'gcloud run services update-traffic weather-lab --project=%q --region=%q --to-revisions=%q\n' "$project" "$region" "${web[2]}"
  printf 'gcloud run services update-traffic weather-collector --project=%q --region=%q --to-revisions=%q\n' "$project" "$region" "${collector[2]}"
  if [[ "$old_hourly_state" == ENABLED ]]; then
    printf 'gcloud scheduler jobs resume weather-live-hourly-observations --project=%q --location=%q\n' "$project" "$region"
  fi
  printf 'gcloud scheduler jobs pause %q --project=%q --location=%q\n' "$job" "$project" "$region"
} > "$rollback"
printf 'Rollback commands saved at %s\n' "$rollback"

image="$base:$tag"
gcloud builds submit . "${run[@]}" --tag="$image" \
  --service-account="projects/$project/serviceAccounts/weather-builder@$project.iam.gserviceaccount.com" \
  --default-buckets-behavior=regional-user-owned-bucket

stage() {
  gcloud run services update "$1" "${run[@]}" --image="$image" --no-traffic --tag="$tag" >&2
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
ready=false
for attempt in {1..18}; do
  if python3 verify_rtmetar_release.py "$candidate" > "$rollback_dir/verification.log" 2>&1; then
    cat "$rollback_dir/verification.log"
    ready=true
    break
  fi
  sleep 5
done
[[ "$ready" == true ]] || { cat "$rollback_dir/verification.log" >&2; echo 'No verified prepared RTMETAR snapshot arrived.' >&2; false; }
gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$web_revision=100"
python3 verify_rtmetar_release.py "$site"
if [[ "$old_hourly_state" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-hourly-observations "${scheduler[@]}"
fi
trap - ERR
echo "RTMETAR is live at $site. Five-minute raw reports use whole Celsius and mph; PLOTS and CLOUDS are retained."
