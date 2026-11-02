#!/usr/bin/env bash
# Retire Infrared from both services and remove only its cached imagery.
set -euo pipefail
WEATHER_PROJECT="${1:-weather-lab-261028-205713-506d}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-no-infrared.XXXXXX")"
trap 'echo "Update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
echo 'Step 1/4: saving the website and collector settings.'
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_SERVICE-before.json"
done
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1]);project=sys.argv[2]
image=json.loads((work/'weather-lab-before.json').read_text())['spec']['template']['spec']['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
if not image.startswith(f'us-central1-docker.pkg.dev/{project}/') or not image.endswith('/app'):raise SystemExit('Unexpected website image registry.')
collector=json.loads((work/'weather-collector-before.json').read_text())['spec']['template']['spec']
env={v['name']:v.get('value') for v in collector['containers'][0].get('env',[])}
bucket=env.get('WEATHER_DATA_BUCKET');account=collector.get('serviceAccountName')
if not bucket or '/' in bucket or '\n' in bucket or not account or not account.endswith('.iam.gserviceaccount.com'):raise SystemExit('Missing bucket or collector identity.')
(work/'image-path').write_text(image)
(work/'bucket').write_text(bucket)
(work/'collector-account').write_text(account)
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
if [[ -n "${WEATHER_SOURCE_COMMIT:-}" ]]; then
  [[ "$WEATHER_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid source commit.' >&2; exit 1; }
  git -C "$WEATHER_WORK/source" fetch --quiet --depth=1 origin "$WEATHER_SOURCE_COMMIT"
  git -C "$WEATHER_WORK/source" checkout --quiet --detach "$WEATHER_SOURCE_COMMIT"
fi
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path"):no-infrared-${WEATHER_COMMIT:0:12}"
echo 'Step 2/4: building the website and collector without Infrared.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/4: updating both services and removing retired Infrared images.'
for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services update "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
  gcloud run services update-traffic "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
done
WEATHER_JOB="weather-ir-cleanup-$(date -u +%y%m%d-%H%M%S)-${WEATHER_WORK##*.}"
WEATHER_JOB="${WEATHER_JOB,,}"
gcloud run jobs deploy "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --service-account="$(cat "$WEATHER_WORK/collector-account")" --set-env-vars="WEATHER_DATA_BUCKET=$(cat "$WEATHER_WORK/bucket")" --command=python --args='-u,remove_infrared_data.py' --tasks=1 --parallelism=1 --cpu=1 --memory=512Mi --max-retries=0 --task-timeout=300s --quiet
gcloud run jobs execute "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --wait --quiet
gcloud run jobs delete "$WEATHER_JOB" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --quiet
echo 'Step 4/4: verifying the three satellite products and the other pages.'
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
curl --compressed --retry 3 --retry-delay 3 -fsS --max-time 90 --dump-header "$WEATHER_WORK/headers.txt" "$WEATHER_URL/" -o "$WEATHER_WORK/page.html"
python3 - "$WEATHER_WORK" "$WEATHER_URL" <<'PY'
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
import re,sys
work=Path(sys.argv[1]);html=(work/'page.html').read_text()
if re.findall(r'<button role="tab" id="tab-([^"]+)"',html)!=['metar','radar','satellite','forecast','air-quality']:raise SystemExit('The five weather tabs were not verified.')
options=re.search(r'<select id="satellite-product">(.*?)</select>',html).group(1)
if re.findall(r'value="([^"]+)"',options)!=['truecolor','dcphase','ntmicro']:raise SystemExit('Expected three satellite products.')
if 'permissions-policy: geolocation=()' not in (work/'headers.txt').read_text().lower():raise SystemExit('Location-blocking policy was not verified.')
try:
    with urlopen(sys.argv[2]+'/api/satellite/13',timeout=30):raise SystemExit('Infrared API is still enabled.')
except HTTPError as error:
    if error.code!=404:raise
print('Verified: Infrared removed, three satellite products ready, five tabs retained, and device location disabled.')
PY
printf '\nOpen https://weather-lab.cloud.run and refresh on each device.\nExisting collection schedules were preserved.\nSaved settings: %s\n' "$WEATHER_WORK"
