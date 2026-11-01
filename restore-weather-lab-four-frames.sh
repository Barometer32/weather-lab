#!/usr/bin/env bash
# Remove EXPMET and publish the five-tab site with four METAR frames.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass a Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-four-frames.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK. EXPMET is left stopped if already paused." >&2' ERR
echo "Step 1/4: saving service settings in $WEATHER_WORK"
gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/web-before.json"
gcloud run services describe weather-collector --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/collector-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]);project=sys.argv[2]
web=json.loads((p/'web-before.json').read_text());collector=json.loads((p/'collector-before.json').read_text())
image=web['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app'):raise SystemExit('Unexpected website registry')
env={v['name']:v.get('value') for v in collector['spec']['template']['spec']['containers'][0].get('env',[])}
bucket=env.get('WEATHER_DATA_BUCKET')
if not bucket or '/' in bucket or '\n' in bucket:raise SystemExit('Missing or invalid data bucket')
(p/'image-path').write_text(image);(p/'bucket').write_text(bucket)
PY
# A missing experimental schedule is fine; permission failures are not absence.
if gcloud scheduler jobs describe weather-live-expmet --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/expmet-job.json" 2>"$WEATHER_WORK/expmet-job.err"; then
  WEATHER_STATE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("state",""))' "$WEATHER_WORK/expmet-job.json")"
  if [[ "$WEATHER_STATE" == ENABLED ]]; then
    gcloud scheduler jobs pause weather-live-expmet --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
  fi
  gcloud scheduler jobs delete weather-live-expmet --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
elif ! grep -q NOT_FOUND "$WEATHER_WORK/expmet-job.err"; then
  cat "$WEATHER_WORK/expmet-job.err" >&2; exit 1
fi
if gcloud run jobs describe weather-expmet-seed --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/expmet-seed.json" 2>"$WEATHER_WORK/expmet-seed.err"; then
  # Deleting this job also terminates any of its running executions.
  gcloud run jobs delete weather-expmet-seed --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
elif ! grep -q NOT_FOUND "$WEATHER_WORK/expmet-seed.err"; then
  cat "$WEATHER_WORK/expmet-seed.err" >&2; exit 1
fi
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
python3 - "$WEATHER_WORK/source" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);html=(p/'static/index.html').read_text();script=(p/'static/metar-views.js').read_text()
if 'metar-four-frame-v1' not in html or 'const historyHours=4;' not in script or 'id="tab-expmet"' in html or (p/'expmet.py').exists():
    raise SystemExit('The four-frame source without EXPMET was not verified; no build started.')
PY
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):four-frames-${WEATHER_COMMIT:0:12}"
WEATHER_BUCKET="$(cat "$WEATHER_WORK/bucket")"
echo 'Step 2/4: building the standard site once.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/4: removing experimental routes from the collector and website.'
for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services update "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
  gcloud run services update-traffic "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
done
echo 'Step 4/4: verifying the standard pages and four-frame viewer.'
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK/page.html" <<'PY'
from pathlib import Path
import sys
html=Path(sys.argv[1]).read_text()
if 'metar-views.js?v=metar-four-frame-v1' not in html or 'id="tab-expmet"' in html:
    raise SystemExit('The expected four-frame viewer was not published.')
print('Verified: five standard tabs, current hour plus three previous hours.')
PY
if gcloud storage objects describe "gs://$WEATHER_BUCKET/live/expmet.json" --format=json >"$WEATHER_WORK/expmet-object.json" 2>"$WEATHER_WORK/expmet-object.err"; then
  gcloud storage rm "gs://$WEATHER_BUCKET/live/expmet.json"
elif ! grep -Eqi 'NOT_FOUND|not found|matched no objects|does not exist|404' "$WEATHER_WORK/expmet-object.err"; then
  cat "$WEATHER_WORK/expmet-object.err" >&2; exit 1
fi
printf '\nEXPMET removed. METAR displays four frames and requires a report in each frame.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
