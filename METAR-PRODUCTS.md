# Airport observation views

The METAR dropdown contains PLOTS and CLOUDS only. The separate MADIS map,
API endpoint, browser preload, collection route and quarter-hour schedule are
retired. Airport METAR collection remains at :00/:05/:10 for routine :45–:59
observations. Both views display four hourly airport frames and the selected
hour when switching between them.

PLOTS shows temperature, dewpoint and a standard wind barb from a small station
dot, without cloud cover or ceiling labels. Barbs are restored and 5% shorter along their shaft than the last pre-vector barb setting; feather widths, stroke thickness, knot encoding
and station anchors stay the same. The collision filter uses the shortened
geometry and reserves space across all four frames for stable history loops.
CLOUDS shows only the first/lowest BKN or OVC height in rounded thousands of feet.
No cloud number is invented when a ceiling is missing or not reported.

Each view retains Set default and Reset view with a separate saved position and
zoom per browser/device. Radar retains its existing saved default/reset controls.
All other map layout, warm instances, media collectors and update schedules stay.

Run `update-weather-lab-airport-views.sh PROJECT_ID` in authenticated Cloud Shell.
It saves existing settings, builds once, deletes only weather-live-madis-map if
present, updates the collector and web images, and verifies the weather pages.
It does not create collection jobs or backfill/download weather history. A full
redeploy also removes the retired MADIS schedule rather than recreating it.

## Current hour and three previous hours

PLOTS and CLOUDS display only the latest four prepared hourly frames (current hour plus the previous three). A station
must have a report in all four frames to be eligible anywhere in that loop.
One missing report, including the first or last hour, hides the station for the
entire loop. A completely empty hour counts as missing; fewer than four available
frames cannot pass completeness. Older gaps outside the displayed four frames do
not count. A station returns automatically once all four rolling frames contain
its reports. This replaces the earlier two-gap/twelve-hour rule.

Cloud ceiling changes and collision thinning are not missing reports. Suppressed
stations reserve no collision space. Original data stays intact; missing hours
never borrow reports. The prepared server cache remains available for collection
and recovery, while both viewer modes and their slider use only four frames.
This display filter adds no source requests or collection work.

Install with `restore-weather-lab-four-frames.sh PROJECT_ID`. This builds and
updates both service images, retaining the standard collection schedules and warm-instance settings,
and the Radar, Satellite, Forecast and Air Q pages.


EXPMET is retired. The standard METAR, Radar, Satellite, Forecast and Air Q tabs
remain. At 10 AM the METAR slider contains 7 AM, 8 AM, 9 AM and 10 AM. The filter
requires a station report in each of those four frames. The removal installer
also stops/deletes only the EXPMET schedule and seed job, replaces both service
images to remove its API/collector, and removes its prepared snapshot. Existing
collection schedules and warm-instance settings are retained.
