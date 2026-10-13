# Google Cloud deployment

## Restore WEATHER LAB

After restoring the Google project and linking an active billing account, deploy
from a fresh clone of `https://github.com/Barometer32/weather-lab.git`. This
preserves any older Cloud Shell checkout and uses the current saved version:

```bash
WEATHER_LAB_DIR="$(mktemp -d "$HOME/weather-lab-restore.XXXXXX")"
git clone https://github.com/Barometer32/weather-lab.git "$WEATHER_LAB_DIR"
cd "$WEATHER_LAB_DIR"
bash deploy.sh weather-lab-511113
```

The deployment recreates missing managed resources and resumes any paused
`weather-live-*` jobs it manages. Fresh history is collected if cached images
were deleted. Some restored Google resources may take time to become available;
if Google reports a restoration or billing propagation error, retry after the
project and billing status have finished updating. The page name is WEATHER LAB;
the existing service IDs and data sources remain the same.

Weather Lab uses a public Cloud Run web service, a private Cloud Run collector, and a private regional Standard Storage bucket. Cloud Scheduler invokes the collector with OIDC authentication. There are no HRRR/RRFS or AI jobs.

## Update

Run in your authenticated Google Cloud Shell:

```bash
cd ~/weather-lab
git pull --ff-only
bash deploy.sh weather-lab-511113
```

The first backfill prepares the complete two-hour radar loop and the latest 24 images for each satellite product. Latest imagery is published first, with checkpoints as history fills in. Allow a few minutes on the first deployment, then refresh the webpage. Each invocation limits its backfill work so later runs can resume from the saved progress. Future runs download/process only newly published frames. A failed collection retains the previous successful manifest; stale data and missing scans/images are indicated in the viewer.

The script creates or updates these resources in `us-central1`:

- `weather-lab`: public web service, 1 CPU / 1 GiB, zero minimum and one maximum instance.
- `weather-collector`: private service, 1 CPU / 1 GiB, zero minimum and one maximum instance. Its endpoints cannot be invoked anonymously.
- `<project>-weather-data`: private bucket. Web identity has object-read permission; collector has object-management permission, scoped to this bucket.
- `weather-live-radar`: every minute for KMPX, using `/collect/radar-KMPX`.
- `weather-live-satellite`: every five minutes, collecting all three products.
- `weather-live-observations`: at :55, :58 and :02 every hour (`2,55,58 * * * *`), checking official AWC routine METARs for all three stations.
- `weather-live-forecast`: every five minutes, checking the NWS MapClick JSON forecast that matches the linked webpage.
- `weather-live-metar-clouds`: at :55, :58 and :02 each hour, preparing twelve routine hourly snapshots shared by cloud and weather views.

It creates `weather-collector` and `weather-scheduler` service identities alongside the existing web/build identities. The Scheduler identity may invoke only the collector. The dedicated data bucket uses one-day image cleanup, no object versioning and no soft-delete retention, to avoid accumulating replaceable history. Map overlays and current manifests are retained. The script still removes only the specifically named obsolete model job/scheduler and its old forecast object/empty bucket. It also deletes the retired `weather-live-radar-KEVX` Scheduler job and its two live manifest/checkpoint objects. Old KEVX binary frames become inaccessible and expire under the existing one-day radar lifecycle. It preserves Artifact Registry revisions for rollback.

Cloud changes occur only after running this script, not when code is saved to GitHub. The deployment identity needs permission to manage the named services, Scheduler jobs, service identities and bucket IAM settings, enable APIs and submit builds. New projects must have billing enabled.

## Refresh behavior

Radar and satellite prepare data even when nobody has the site open. Viewing the radar checks the prepared manifest every 30 seconds; satellite checks every minute. These requests do not trigger upstream processing. The newest completed low-level scan appears before the entire loop downloads, and already decoded frames are reused. Browser download time and upstream publishing latency still apply.

Current conditions and twelve hourly history rows use the official routine METAR nearest :53 within :50–:59, labeling the following hour and excluding SPECI/rapid reports. Temperature/dew point prefer the raw METAR T remark in tenths Celsius, with decoded source values as fallback, averaged before Fahrenheit conversion. Current conditions require all three valid reports for the labeled hour. Incomplete historical rows retain valid contributors and are flagged.

The observations Scheduler cron is `2,55,58 * * * *` in UTC (the same minute marks in Central time). Each collector invocation invalidates the AWC cache so consecutive checks actually fetch independently. No main-observation MADIS download occurs. Corrections and partial batches merge with retained sixteen-hour AWC reports; failures leave the saved snapshot/check time untouched. The initial HTML is rendered with prepared observation values/history and safely embeds the same JSON for startup hydration, avoiding a second startup API round trip. Root-page rendering never downloads upstream METAR data. Browser API reads occur on visible-tab return/manual refresh and 30 seconds after the three collector check times. It no longer polls observations every minute. API freshness uses the latest scheduled check with a two-minute grace period, rather than flagging the normal between-check gap. The regional METAR job uses the same three minute marks.


The METAR dropdown offers unboxed cloud ceiling numbers (known BKN/OVC bases only) and transparent weather station models (open circle, wind barbs, temperature and dew point). Both share 12 routine hourly snapshots closest to :53 within :50–:59, excluding SPECI/rapid data and labeling the following hour. No Live position or cloud-filled weather circles remain. KCFE stays excluded. The metro plot uses the same routine selection and T-remark precision as the main hourly observations.

The regional job's cron is `2,55,58 * * * *`. AWC current cache discovers stations, while bounded history queries recover routine reports replaced by SPECI in the cache. Every scheduled check merges short overlap queries with durable history; initial collection backfills thirteen hours. No MADIS feed is downloaded. The browser/API use prepared hourly data with schedule-aware staleness, gzip compression, and manual position preservation. Wind barbs, closer zoom-aware spacing and original boundary map styling remain. The original COD satellite products remain intact.

NWS retains its own issuance schedule; checking every five minutes does not create new NWS forecasts. Forecast periods, narrative and issue time all come from the same MapClick response. Saved periods are filtered again at request time so an expired afternoon cannot linger in the API. During deployment, the forecast job is triggered to prepare the new source; until it succeeds, an old API-format snapshot is not presented as the matching webpage feed. Original satellite RGB imagery, grid, boundaries and attribution are preserved. Radar boundary tiles and white background are unchanged. Native Level II replaces the coarse image feed and keeps complete KMPX lowest-tilt surveillance scans, including supplemental scans. Every available completed scan in the preceding two hours is included, without a frame-count limit. Missing source scans are indicated rather than extending the loop beyond two hours. Radar operator settings and feed latency determine the actual interval; minute polling does not force faster antenna scans.

## Verify

```bash
gcloud scheduler jobs list --project=weather-lab-511113 --location=us-central1
gcloud run services list --project=weather-lab-511113 --region=us-central1
gcloud storage ls gs://weather-lab-511113-weather-data/live/
```

The bucket should contain `radar-KMPX.json`, its private `radar-state-KMPX.json` checkpoint, `observations.json`, `metar-clouds.json`, `forecast.json` and three `satellite-<product>.json` manifests. If initial collection fails, inspect the `weather-collector` service logs, fix the reported feed/permission error and trigger the affected Scheduler job with its **Run now** control. The public web service does not fall back to expensive per-visitor radar or original-satellite processing in deployed mode.

## Costs and stopping updates

Charges depend on collector runtime, storage operations, web traffic, image downloads and any remaining free-tier allowances. There are five Scheduler jobs; see [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing). The METAR collector runs at :55/:58/:02 each hour and stores one rolling history/live JSON object, with a larger history backfill on the first deployment of the data format. It limits historic overlap requests to avoid repeating the full backfill on later checks. Native Level II collection costs should be assessed from deployed runtime, storage operations and traffic. Both services use request-based billing and scale-to-zero settings; storage and Artifact Registry costs can remain while idle.

To stop unattended collection, pause or delete the five `weather-live-*` Scheduler jobs in the Cloud Scheduler GUI. Do not confuse them with the retired `weather-hourly` numerical-model job. Pausing stops updates but preserves the site and saved data; the site will flag delayed updates. Removing the project is the comprehensive cleanup option when the experiment is no longer wanted.
