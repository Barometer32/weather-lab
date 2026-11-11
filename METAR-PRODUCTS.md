# Weather Lab METAR products

METAR is the home tab. Its dropdown contains **PLOTS** and **CLOUDS** only.
PLOTS opens on initial load and whenever the user returns to the METAR tab.
A visibility refresh keeps the currently selected hourly product and frame.
The retired OBSERVATIONS and RTMETAR UI, APIs and collector routes are absent.

## Hourly maps

PLOTS and CLOUDS use official routine airport METARs from :45–:59, closest to
:53, labeled with the following hour. Four consecutive populated hours must
be ready before the viewer advances. Individual airports must be present in
all four frames; CLOUDS additionally requires usable sky data in every frame.
KCFE remains excluded. Saved geographic defaults for PLOTS and CLOUDS are
independent. Hourly station spacing and the timeline are retained.

PLOTS uses Fahrenheit temperature/dewpoint and mph wind barbs. CLOUDS shows
sky cover and the lowest BKN/OVC height in thousands of feet AGL. More airports
appear when zooming in. Neither product fetches the removed five-minute feed.

## Background preparation and warm startup

The scheduled hourly collector normally overlaps two archive hours. When the
saved history lacks a recent complete four-hour window, it fetches five real
archive hours to repair outage gaps. It writes `live/metar-loop.json` only when
a usable window exists. Failed or incomplete recovery retains the prior usable
loop, whose age is still checked. Public compact requests read that prepared
object without rebuilding the archive. Until initial preparation succeeds they
return an explicit 503 recovery message.

Radar, satellite, forecast, air quality, and the hourly maps are collected by
Cloud Scheduler independently of browser visits. The public service uses
`WEATHER_PREPARED_ONLY=true`; all retained product manifests start independently
when the page opens. Saved browser copies can paint while fresh prepared data
is downloaded. Latest default radar/satellite assets are warmed in the browser
when Data Saver is off; whole historical image loops load on demand.

One service-level minimum website instance serves every tab and reduces cold
starts. This incurs idle instance charges. Network transfers and browser drawing
still take time; upstream availability determines how recent observations can be.
The displayed source times and stale indicators remain authoritative.

## Release

From a clean pushed checkout in authenticated Google Cloud Shell:

```bash
bash release-plots.sh
```

The script inspects the existing services, builds once, stages both services,
and pauses the retired RTMETAR job. It seeds all five retained collectors,
resumes any paused retained schedules, and checks prepared data for every tab
before switching website traffic. The hourly collector runs every five minutes
with a 300-second deadline, skipping unnecessary NOAA requests once the hour
settles. The public service keeps at least one warm instance and uses prepared
data only. Both settings are read back and verified after deployment.

If preparation or live verification fails, the script restores prior service
traffic, schedules, enabled/paused states, and the website minimum-instance
setting. After all deployment checks pass, it deletes only the retired
`weather-live-rtmetar` scheduler and `live/rtmetar-v1.json` from the actual data
bucket. It then confirms all five retained jobs are enabled. Cleanup failures
are reported separately while the verified replacement stays live. Other bucket
objects and saved hourly history are retained. Browser caches discard the old
rapid manifest and saved rapid-map default.

`verify_weather_release.py` checks HTML defaults, the removed API, four populated
hourly frames, fresh prepared manifests for every tab, and readable latest
prepared radar/satellite/air-quality assets. Deployment tests exercise staged
success, outage rollback, cleanup failure, and repeat deployment after retirement.
