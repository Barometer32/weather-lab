#!/usr/bin/env bash
# Run from this pushed checkout in authenticated Google Cloud Shell.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
project=weather-lab-261105-184200-1a9b
region=us-central1
site=https://weather-lab.cloud.run
job=weather-live-rtmetar
tag="plots-ready-$(git rev-parse --short=12 HEAD)"
run=(--project="$project" --region="$region")
scheduler=(--project="$project" --location="$region")
export CLOUDSDK_BILLING_QUOTA_PROJECT="$project"
[[ -z "$(git status --porcelain)" ]] || { echo 'Run from a clean checkout.' >&2; exit 1; }

# Read actual services and image repository; retain runtime settings, IAM,
# existing data bucket and the schedules of the other retained products.
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
old_hourly_state="$(gcloud scheduler jobs describe weather-live-hourly-observations "${scheduler[@]}" --format='value(state)' 2>/dev/null || true)"
old_rt_state="$(gcloud scheduler jobs describe "$job" "${scheduler[@]}" --format='value(state)' 2>/dev/null || true)"
mapfile -t old_metar_job < <(gcloud scheduler jobs describe weather-live-metar-clouds "${scheduler[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["schedule"]); print(d.get("attemptDeadline","180s")); print(d["state"])')
[[ ${#old_metar_job[@]} == 3 ]] || { echo 'Could not save hourly collector configuration.' >&2; exit 1; }
old_forecast_schedule="$(gcloud scheduler jobs describe weather-live-forecast "${scheduler[@]}" --format='value(schedule)')"
[[ -n "$old_forecast_schedule" ]] || { echo 'Could not save forecast schedule.' >&2; exit 1; }
old_min="$(gcloud run services describe weather-lab "${run[@]}" --format=json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("metadata",{}).get("annotations",{}).get("run.googleapis.com/minScale","default"))')"
warm_min=1
if [[ "$old_min" =~ ^[0-9]+$ ]] && (( old_min > 1 )); then warm_min="$old_min"; fi
rollback_dir="$(mktemp -d /tmp/weather-plots-rollback.XXXXXX)"
rollback="$rollback_dir/rollback.sh"
{
  echo '#!/usr/bin/env bash'
  printf 'gcloud run services update-traffic weather-lab --project=%q --region=%q --to-revisions=%q\n' "$project" "$region" "${web[2]}"
  printf 'gcloud run services update-traffic weather-collector --project=%q --region=%q --to-revisions=%q\n' "$project" "$region" "${collector[2]}"
  if [[ "$old_hourly_state" == ENABLED ]]; then
    printf 'gcloud scheduler jobs resume weather-live-hourly-observations --project=%q --location=%q\n' "$project" "$region"
  fi
  if [[ "$old_rt_state" == ENABLED ]]; then
    printf 'gcloud scheduler jobs resume %q --project=%q --location=%q\n' "$job" "$project" "$region"
  fi
  printf 'gcloud scheduler jobs update http weather-live-metar-clouds --project=%q --location=%q --schedule=%q --attempt-deadline=%q\n' "$project" "$region" "${old_metar_job[0]}" "${old_metar_job[1]}"
  printf 'gcloud scheduler jobs update http weather-live-forecast --project=%q --location=%q --schedule=%q\n' "$project" "$region" "$old_forecast_schedule"
  if [[ "${old_metar_job[2]}" == PAUSED ]]; then
    printf 'gcloud scheduler jobs pause weather-live-metar-clouds --project=%q --location=%q\n' "$project" "$region"
  fi
  printf 'gcloud run services update weather-lab --project=%q --region=%q --min=%q\n' "$project" "$region" "$old_min"
} > "$rollback"
retained_jobs=(weather-live-radar weather-live-satellite weather-live-forecast weather-live-air-quality)
for active_job in "${retained_jobs[@]}"; do
  state="$(gcloud scheduler jobs describe "$active_job" "${scheduler[@]}" --format='value(state)')"
  case "$state" in
    ENABLED) ;;
    PAUSED) printf 'gcloud scheduler jobs pause %q --project=%q --location=%q\n' "$active_job" "$project" "$region" >> "$rollback" ;;
    *) echo "Unexpected background job state: $active_job $state" >&2; exit 1 ;;
  esac
done
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
python3 verify_weather_release.py "$candidate" --layout-only
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
if [[ "$old_rt_state" == ENABLED ]]; then
  gcloud scheduler jobs pause "$job" "${scheduler[@]}"
fi
gcloud run services update-traffic weather-collector "${run[@]}" --to-revisions="$collector_revision=100"
# Check at :00, :02 and every two minutes, using the fast official bulk file
# when saved history is healthy. Recovery still fills gaps from the archive.
gcloud scheduler jobs update http weather-live-metar-clouds "${scheduler[@]}" \
  --schedule='*/2 * * * *' --attempt-deadline=300s
if [[ "$(gcloud scheduler jobs describe weather-live-metar-clouds "${scheduler[@]}" --format='value(state)')" == PAUSED ]]; then
  gcloud scheduler jobs resume weather-live-metar-clouds "${scheduler[@]}"
fi
gcloud scheduler jobs run weather-live-metar-clouds "${scheduler[@]}"
# NWS can issue a new forecast between the old :00/:30 checks. Use the same
# Hopkins MapClick feed every five minutes, without changing its wording.
gcloud scheduler jobs update http weather-live-forecast "${scheduler[@]}" --schedule='*/5 * * * *'
for active_job in "${retained_jobs[@]}"; do
  if [[ "$(gcloud scheduler jobs describe "$active_job" "${scheduler[@]}" --format='value(state)')" == PAUSED ]]; then
    gcloud scheduler jobs resume "$active_job" "${scheduler[@]}"
  fi
  gcloud scheduler jobs run "$active_job" "${scheduler[@]}"
done
ready=false
for attempt in {1..72}; do
  if python3 verify_weather_release.py "$candidate" --all-products > "$rollback_dir/verification.log" 2>&1; then
    cat "$rollback_dir/verification.log"
    ready=true
    break
  fi
  sleep 5
done
[[ "$ready" == true ]] || { cat "$rollback_dir/verification.log" >&2; echo 'Verified prepared weather data did not arrive.' >&2; false; }
gcloud run services update-traffic weather-lab "${run[@]}" --to-revisions="$web_revision=100"
gcloud run services update weather-lab "${run[@]}" --min="$warm_min"
gcloud run services describe weather-lab "${run[@]}" --format=json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); minimum=int(d.get("metadata",{}).get("annotations",{}).get("run.googleapis.com/minScale",0)); assert minimum>=1,"Website has no warm minimum instance"; env=d["spec"]["template"]["spec"]["containers"][0].get("env",[]); assert any(e["name"]=="WEATHER_PREPARED_ONLY" and e.get("value")=="true" for e in env),"Public service is not prepared-only"; print("Verified website warm minimum:",minimum,"instance(s), covering all tabs; prepared-only enabled.")'
python3 verify_weather_release.py "$site" --all-products
if [[ "$old_hourly_state" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-hourly-observations "${scheduler[@]}"
fi
# Retire the job and its one unused snapshot only after the replacement passes
# all checks. Until this point the prior service/job remain recoverable.
trap - ERR
trap 'echo "Website deployment passed, but post-deployment cleanup is incomplete. Inspect the error above." >&2' ERR
if [[ -n "$old_rt_state" ]]; then
  gcloud scheduler jobs delete "$job" "${scheduler[@]}" --quiet
fi
bucket="$(gcloud run services describe weather-collector "${run[@]}" --format=json |
  python3 -c 'import json,sys; env=json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env",[]); print(next(e["value"] for e in env if e["name"]=="WEATHER_DATA_BUCKET"))')"
[[ "$bucket" =~ ^[a-z0-9][a-z0-9._-]+$ ]] || { echo 'Invalid data bucket; inspect before cleanup.' >&2; exit 1; }
# Extend retention only for the new image prefix; preserve all existing rules.
gcloud storage buckets describe "gs://$bucket" --raw --format=json > "$rollback_dir/bucket-before.json"
python3 extend_satellite_lifecycle.py "$bucket" < "$rollback_dir/bucket-before.json" > "$rollback_dir/satellite-lifecycle.json"
gcloud storage buckets update "gs://$bucket" --lifecycle-file="$rollback_dir/satellite-lifecycle.json"
rt_object="gs://$bucket/live/rtmetar-v1.json"
gcloud storage ls "gs://$bucket/live/" > "$rollback_dir/live-objects.txt"
while IFS= read -r object; do
  if [[ "$object" == "$rt_object" ]]; then
    gcloud storage rm "$rt_object"
  fi
done < "$rollback_dir/live-objects.txt"
gcloud scheduler jobs list "${scheduler[@]}" --format=json |
  python3 -c 'import json,sys; jobs={j["name"].split("/")[-1]:j for j in json.load(sys.stdin)}; assert "weather-live-rtmetar" not in jobs,"Retired RTMETAR scheduler still exists"; names=["weather-live-metar-clouds","weather-live-radar","weather-live-satellite","weather-live-forecast","weather-live-air-quality"]; [print("Verified background job:",name,jobs[name]["state"],jobs[name]["schedule"]) for name in names if jobs[name]["state"]=="ENABLED"]; assert all(jobs[name]["state"]=="ENABLED" for name in names),"A weather collection job is paused"; assert " ".join(jobs["weather-live-forecast"]["schedule"].split())=="*/5 * * * *","Forecast must check NWS every five minutes"; assert " ".join(jobs["weather-live-metar-clouds"]["schedule"].split())=="*/2 * * * *","METAR must check every two minutes starting at :00"'
trap - ERR
echo "Weather Lab is live at $site. PLOTS is the default; RTMETAR is removed. All retained tabs use background-prepared data and share the warm website instance."
