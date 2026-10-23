# J-Weather deployment

The current site uses project `j-weather-261020012817`, region `us-central1`, and
branch `metar-cloud-history-20261019` in `Barometer32/weather-lab`.
The public service is `weather-lab`; the private collector is `weather-collector`.

## Update the local Current page

Run in authenticated Google Cloud Shell, with this project's billing enabled:

```bash
curl -fsSL https://raw.githubusercontent.com/Barometer32/weather-lab/metar-cloud-history-20261019/update-j-weather-local-current.sh -o /tmp/j-weather-local-current.sh
bash /tmp/j-weather-local-current.sh
```

The helper saves service/job settings, builds a versioned image if needed,
updates the collector, and runs one initial local observation collection. It
publishes the website only after collection succeeds. It verifies the five tabs
and the prepared local Current product before removing the named retired METAR
collection schedules. Other weather schedules, imagery and forecasts remain in
place. Collector memory is 2 GiB for the national MADIS file decoder. Cloud
changes happen when this helper runs, not when source is saved to GitHub.

The tabs are Current, Radar, Satellite, Forecast and Air Quality. The METAR map
and its history are removed from the interface. Historical deployment helpers
in this repository describe earlier layouts; use the local Current helper for
this version.

## Local Current observations

`local_current.py` reads only public NOAA MADIS mesonet and high-frequency ASOS
files. It conditionally checks the current and previous UTC-hour files every
two minutes, so delayed delivery across the hour boundary can still arrive.
Airport observations use five-minute timestamp marks. Other providers keep
their actual timestamps; many local Hennepin West observations are five minutes
apart, but CWOP and road stations can have different intervals. Five-minute
observations do not guarantee five-minute delivery.

Stations are discovered from source coordinates within ten statute miles of
44.925°N, 93.463°W, the site's Hopkins reference point. This includes public
Hennepin West, road, neighborhood and airport reports available through those
files. Flying Cloud is within the radius; Crystal and MSP are outside it.
Readable city/site names lead the station list; station IDs and original source
names remain in row titles. The list includes network, distance, actual report
time, values and which measurements are used or excluded.

Each station contributes its latest known report. Reports must be within 15
minutes of the newest usable local report, inclusive. Clock age is not the
coherence cutoff. MADIS QC failures, missing values and physical checks exclude
individual fields rather than every measurement at a station. Invalid newer
reports replace older valid reports, preventing silent fallback at that site.
At least three stations per temperature, dewpoint and wind-speed field are
required before publishing a new complete summary. Otherwise the previous
complete summary and its observation timestamp remain displayed.

Temperature, dewpoint and wind speed use equal station weighting for the fields
supplied. Wind direction uses a speed-weighted circular mean. The summary time
is the arithmetic mean of actual participating report timestamps. Display uses
whole Fahrenheit degrees, whole mph and eight compass directions, such as
`SW 5`, without a unit suffix. Sun elevation retains the existing independent
Hopkins calculation. There is no Current history slider.

Prepared state is stored at `live/current.json`, version
`madis-hopkins-ten-mile-v1`. The public `/api/observations` and initial HTML only
read prepared state; page views never download national MADIS files. The browser
reads prepared Current data every 30 seconds while visible.

## Background updates and checks

The local helper configures `weather-live-current` for `*/2 * * * *` in UTC,
POSTing privately to `/collect/current` with the existing Scheduler identity.
It removes only `weather-live-metar-clouds`, `weather-live-madis` and
`weather-live-observations` when those retired jobs exist. The existing radar,
satellite and forecast schedules are preserved.

```bash
gcloud scheduler jobs list --project=j-weather-261020012817 --location=us-central1
gcloud run services list --project=j-weather-261020012817 --region=us-central1
gcloud storage ls -l gs://j-weather-261020012817-weather-data/live/current.json
```

Check the page's average timestamp and individual station times after updating.
Use the collector and `weather-current-start` job logs if the initial average
cannot be prepared. Source publication delays can leave old observation times
even when the collection jobs run successfully. Runtime, storage, build and
traffic charges depend on actual usage; no GPU or numerical-model job is used.
