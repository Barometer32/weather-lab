# Observation dropdown

The METAR heading offers PLOTS, CLOUDS and MADIS. PLOTS uses a small solid
station dot with temperature, dewpoint and a wind barb starting at the dot.
Cloud cover and ceiling labels are absent from PLOTS. CLOUDS shows only the
lowest known BKN/OVC airport height in rounded thousands of feet. Clear or
scattered reports do not produce a CLOUDS label; missing heights are not invented.

PLOTS and CLOUDS share twelve hourly airport frames, routine :45–:59 reports and
:00/:05/:10 checks. Their selected hour is retained when visiting MADIS and back.
MADIS has no history or slider. It is a snapshot of the latest report per station
observed within the preceding 25 minutes, inclusive of both endpoints. Its
quarter-hour collector runs at :00/:15/:30/:45. For a 19:15 collection, eligible
reports are 18:50–19:15. Each station's newest record wins independently. A
newer NOAA-QC-rejected measurement never causes an older good record to return.
Source delivery can delay or omit stations; the timestamp is the collection time,
and each station popup shows its actual observation time. Nothing outside the
window is substituted to fill gaps. If a whole collection fails, retain the prior
snapshot and its original timestamp; show a delay indicator after 35 minutes.

MADIS requests only current/previous-hour public Integrated Mesonet files that
intersect its 25-minute window, with conditional HTTP reuse of unchanged files.
There is no twelve-hour mesonet download or history. Parsed per-file latest
records are retained only for reuse/reissued QC; they are not public history.
The snapshot persists in `live/madis-map.json`, separate from airport data in
`live/metar-clouds.json`. Source files replace their prior records on reissue.
Choosing a view or refreshing the browser reads prepared data, not external feeds.

MADIS covers 40–50°N, 100–85°W and includes public mesonets with usable temperature,
dewpoint or wind: Hennepin West, MnDOT, CWOP, RAWS and other state/local networks.
NOAA per-field QC remains in place. Airport IDs from prepared airport history,
conventional K/C four-character airport IDs, and explicit ASOS/AWOS/METAR/NWS/WFO
metadata are excluded. Unknown ownership cannot be inferred: MADIS does not have
universal ownership metadata. HPN07 is a Hennepin West sensor near MSP, not KMSP.
Restricted/nonpublic feeds are not requested. All MADIS plots use a dot and a
wind barb, even if the source also includes cloud measurements. Missing clouds
never imply clear sky. Collision filtering prioritizes Hennepin West and MnDOT;
zooming reveals more eligible sites without overlapping plots.

Set default and Reset view are available for PLOTS, CLOUDS and MADIS. Each product
has its own saved center/zoom in this browser/device's local storage. Reset view
returns to that saved view; without one it uses the existing three-airport focus.
Radar's existing saved default now also has a Reset view action. Saved defaults are not synced between
phone and laptop. Mobile actions stay visible above the timeline where present.

`update-weather-lab-madis-products.sh PROJECT_ID` saves live settings, builds once,
updates the collector image, seeds only the current mesonet snapshot in a private
one-time job, updates only the MADIS schedule and publishes the website. Warm
instances, other schedules, airport history, billing and domains are preserved.
