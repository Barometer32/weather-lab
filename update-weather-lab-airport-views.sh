#!/usr/bin/env bash
# Keep airport PLOTS/CLOUDS, remove the MADIS map and shorten wind barbs.
set -euo pipefail
WEATHER_PROJECT="${1:-$(gcloud config get-value project)}"
WEATHER_REGION=us-central1
case "$WEATHER_PROJECT" in weather-lab-*|j-weather-*) ;; *) echo 'Pass your active Weather Lab project ID.' >&2; exit 1;; esac
export CLOUDSDK_BILLING_QUOTA_PROJECT="$WEATHER_PROJECT"
WEATHER_WORK="$(mktemp -d "$HOME/weather-lab-airport-views.XXXXXX")"
trap 'echo "Map update stopped at line $LINENO. Saved settings: $WEATHER_WORK" >&2' ERR
printf 'Updating Weather Lab project: %s\n' "$WEATHER_PROJECT"
echo 'Step 1/4: saving the live services and schedules.'
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
    path=spec['containers'][0]['image'].split('@',1)[0].split(':',1)[0]
    if not path.startswith(f'us-central1-docker.pkg.dev/{project}/') or not path.endswith('/app'):
        raise SystemExit('Unexpected image registry; no build started.')
    if service=='weather-lab':(work/'image-path.txt').write_text(path)
    else:
        account=spec.get('serviceAccountName')
        bucket=next((v.get('value') for v in spec['containers'][0].get('env',[]) if v['name']=='WEATHER_DATA_BUCKET'),None)
        if account!=f'weather-collector@{project}.iam.gserviceaccount.com' or bucket!=f'{project}-weather-data':
            raise SystemExit('Unexpected collector account or bucket; no build started.')
        (work/'collector-account.txt').write_text(account);(work/'bucket.txt').write_text(bucket)
job=next((j for j in json.loads((work/'jobs-before.json').read_text()) if j['name'].rsplit('/',1)[-1]=='weather-live-madis-map'),None)
(work/'remove-madis.txt').write_text('yes' if job else 'no')
PY
git clone --quiet --depth=1 --branch metar-cloud-history-20261019 https://github.com/Barometer32/weather-lab.git "$WEATHER_WORK/source"
WEATHER_COMMIT="$(git -C "$WEATHER_WORK/source" rev-parse HEAD)"
WEATHER_IMAGE="$(cat "$WEATHER_WORK/image-path.txt"):airport-views-${WEATHER_COMMIT:0:12}"
echo 'Step 2/4: building PLOTS/CLOUDS with wind barbs shortened by 10%.'
gcloud builds submit "$WEATHER_WORK/source" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --tag="$WEATHER_IMAGE" --service-account="projects/$WEATHER_PROJECT/serviceAccounts/weather-builder@$WEATHER_PROJECT.iam.gserviceaccount.com" --default-buckets-behavior=regional-user-owned-bucket
echo 'Step 3/4: removing only the MADIS background schedule.'
if [[ "$(cat "$WEATHER_WORK/remove-madis.txt")" == yes ]]; then
  gcloud scheduler jobs delete weather-live-madis-map --project="$WEATHER_PROJECT" --location="$WEATHER_REGION" --quiet
fi
echo 'Step 4/4: deploying and verifying the airport views and other weather pages.'
for WEATHER_SERVICE in weather-collector weather-lab; do
  gcloud run services update "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --image="$WEATHER_IMAGE" --quiet
  gcloud run services update-traffic "$WEATHER_SERVICE" --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --to-latest --quiet
done
WEATHER_URL="$(gcloud run services describe weather-lab --project="$WEATHER_PROJECT" --region="$WEATHER_REGION" --format='value(status.url)')"
python3 "$WEATHER_WORK/source/verify_weather_site.py" "$WEATHER_URL"
printf '\nAirport views update complete: PLOTS and CLOUDS; no MADIS collection.\nWebsite: https://weather-lab.cloud.run\nDirect website: %s\nSaved settings: %s\n' "$WEATHER_URL" "$WEATHER_WORK"
