# Airport observation views

The METAR dropdown contains PLOTS and CLOUDS only. The separate MADIS map,
API endpoint, browser preload, collection route and quarter-hour schedule are
retired. Airport METAR collection remains at :00/:05/:10 for routine :45–:59
observations. Both views retain twelve hourly airport frames and the selected
hour when switching between them.

PLOTS shows temperature, dewpoint, a small station dot and a short solid arrow
pointing where the wind is blowing TO. Official METAR bearings describe the source,
so the arrow uses source bearing +180 degrees. A west wind points east. Wind speed
appears in blue at the lower right, rounded to whole mph. Calm shows 0 with no
arrow; variable/unknown bearing does not invent an arrow. Cloud coverage and
height remain absent from PLOTS. Text stays in fixed quadrants outside the compact
arrow envelope, and collision filtering reserves the largest footprint across
the twelve-hour loop. Station anchors, hourly collection and history are unchanged.
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

Run `update-weather-lab-wind-vectors.sh PROJECT_ID` for this visual-only change.
It updates only the website image, retaining collector schedules, warm instances,
all five tabs, saved map views, cloud plots and centered 80% phone sliders.
