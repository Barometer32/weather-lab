# Google Cloud deployment

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
- `weather-live-observations`: :56, :59 and :03 each hour (UTC minute offsets also match Central time).
- `weather-live-forecast`: every five minutes, checking the NWS MapClick JSON forecast that matches the linked webpage.
- `weather-live-metar-clouds`: :56, :59 and :03 each hour, retaining routine near-:53 reports for the twelve-hour cloud map.

It creates `weather-collector` and `weather-scheduler` service identities alongside the existing web/build identities. The Scheduler identity may invoke only the collector. The dedicated data bucket uses one-day image cleanup, no object versioning and no soft-delete retention, to avoid accumulating replaceable history. Map overlays and current manifests are retained. The script still removes only the specifically named obsolete model job/scheduler and its old forecast object/empty bucket. It also deletes the retired `weather-live-radar-KEVX` Scheduler job and its two live manifest/checkpoint objects. Old KEVX binary frames become inaccessible and expire under the existing one-day radar lifecycle. It preserves Artifact Registry revisions for rollback.

Cloud changes occur only after running this script, not when code is saved to GitHub. The deployment identity needs permission to manage the named services, Scheduler jobs, service identities and bucket IAM settings, enable APIs and submit builds. New projects must have billing enabled.

## Refresh behavior

Radar and satellite prepare data even when nobody has the site open. Viewing the radar checks the prepared manifest every 30 seconds; satellite checks every minute. These requests do not trigger upstream processing. The newest completed low-level scan appears before the entire loop downloads, and already decoded frames are reused. Browser download time and upstream publishing latency still apply.

Observation sampling remains restricted to routine :50–:59 METARs, favoring :53 and labeling the next hour. The background checks at :56 and :59 collect those reports; :03 catches modest feed delays. The browser reads at :56:20, :59:20 and :03:20, and when opened, returned to, or refreshed manually. It preserves station QA and never replaces a missing current hour with an old complete one.

The METAR clouds tab uses the same routine :50–:59 selection as main observations, preferring :53, excluding SPECI, and labeling the following hour. It collects at :56, :59 and :03, stores twelve hourly snapshots, and backfills missing initial history from bounded AWC station queries. Subsequent runs request a short overlap and merge stored history. A failed query retains the previous successful snapshot; missing station/hour reports are not carried forward. The browser reads at :56:20, :59:20 and :03:20 while visible, and on opening/returning/manual refresh. Map labels show rounded thousands of feet AGL (minimum 1); popups retain exact reported heights. The original COD satellite products remain intact.

NWS retains its own issuance schedule; checking every five minutes does not create new NWS forecasts. Forecast periods, narrative and issue time all come from the same MapClick response. Saved periods are filtered again at request time so an expired afternoon cannot linger in the API. During deployment, the forecast job is triggered to prepare the new source; until it succeeds, an old API-format snapshot is not presented as the matching webpage feed. Original satellite RGB imagery, grid, boundaries and attribution are preserved. Radar boundary tiles and white background are unchanged. Native Level II replaces the coarse image feed and keeps complete KMPX lowest-tilt surveillance scans, including supplemental scans. Every available completed scan in the preceding two hours is included, without a frame-count limit. Missing source scans are indicated rather than extending the loop beyond two hours. Radar operator settings and feed latency determine the actual interval; minute polling does not force faster antenna scans.

## Verify

```bash
gcloud scheduler jobs list --project=weather-lab-511113 --location=us-central1
gcloud run services list --project=weather-lab-511113 --region=us-central1
gcloud storage ls gs://weather-lab-511113-weather-data/live/
```

The bucket should contain `radar-KMPX.json`, its private `radar-state-KMPX.json` checkpoint, `observations.json`, `metar-clouds.json`, `forecast.json` and three `satellite-<product>.json` manifests. If initial collection fails, inspect the `weather-collector` service logs, fix the reported feed/permission error and trigger the affected Scheduler job with its **Run now** control. The public web service does not fall back to expensive per-visitor radar or original-satellite processing in deployed mode.

## Costs and stopping updates

Charges depend on collector runtime, storage operations, web traffic, image downloads and any remaining free-tier allowances. There are five Scheduler jobs; see [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing). METAR clouds adds three lightweight collections per hour and one rolling JSON history object, with a larger history backfill on the first run. Native Level II collection costs should be assessed from deployed runtime, storage operations and traffic. Both services use request-based billing and scale-to-zero settings; storage and Artifact Registry costs can remain while idle.

To stop unattended collection, pause or delete the five `weather-live-*` Scheduler jobs in the Cloud Scheduler GUI. Do not confuse them with the retired `weather-hourly` numerical-model job. Pausing stops updates but preserves the site and saved data; the site will flag delayed updates. Removing the project is the comprehensive cleanup option when the experiment is no longer wanted.
