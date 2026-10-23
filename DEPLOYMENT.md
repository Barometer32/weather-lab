# J-Weather: hourly airport METAR map

The active target is project `j-weather-261020012817`, region `us-central1`.
Source lives on branch `metar-cloud-history-20261019` of `Barometer32/weather-lab`.
Restore that repository and Google project, and link an active billing account,
then run in authenticated Google Cloud Shell:

```bash
curl -fsSL https://raw.githubusercontent.com/Barometer32/weather-lab/metar-cloud-history-20261019/restore-j-weather-airport-metars.sh -o /tmp/j-weather-airports.sh
bash /tmp/j-weather-airports.sh
```

The helper also accepts an explicit existing project ID as its first argument.
It never creates a new project or guesses a billing account. It restores a
pending-deletion project when permitted, checks billing and read access, saves
service/job listings, checks enabled APIs without re-enabling them, and rebuilds the app's registry, identities, storage and
collector through `deploy.sh`. Web publication is deferred until a one-time
Cloud Run job imports twelve populated airport frames and recovers the radar,
satellite and forecast objects. Failure resumes paused managed schedules and
prints the saved working directory. Recovery of Google resources may still
require propagation time after project restoration.

## Layout and sources

Tabs: **METAR, Radar, Satellite, Forecast, Air Quality**. METAR opens first.
There is no Current page or browser Current polling. The original compact SVG
station models, map boundaries, fine zoom steps and mobile fullscreen timeline
are retained. Sun elevation remains current for Hopkins on the METAR page,
independent of the selected history frame. Radar and satellite retain two-hour
loops. NWS forecast and MPCA air quality retain their existing sources.

The airport map includes all available eligible official routine METARs in the
existing Upper Midwest extent: 40–50°N and 100–85°W. There is no station blacklist:
KCFE, KFCE, KSGS and KDEH are eligible again when NOAA supplies reports. KFCM,
KMIC and KMSP appear individually. No plots are removed to avoid label overlap;
zoom in to separate neighboring station models. The searchable list includes
all eligible airports for the selected hour, even outside the current view.
Missing measurements do not remove otherwise usable station plots.

Only NOAA Aviation Weather Center airport METARs feed this map. There is no
MADIS/mesonet merge, rapid airport feed or SPECI substitution. Select the routine
METAR closest to :53 within **:45–:59 inclusive**, using corrected receipt times
as tie breakers, and label it with the following hour. An 8:53 p.m. report is
shown in the 9 p.m. frame. These are hourly-selected reports; airports whose
routine report times fall outside that window are absent for that hour.

## Collection and history

`weather-live-metar-clouds` is invoked every two minutes, including **:00**.
Reports still use one official routine :45–:59 METAR per airport per hourly
frame; this does not switch the observation source to rapid reports.

During :00–:20 inclusive, the collector revisits the preceding two completed
hours every two minutes, even after a partial batch arrives, merging late
reports with the durable twelve-frame archive. Duplicate invocations within the
same two-minute slot reuse a successful prepared result. After :20 a populated
hour is reused, avoiding more NOAA downloads until the next hour. If the entire
new hour is still absent, two-minute retries continue beyond :20. Source errors
or empty new-hour batches retain the previous prepared data.

When automatically following the latest hour, the browser selects the newest
populated frame while a newer frame is empty, labels the actual displayed time,
and indicates which hour is pending. It advances automatically when that new
hour arrives. Manual selections of older history are preserved. No earlier
report is relabeled as a newer observation.

`metar_history.py` imports the initial twelve hours immediately using explicit
regional station batches from NOAA's station catalog. It splits capped queries
instead of accepting truncated results, and validates every hourly frame before
publishing the prepared object. Browser reads only use the prepared object;
opening the page or refreshing it does not start upstream collection.

Prepared data is `live/metar-clouds.json`, with `stationPolicy=all-airports-v1`.
The map reads `/api/station-plots`, marked `sourcePolicy=airport-routine-only`.
Historical Current modules and read APIs remain as compatibility code but are
not part of the UI or collection schedule. Older deployment helpers describe
previous layouts; use the airport helper for this layout.

After successful verification, the restore helper removes the retired
`weather-live-current`, `weather-live-madis` and `weather-live-observations`
schedules. Active managed jobs are:

| Job | Schedule UTC | Purpose |
| --- | --- | --- |
| weather-live-metar-clouds | `*/2 * * * *` | Hourly routine METARs with catch-up retries |
| weather-live-radar | `* * * * *` | Native KMPX reflectivity |
| weather-live-satellite | `*/5 * * * *` | Three GOES products |
| weather-live-forecast | `0,30 * * * *` | NWS point forecast |

## Verify

```bash
gcloud scheduler jobs list --project=j-weather-261020012817 --location=us-central1
gcloud run services list --project=j-weather-261020012817 --region=us-central1
gcloud storage ls -l gs://j-weather-261020012817-weather-data/live/metar-clouds.json
```

Check actual station times and the twelve slider positions. Source availability
and delivery latency determine the number of airports in each frame. Cloud
changes occur only after running the helper, not when code is saved to GitHub.

## API setup rate limits

`ensure-weather-apis.sh` first lists enabled APIs and requests only missing
services. The restore wrapper verifies once and passes that result to
`deploy.sh`, avoiding a second batch-enable call. Service Usage requests use
`--billing-project` set explicitly to the target project; the restore and its
child processes also scope `CLOUDSDK_BILLING_QUOTA_PROJECT` to that project
without changing the user's persistent quota-project setting. Genuine HTTP
429 enablement failures receive bounded backoff and a fresh enabled-service
check before each retry. Read or permission failures stop before any build.

## Update an already running site for retry behavior

```bash
curl -fsSL https://raw.githubusercontent.com/Barometer32/weather-lab/metar-cloud-history-20261019/update-j-weather-metar-retries.sh -o /tmp/j-weather-metar-retries.sh
bash /tmp/j-weather-metar-retries.sh
```

This smaller update saves the running service/job settings, builds a versioned
image, changes only the two app images and METAR schedule, and requests an
immediate collection. It does not enable APIs, recreate cloud resources, or
repeat the full twelve-hour and imagery backfill. Scheduler submission alone
does not prove that NOAA reports are available; check actual timestamps.
