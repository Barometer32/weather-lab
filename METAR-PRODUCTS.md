# Airport observation views

The METAR dropdown contains PLOTS and CLOUDS only. The separate MADIS map,
API endpoint, browser preload, collection route and quarter-hour schedule are
retired. Airport METAR collection remains at :00/:05/:10 for routine :45–:59
observations. Both views display six hourly airport frames and the selected
hour when switching between them.

PLOTS shows temperature, dewpoint and a standard wind barb from a small station
dot, without cloud cover or ceiling labels. Barbs are restored and 5% shorter along their shaft than the last pre-vector barb setting; feather widths, stroke thickness, knot encoding
and station anchors stay the same. The collision filter uses the shortened
geometry and reserves space across all six hours for stable history loops.
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

## Stable six-hour station history

PLOTS and CLOUDS display only the latest six prepared hourly frames. A station
must have a report in all six frames to be eligible anywhere in that loop.
One missing report, including the first or last hour, hides the station for the
entire loop. A completely empty hour counts as missing; fewer than six available
frames cannot pass completeness. Older gaps outside the displayed six frames do
not count. A station returns automatically once all six rolling frames contain
its reports. This replaces the earlier two-gap/twelve-hour rule.

Cloud ceiling changes and collision thinning are not missing reports. Suppressed
stations reserve no collision space. Original data stays intact; missing hours
never borrow reports. The prepared server cache remains available for collection
and recovery, while both viewer modes and their slider use only six frames.
This display filter adds no source requests or collection work.

Install with `update-weather-lab-six-hour-metars.sh PROJECT_ID`. This builds and
updates only the website, retaining collection schedules, warm-instance settings,
and the Radar, Satellite, Forecast and Air Q pages.
