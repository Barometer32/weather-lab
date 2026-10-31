# Observation dropdown

The METAR heading offers PLOTS (the unchanged airport station model), CLOUDS
(number-only lowest known BKN/OVC airport height in rounded thousands of feet),
and MADIS (separate public surface-mesonet plots). Clear or scattered airport
reports do not produce a CLOUDS label. A missing ceiling base is not invented.

Airport PLOTS and CLOUDS share the existing twelve hourly airport frames, routine
:45–:59 reports and :00/:05/:10 checks. Choosing a view or refreshing the browser
never downloads an external weather feed. Map position and selected hour carry
across view changes; collision filtering uses the chosen plot's footprint.
MADIS spacing prioritizes Hennepin West and MnDOT, then other networks; zooming
reveals more eligible stations without overlapping their plots.

MADIS uses the public Integrated Mesonet files within the existing Upper Midwest
extent: 40–50°N, 100–85°W. Include all public networks with usable map measurements,
including Hennepin West, MnDOT, CWOP, other state mesonets and RAWS. Retain NOAA
per-field QC: failed or missing measurements remain unavailable. Exclude airport
IDs from prepared airport history, conventional K/C four-character airport IDs,
and stations explicitly identified as ASOS, AWOS, METAR, NWS or WFO in network,
provider or station metadata. MADIS does not supply universal ownership metadata,
so unidentified affiliations cannot be guaranteed. HPN07 remains a Hennepin West
site near MSP; it is not the KMSP ASOS. Restricted/nonpublic feeds are not requested.

MADIS keeps twelve completed hourly frames. Each frame selects the latest report
per site anywhere in its hour; the frame label is the hour ending. No :45–:59
filter applies to mesonets, so road sites reporting at :40 remain eligible.
The separate `weather-live-madis-map` job checks at :00/:15/:30/:45, revisiting the
latest two completed hours to pick up delayed reports and NOAA QC corrections.
A twelve-hour import runs only for initial seeding/restoration. Conditional HTTP
requests reuse unchanged source files. All frames persist in `live/madis-map.json`
independently of `live/metar-clouds.json`. Do not merge these into airport PLOTS.
If a mesonet does not measure clouds, its plot uses a station dot rather than
inventing clear sky, a ceiling, or an unknown cloud label for every sensor.

`update-weather-lab-madis-products.sh PROJECT_ID` saves live settings, builds once,
updates the collector image, seeds mesonet frames in a private one-time job,
creates/updates only the MADIS schedule, and publishes the website after seeding.
Warm instances, other collection schedules, billing and domains are preserved.
