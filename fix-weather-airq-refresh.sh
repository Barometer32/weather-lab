#!/usr/bin/env bash
# Correct AIR Q refresh behavior without changing collection schedules.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-airq-refresh.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
echo 'Step 1/3: saving the website settings.'
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/web-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1]);project=sys.argv[2]
image=json.loads((work/'web-before.json').read_text())['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app'):raise SystemExit('Unexpected website image registry.')
(work/'image-path').write_text(image)
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):airq-refresh-${WEATHER_COMMIT:0:12}"
echo 'Step 2/3: building and publishing the AIR Q refresh fix.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
gcloud run services update weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
gcloud run services update-traffic weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
echo 'Step 3/3: verifying the new AIR Q viewer and existing weather tabs.'
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 --dump-header "$WEATHER_WORK/headers.txt" "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/static/air-quality-views.js?v=airq-freshness-v2" -o "$WEATHER_WORK/air-quality-views.js"
python3 - "$WEATHER_WORK" <<'PY'
from pathlib import Path
import re,sys
work=Path(sys.argv[1]);html=(work/'page.html').read_text();headers=(work/'headers.txt').read_text().lower()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['metar','radar','satellite','forecast','air-quality']:raise SystemExit('The five weather tabs were not verified.')
if 'id="radar-location"' in html or 'radar-location.js' in html:raise SystemExit('The location control is still referenced.')
if 'permissions-policy: geolocation=()' not in headers:raise SystemExit('The location-blocking policy was not verified.')
if '/static/air-quality-views.js?v=airq-freshness-v2' not in html:raise SystemExit('The new AIR Q viewer is not referenced.')
if (work/'air-quality-views.js').read_bytes()!=(work/'source/static/air-quality-views.js').read_bytes():raise SystemExit('The expected AIR Q script was not served.')
print('Verified: updated AIR Q refresh, five weather tabs, and device location disabled site-wide.')
PY
echo 'Current AIR Q collection schedule (unchanged):'
gcloud scheduler jobs describe weather-live-air-quality --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format='yaml(schedule,state,lastAttemptTime,status)' || echo 'Could not read schedule diagnostics; the website update is complete.'
printf '\nOpen https://weather-lab.cloud.run and refresh on each device.\nSaved settings: %s\n' "$WEATHER_WORK"
