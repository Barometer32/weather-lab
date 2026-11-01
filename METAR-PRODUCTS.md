# Airport observation views

The METAR dropdown contains PLOTS and CLOUDS only. The separate MADIS map,
API endpoint, browser preload, collection route and quarter-hour schedule are
retired. Airport METAR collection remains at :00/:05/:10 for routine :45–:59
observations. Both views retain twelve hourly airport frames and the selected
hour when switching between them.

PLOTS shows temperature, dewpoint and a standard wind barb from a small station
dot, without cloud cover or ceiling labels. Barbs are restored and 5% shorter along their shaft than the last pre-vector barb setting; feather widths, stroke thickness, knot encoding
and station anchors stay the same. The collision filter uses the shortened
geometry and reserves space across all twelve hours for stable history loops.
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

## Stable station history

Both views hide a station throughout the displayed twelve-hour history when its
raw report availability contains two or more completed present → missing →
present cycles. Leading missing frames, trailing missing frames and one completed
gap do not suppress a station. Fully empty feed frames do not count against
individual stations. Cloud ceiling changes and collision thinning are not report
gaps. Suppressed stations reserve no collision space, and become eligible again
when their repeated gaps leave the rolling window. Original reports remain intact;
missing hours never borrow data from another hour. The filter uses downloaded
history and makes no additional source requests.

Install with `update-weather-lab-station-continuity.sh PROJECT_ID`. This builds and
updates only the website, retaining collection schedules and warm-instance settings.
