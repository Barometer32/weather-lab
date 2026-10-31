# Current conditions

OBSERVATIONS averages only the twelve Hennepin West stations selected by the user:
HPN02, HPN07, HPN09, HPN20, HPN21, HPN24, HPN25, HPN26, HPN38, HPN39, HPN42, HPN47.
Fridley (HPN21) is intentionally included even though it is outside Hennepin County.
HPN07 is the Hennepin West station near MSP, not the KMSP airport METAR.

`hennepin_current.py` reads NOAA's public MADIS mesonet files every five minutes
through `weather-live-hennepin-current` (`*/5 * * * *`, no automatic retries).
It checks this hour and reads the preceding hour only while the current-hour
station set is incomplete. Conditional requests reuse unchanged files. Only the
selected station records and up to two hours of context are saved; there is no
12-hour history download for CURRENT. Browser refreshes read the saved average.

Temperature and dewpoint are equal station averages displayed to the nearest whole °F. Wind
speed is the arithmetic mean in mph; direction uses speed-weighted circular
averaging and is displayed in eight compass sectors. Opposing winds with a
weak resultant show VRB; calm shows 0. Values are not invented for missing fields.
Hopkins apparent solar elevation uses the existing NOAA/Meeus implementation and
updates from the clock independently of observation delivery.

QC is per measurement: honor MADIS rejection flags, missing values and physical
checks. Reports must be no more than 45 minutes old and within ten minutes of
the newest usable selected report. At least nine sites must contribute to each
of temperature, dewpoint and wind before a new complete average is published.
A temperature/dewpoint isolated from at least three neighbors within 15 miles by
more than max(6°F, four robust standard deviations) is monitored, then withheld
after three distinct successive report times. Repeated API reads do not advance
that counter. A return to agreement restores the field. Legitimate regional
changes are not rejected just for changing quickly. Station details show missing
or excluded fields, preliminary QC warnings and the latest report times.
If the group cannot form a usable average, retain the last one with its original
timestamp and an explicit delayed notice. Averages do not guarantee sensor accuracy.

Run `update-weather-lab-hennepin-current.sh PROJECT_ID` in Cloud Shell to build,
seed this one new product, add its schedule and publish the OBSERVATIONS tab. It saves
service settings first and changes only images plus the new schedule, preserving
existing warm-instance settings, domains, billing and other collection schedules.
The existing hourly Fahrenheit METAR map and its :00/:05/:10 schedule are unchanged.

The OBSERVATIONS tab uses four centered cards, with a two-by-two phone layout.
The phone tab label is OBS. Existing 80% phone map sliders, laptop sliders,
PLOTS/CLOUDS, shortened wind barbs and radar rendering are preserved.
