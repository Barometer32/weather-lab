# WEATHER LAB deployment

Run in authenticated Google Cloud Shell with billing linked to `weather-lab-511113`. A fresh checkout preserves older local changes:

```bash
WEATHER_LAB_DIR="$(mktemp -d "$HOME/weather-lab-update.XXXXXX")"
git clone https://github.com/Barometer32/weather-lab.git "$WEATHER_LAB_DIR"
cd "$WEATHER_LAB_DIR"
bash deploy.sh weather-lab-511113
```

Saving code to GitHub does not deploy Google Cloud. The script builds the image, updates both services, resumes its paused jobs and triggers initial collection. Allow a few minutes for first imagery backfill and Surface collection. The public URL is printed at the end. An empty Surface store builds twelve hourly history positions over time; missing slots stay empty.

## Managed resources

All services/jobs use `us-central1`:

| Resource | Settings |
| --- | --- |
| `weather-lab` | Public Cloud Run, 1 CPU / 1 GiB, request-based billing, minimum 0 / maximum 1 instance |
| `weather-collector` | Private Cloud Run, 1 CPU / **2 GiB**, minimum 0 / maximum 1 instance; large MADIS temporary files use RAM |
| `<project>-weather-data` | Private regional bucket; collector writes, web identity reads |
| `weather-live-radar` | Every minute, KMPX |
| `weather-live-satellite` | Every five minutes, all three original COD products |
| `weather-live-forecast` | Every five minutes, NWS MapClick JSON |
| `weather-live-metar-clouds` | Once hourly at **:00**, no scheduled retries |
| `weather-live-surface` | Once hourly at **:10**, at most one scheduled retry |

Cloud Scheduler uses OIDC with a dedicated service identity to invoke the private collector. No Linux VM, GPU, AI model, HRRR or RRFS job is needed. The script removes the specifically named retired model, KEVX and separate observations jobs; it preserves unrelated resources and Artifact Registry revisions. Prepared radar/satellite/Surface assets expire after one day. Current manifests and boundary overlays remain. The bucket has no versioning or soft-delete retention for replaceable assets.

## Data behavior

- **METAR:** stays the first/default tab. KFCM/KMIC/KMSP are independent, with routine reports nearest :53 in :50–:59, labeled with the following hour. Both modes use twelve hourly snapshots and one AWC bulk pull at :00. KCFE/KFCE/KSGS remain excluded. No metro average is shown.
- **Surface:** separate station plots and observed analyses from public MADIS mesonet networks, regional RWIS including MnDOT, direct Wisconet fallbacks matched to published MADIS IDs, and saved hourly METAR airports. Domain: 40–49.5°N, 104.5–84°W. Mesonet/road observations must be within 30 minutes preceding the nominal hour. Each field's QC is checked independently. IEM road and direct-only Wisconet fallbacks are labeled local-only. Failed MADIS values cannot be replaced by unflagged copies. Source and quality selectors support comparisons; not every network is public or available. README documents interpolation weights, masks, wind-vector calculations and fixed palettes. Only the selected hourly asset downloads; analysis runs in a browser worker.
- **Radar:** unchanged native KMPX 0.5° completed surveillance/supplemental scans, all available scans in the preceding two hours, no frame cap or smoothing, approved colors from 10 dBZ, white boundary map and manual slider. Feed latency/operator settings control scan frequency.
- **Satellite:** unchanged original COD Central Minnesota True Color, Day Cloud Phase and Nighttime Microphysics, native image projection/map/colors, latest 24 source images and manual slider.
- **Forecast:** compact white NWS rows for 44.9244, −93.4140. Narrative, periods and issue time come from one MapClick JSON response. Expired periods are filtered at request/render time; polling does not force an NWS issuance.

The deployed web service reads saved data only. METAR checks at :00:30; Surface at :10:30 with bounded saved-data retries while collection finishes. Opening/Refresh reads saved manifests, without launching upstream processing. Cold starts, browser downloads and feed latency still apply. First viewing is not guaranteed instantaneous. Partial source failures and delayed updates are shown. Initial Surface history fills over twelve hours.

## Verify after deployment

```bash
gcloud scheduler jobs list --project=weather-lab-511113 --location=us-central1
gcloud run services list --project=weather-lab-511113 --region=us-central1
gcloud storage ls gs://weather-lab-511113-weather-data/live/
```

There should be **five active Weather Lab jobs**. Expected manifests: `radar-KMPX.json`, its private `radar-state-KMPX.json` checkpoint, `metar-clouds.json`, `surface.json`, `forecast.json`, and three `satellite-<product>.json` files. Legacy `observations.json` may remain but is not used by the page. Immutable Surface assets are under `surface/v1/`.

If Surface data is not ready, inspect `weather-collector` logs for feed timeouts, download-size checks or permissions. After fixing a failure, use **Run now** on `weather-live-surface`. A partial result is not presented as full source availability. Deployment requires permission to manage the named services, jobs, identities, bucket IAM and builds.

## Costs and stopping updates

Charges depend on active collector runtime, memory, storage operations, traffic, builds and account-wide free tiers. Surface adds one hourly job and a large public MADIS download; browser analysis does not require paid cloud CPU. Benchmark deployed runtime before assigning an exact monthly estimate. Both services scale to zero, but storage/Artifact Registry charges can remain.

Pause or delete the **five managed `weather-live-*` Scheduler jobs** to stop unattended collection. Pausing retains the site and cached data; updates stop and delayed data are indicated. Deleting the Google project is the comprehensive cleanup option when no longer wanted.
