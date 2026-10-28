#!/usr/bin/env bash
# Build one new project, verify it, then move the user's existing custom URL.
set -euo pipefail
WEATHER_OLD_PROJECT="${1:-weather-lab-261027-024631-5ff2}"
WEATHER_REGION=us-central1
WEATHER_DOMAIN=weather-lab.cloud.run
WEATHER_SITE_COMMIT=4e8df6fa9e6e20efbe0614f86dce12109964bb98
WEATHER_WORK="${WEATHER_FRESH_WORK_DIR:-$HOME/weather-lab-fresh-$WEATHER_OLD_PROJECT}"
mkdir -p "$WEATHER_WORK"
trap 'echo "Migration stopped at line $LINENO. Rerun the same command to resume the same project. Settings: $WEATHER_WORK" >&2' ERR

if [[ -s "$WEATHER_WORK/old-project.txt" ]]; then
  [[ "$(cat "$WEATHER_WORK/old-project.txt")" == "$WEATHER_OLD_PROJECT" ]] || { echo 'This resume folder belongs to another source project.' >&2; exit 1; }
else
  printf '%s\n' "$WEATHER_OLD_PROJECT" >"$WEATHER_WORK/old-project.txt"
fi

if [[ -s "$WEATHER_WORK/site-commit.txt" ]]; then
  [[ "$(cat "$WEATHER_WORK/site-commit.txt")" == "$WEATHER_SITE_COMMIT" ]] || { echo 'This resume folder belongs to a different website version; stopping.' >&2; exit 1; }
else
  printf '%s\n' "$WEATHER_SITE_COMMIT" >"$WEATHER_WORK/site-commit.txt"
fi

echo 'Step 1/6: checking billing and fetching the recovery tools.'
if [[ ! -s "$WEATHER_WORK/billing-account.txt" ]]; then
  WEATHER_BILLING="${2:-}"
  if [[ -z "$WEATHER_BILLING" ]]; then
    WEATHER_BILLING="$(gcloud billing projects describe "$WEATHER_OLD_PROJECT" --format='value(billingAccountName)')"
    WEATHER_BILLING="${WEATHER_BILLING##*/}"
  fi
  if [[ -z "$WEATHER_BILLING" ]]; then
    gcloud billing accounts list --filter='open=true' --format=json >"$WEATHER_WORK/open-billing.json"
    WEATHER_BILLING="$(python3 - "$WEATHER_WORK/open-billing.json" <<'PY'
import json,sys
accounts=json.load(open(sys.argv[1]))
if len(accounts)==1:print(accounts[0]['name'].rsplit('/',1)[-1])
PY
)"
  fi
  [[ -n "$WEATHER_BILLING" ]] || { echo 'Choose an open billing account and pass its ID as argument two. See https://console.cloud.google.com/billing' >&2; exit 1; }
  printf '%s\n' "$WEATHER_BILLING" >"$WEATHER_WORK/billing-account.txt"
fi
WEATHER_BILLING="$(cat "$WEATHER_WORK/billing-account.txt")"
WEATHER_OPEN="$(gcloud billing accounts describe "$WEATHER_BILLING" --format='value(open)')"
[[ "${WEATHER_OPEN,,}" == true ]] || { echo 'Reopen the saved billing account before retrying.' >&2; exit 1; }
if [[ ! -d "$WEATHER_WORK/tools/.git" ]]; then
  git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/tools"
fi
# Recovery tools and application both use the same verified working snapshot.
git -C "$WEATHER_WORK/tools" fetch --quiet --depth=1 origin "$WEATHER_SITE_COMMIT"
git -C "$WEATHER_WORK/tools" checkout --quiet --detach "$WEATHER_SITE_COMMIT"
[[ "$(git -C "$WEATHER_WORK/tools" rev-parse HEAD)" == "$WEATHER_SITE_COMMIT" ]] || { echo 'Could not verify the saved website source; stopping.' >&2; exit 1; }
test -f "$WEATHER_WORK/tools/verify_weather_site.py"
test -f "$WEATHER_WORK/tools/restore-weather-lab-latest.sh"

echo 'Step 2/6: creating or resuming one fresh project named Weather Lab.'
if [[ ! -s "$WEATHER_WORK/project-id.txt" ]]; then
  WEATHER_SUFFIX="$(python3 -c 'import secrets; print(secrets.token_hex(2))')"
  printf 'weather-lab-%s-%s\n' "$(date -u +%y%m%d-%H%M%S)" "$WEATHER_SUFFIX" >"$WEATHER_WORK/project-id.txt"
fi
WEATHER_PROJECT="$(cat "$WEATHER_WORK/project-id.txt")"
[[ "$WEATHER_PROJECT" =~ ^weather-lab-[0-9]{6}-[0-9]{6}-[a-f0-9]{4}$ && "$WEATHER_PROJECT" != "$WEATHER_OLD_PROJECT" ]] || { echo 'Unexpected saved project ID; stopping.' >&2; exit 1; }
echo "NEW PROJECT: $WEATHER_PROJECT"
if [[ ! -f "$WEATHER_WORK/project-created" ]]; then
  if gcloud projects create "$WEATHER_PROJECT" --name='Weather Lab' 2>"$WEATHER_WORK/create-project.err"; then
    touch "$WEATHER_WORK/project-created"
  elif grep -q ALREADY_EXISTS "$WEATHER_WORK/create-project.err"; then
    gcloud projects describe "$WEATHER_PROJECT" --format='value(projectId)'
    touch "$WEATHER_WORK/project-created"
  else
    cat "$WEATHER_WORK/create-project.err" >&2
    exit 1
  fi
fi
[[ "$(gcloud projects describe "$WEATHER_PROJECT" --format='value(lifecycleState)')" == ACTIVE ]] || { echo 'The saved new project is not ACTIVE. No replacement was created.' >&2; exit 1; }
gcloud billing projects link "$WEATHER_PROJECT" --billing-account="$WEATHER_BILLING"
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
gcloud config set project "$WEATHER_PROJECT"
bash "$WEATHER_WORK/tools/ensure-weather-apis.sh" "$WEATHER_PROJECT"

echo 'Step 3/6: copying the dedicated weather data bucket when it is available.'
if [[ ! -f "$WEATHER_WORK/data-copied" ]]; then
  gcloud storage buckets list --project="$WEATHER_OLD_PROJECT" --format=json >"$WEATHER_WORK/old-buckets.json"
  WEATHER_HAS_DATA="$(python3 - "$WEATHER_WORK/old-buckets.json" "$WEATHER_OLD_PROJECT-weather-data" <<'PY'
import json,sys
print('true' if any(b.get('name','').removeprefix('gs://').rstrip('/')==sys.argv[2] for b in json.load(open(sys.argv[1]))) else 'false')
PY
)"
  if [[ "$WEATHER_HAS_DATA" == true ]]; then
    if [[ ! -f "$WEATHER_WORK/bucket-created" ]]; then
      # A failed bucket read is not interpreted as a missing bucket.
      gcloud storage buckets list --project="$WEATHER_PROJECT" --format=json >"$WEATHER_WORK/new-buckets.json"
      WEATHER_HAS_BUCKET="$(python3 - "$WEATHER_WORK/new-buckets.json" "$WEATHER_PROJECT-weather-data" <<'PY'
import json,sys
print('true' if any(b.get('name','').removeprefix('gs://').rstrip('/')==sys.argv[2] for b in json.load(open(sys.argv[1]))) else 'false')
PY
)"
      if [[ "$WEATHER_HAS_BUCKET" != true ]]; then
        gcloud storage buckets create "gs://$WEATHER_PROJECT-weather-data" --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --uniform-bucket-level-access
      fi
      touch "$WEATHER_WORK/bucket-created"
    fi
    gcloud storage rsync --recursive "gs://$WEATHER_OLD_PROJECT-weather-data" "gs://$WEATHER_PROJECT-weather-data"
  else
    echo 'No saved data bucket was found; the source feeds will rebuild available history.'
  fi
  touch "$WEATHER_WORK/data-copied"
fi

echo 'Step 4/6: building fresh containers and restoring the saved five-tab site.'
if [[ ! -f "$WEATHER_WORK/site-restored" ]]; then
  WEATHER_RESTORE_SOURCE_COMMIT="$WEATHER_SITE_COMMIT" WEATHER_SKIP_DOMAIN_SETUP=true \
    bash "$WEATHER_WORK/tools/restore-weather-lab-latest.sh" "$WEATHER_PROJECT"
  touch "$WEATHER_WORK/site-restored"
fi
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
[[ "$WEATHER_URL" == https://*.run.app ]] || { echo 'A direct website URL was not returned.' >&2; exit 1; }
printf '%s\n' "$WEATHER_URL" >"$WEATHER_WORK/website-url.txt"
echo "Direct website: $WEATHER_URL"
WEATHER_COLLECTOR="$(gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
[[ "$WEATHER_COLLECTOR" == https://*.run.app ]] || exit 1
curl -fsS --max-time 300 -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$WEATHER_COLLECTOR/collect/forecast" -o "$WEATHER_WORK/collector-check.json"
python3 "$WEATHER_WORK/tools/verify_weather_site.py" "$WEATHER_URL"

echo 'Step 5/6: moving weather-lab.cloud.run after the new site passes its checks.'
gcloud beta run domain-mappings list --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/new-mappings.json"
WEATHER_NEW_ROUTE="$(python3 - "$WEATHER_WORK/new-mappings.json" "$WEATHER_DOMAIN" <<'PY'
import json,sys
for mapping in json.load(open(sys.argv[1])):
    if mapping.get('metadata',{}).get('name')==sys.argv[2]:print(mapping.get('spec',{}).get('routeName','UNKNOWN'))
PY
)"
if [[ -n "$WEATHER_NEW_ROUTE" && "$WEATHER_NEW_ROUTE" != weather-lab ]]; then
  echo 'The address maps to an unexpected service in the new project; stopping.' >&2
  exit 1
fi
if [[ -z "$WEATHER_NEW_ROUTE" ]]; then
  # Never interpret an IAM/read failure as an absent mapping.
  gcloud beta run domain-mappings list --project="$WEATHER_OLD_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/old-mappings.json"
  WEATHER_OLD_ROUTE="$(python3 - "$WEATHER_WORK/old-mappings.json" "$WEATHER_DOMAIN" <<'PY'
import json,sys
for mapping in json.load(open(sys.argv[1])):
    if mapping.get('metadata',{}).get('name')==sys.argv[2]:print(mapping.get('spec',{}).get('routeName','UNKNOWN'))
PY
)"
  [[ -z "$WEATHER_OLD_ROUTE" || "$WEATHER_OLD_ROUTE" == weather-lab ]] || { echo 'The old address maps to an unexpected service; stopping.' >&2; exit 1; }
  WEATHER_RELEASED=false
  if [[ "$WEATHER_OLD_ROUTE" == weather-lab ]]; then
    gcloud beta run domain-mappings delete --domain="$WEATHER_DOMAIN" --project="$WEATHER_OLD_PROJECT" --region="$WEATHER_REGION" --quiet
    WEATHER_RELEASED=true
  fi
  if ! gcloud beta run domain-mappings create --service=weather-lab --domain="$WEATHER_DOMAIN" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet >"$WEATHER_WORK/domain-create.txt" 2>"$WEATHER_WORK/domain-create.err"; then
    cat "$WEATHER_WORK/domain-create.err" >&2
    if [[ "$WEATHER_RELEASED" == true ]]; then
      echo 'Trying to restore the previous address mapping.' >&2
      if ! gcloud beta run domain-mappings create --service=weather-lab --domain="$WEATHER_DOMAIN" --project="$WEATHER_OLD_PROJECT" --region="$WEATHER_REGION" --quiet; then
        echo 'The previous mapping could not be reclaimed. The new direct website remains available.' >&2
      fi
    fi
    echo "Custom address transfer failed. Direct website: $WEATHER_URL" >&2
    exit 1
  fi
fi
WEATHER_DOMAIN_READY=false
for WEATHER_ATTEMPT in 1 2 3 4 5 6; do
  gcloud beta run domain-mappings describe --domain="$WEATHER_DOMAIN" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/domain-status.json"
  WEATHER_DOMAIN_READY="$(python3 - "$WEATHER_WORK/domain-status.json" <<'PY'
import json,sys
data=json.load(open(sys.argv[1]))
ready=any(c.get('type')=='Ready' and str(c.get('status')).lower()=='true' for c in data.get('status',{}).get('conditions',[]))
print('true' if ready and data.get('spec',{}).get('routeName')=='weather-lab' else 'false')
PY
)"
  if [[ "$WEATHER_DOMAIN_READY" == true ]]; then break; fi
  if [[ "$WEATHER_ATTEMPT" != 6 ]]; then sleep 5; fi
done
[[ "$WEATHER_DOMAIN_READY" == true ]] || { echo "Address routing is still pending. Direct website: $WEATHER_URL. Rerun to finish; old billing remains linked." >&2; exit 1; }
curl -fsS --max-time 90 --retry 3 --retry-delay 5 "https://$WEATHER_DOMAIN/" -o "$WEATHER_WORK/custom-page.html"

echo 'Step 6/6: disabling billing on the old project after successful cutover.'
gcloud billing projects unlink "$WEATHER_OLD_PROJECT" --quiet
gcloud billing projects describe "$WEATHER_OLD_PROJECT" --format='yaml(projectId,billingEnabled)'
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='table(name,schedule,state)'
printf '\nFresh Weather Lab migration complete.\nWebsite: https://%s\nDirect website: %s\nNew project: %s\nResume folder: %s\n' "$WEATHER_DOMAIN" "$WEATHER_URL" "$WEATHER_PROJECT" "$WEATHER_WORK"
