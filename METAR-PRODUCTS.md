# Weather Lab METAR products

METAR is the home tab. Its dropdown defaults to **RTMETAR**, followed by
**PLOTS** and **CLOUDS**. The separate OBSERVATIONS tab, client module, public
API, and hourly-observations collector route are retired.

## RTMETAR

- Five-minute ASOS/HFMETAR reports only, from SD, ND, MN, IA and WI.
- One combined IEM archive request every five minutes (`report_type=1`).
  The airport/state inventory in `rtmetar_stations.py` is from IEM's five state
  ASOS inventories. Inventory membership alone never enables a marker: a
  qualifying five-minute record must actually exist for that airport.
- Raw text must contain `MADISHF` in the remarks, match its airport/time, and
  have a timestamp on a five-minute boundary. No routine METAR or SPECI
  replacement, including at :53. Missing intervals stay missing.
- Temperature and dewpoint are integer Celsius from the main `XX/XX` group
  (`M` denotes negative). T remarks and decoded Fahrenheit fields are never
  temperature inputs. Missing main-group values remain missing.
- Wind is converted from the raw knot group to mph. Both numeric popup speed
  and barb feathers use mph. Speeds below 3 mph have no feathers; 3–7 have a
  half feather, 8–12 a full feather, 13–17 one and a half, and so on.
- The map shows the latest qualifying record for each airport, not a synthetic
  synchronized frame. The hourly slider is hidden in RTMETAR.
- Reports more than 15 minutes old are labeled delayed, and expire after
  60 minutes. A successful collector check does not renew the observation time.
  This feed can arrive late; polling every five minutes does not guarantee
  five-minute end-to-end latency. Per-airport popups show actual source times.
- Public requests read `live/rtmetar-v1.json` only. Source requests run in the
  authenticated background collector, independently of browser visits.

The IEM documents that its MADISHF strings are METAR-formatted renderings of
high-frequency MADIS data, not routine airport-issued METARs:
https://mesonet.agron.iastate.edu/onsite/news.phtml?tag=asos

## Retained hourly products

PLOTS and CLOUDS retain their existing four-consecutive-hour readiness rule,
station spacing, hourly timeline, sources, units and view controls. PLOTS uses
existing Fahrenheit temperature/dewpoint values and mph barbs; Celsius is
specific to RTMETAR. CLOUDS retains sky cover and lowest BKN/OVC height in
thousands of feet AGL. Neither hourly view uses the RTMETAR feed.

Each product has an independent saved map default. Switching between RTMETAR
and hourly maps preserves their respective geographic views; switching PLOTS
and CLOUDS preserves the selected hourly frame.

## Release

From a clean pushed checkout in authenticated Google Cloud Shell:

```bash
bash release-rtmetar.sh
```

The script inspects the existing image repository and Scheduler service
account, builds once, stages both services, and verifies prepared RTMETAR data
before switching the public web service. It creates/updates only
`weather-live-rtmetar` and pauses `weather-live-hourly-observations` after a
successful cutover. Other weather schedules and runtime settings are retained.
Rollback traffic commands are saved in a private temporary directory and used
if verification fails after collector cutover. Existing bucket objects and
hourly METAR history are not deleted.

Validation includes `tests/test_rtmetar.py`, RTMETAR view tests, existing
hourly-map continuity tests, station-model tests, prepared-cache tests, and
navigation tests. `verify_rtmetar_release.py` checks staged/live HTML plus
report provenance and Celsius/mph fields.
