#!/usr/bin/env bash
# Restore the pre-CURRENT version and stop only its five-minute collector.
set -euo pipefail
WEATHER_PROJECT="${1:-$(gcloud config get-value project)}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your active Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-remove-current.XXXXXX")"
trap 'echo "Removal stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
printf 'Updating Weather Lab project: %s\n' "$WEATHER_PROJECT"
echo 'Step 1/4: saving service settings and stopping the Current collection job.'
for WEATHER_SERVICE in weather-lab weather-collector; do
  gcloud run services describe "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format=json >"$WEATHER_WORK/$WEATHER_SERVICE-before.json"
done
gcloud scheduler jobs list --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --format=json >"$WEATHER_WORK/jobs-before.json"
python3 - "$WEATHER_WORK" "$WEATHER_PROJECT" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1]);project=sys.argv[2]
for service in ('weather-lab','weather-collector'):
    spec=json.loads((work/f'{service}-before.json').read_text())['spec']['template']['spec']
    image=spec['containers'][0]['image'];path=image.split('@',1)[0].split(':',1)[0]
    if not path.startswith(f'us-central1-docker.pkg.dev/{project}/') or not path.endswith('/app'):
        raise SystemExit('Unexpected image registry; no deployment started.')
    if service=='weather-lab':(work/'image-path.txt').write_text(path)
jobs=json.loads((work/'jobs-before.json').read_text())
current=next((j for j in jobs if j['name'].rsplit('/',1)[-1]=='weather-live-hennepin-current'),None)
(work/'current-exists.txt').write_text('yes' if current else 'no')
(work/'current-state.txt').write_text(current.get('state','') if current else '')
PY
if [[ "$(cat "$WEATHER_WORK/current-exists.txt")" == yes && "$(cat "$WEATHER_WORK/current-state.txt")" == ENABLED ]]; then
  gcloud scheduler jobs pause weather-live-hennepin-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION"
fi
# Pin the saved version from immediately before CURRENT was added.
git clone --quiet --no-checkout https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
git -C "$WEATHER_WORK/source" checkout --quiet d5169658cf5352604bfbc80c49a184ab2c70a445
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path.txt"):without-current-d5169658cf53"
echo 'Step 2/4: building the saved METAR-first version.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/4: publishing the original collector and website.'
for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services update "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
  gcloud run services update-traffic "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
done
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
echo 'Step 4/4: verifying the five original weather tabs and removing the retired job.'
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
if [[ "$(cat "$WEATHER_WORK/current-exists.txt")" == yes ]]; then
  gcloud scheduler jobs delete weather-live-hennepin-current --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
fi
printf '\nCURRENT removed. METAR is the opening tab again.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nProject: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_PROJECT" "$WEATHER_WORK"
