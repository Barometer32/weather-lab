# WEATHER LAB · METAR Fresh

Four views: hourly airport METAR plots, two-hour KMPX radar, Central Minnesota satellite, and the NWS Hopkins forecast. No contours or mesonet observation feeds.

## Deploy to a new Google Cloud project

Open Google Cloud Shell, clone this branch, and run `bash start-fresh.sh`.
The script creates **Weather Lab METAR Fresh**, links an active billing account, builds and uploads the application using Google Cloud Build, deploys public `weather-lab` and private `weather-collector` Cloud Run services, and imports twelve hours of NOAA METAR history. No ZIP upload or paid weather API is required. Cloud Build uses a dedicated `weather-builder` service account and regional user-owned build/log buckets. Cloud Shell's local Docker daemon is not used unless you explicitly set `WEATHER_BUILD_MODE=docker`.

Before submitting a build, setup runs read-only checks of the signed-in caller's effective build and service-account permissions. Missing access is printed with the permission and resource names; setup then stops before submitting a build. This check never grants IAM roles. Access tokens remain in memory and are never printed or saved.

If multiple billing accounts are available, set `WEATHER_BILLING_ACCOUNT=YOUR_ACCOUNT_ID` before running. The selected account must be open and accessible to your signed-in Google account. Google Cloud compute, storage and scheduling charges still apply.

The project ID is saved in `$HOME/weather-lab-metar-project.txt`. Rerunning the script resumes that project instead of creating extras. To deliberately create a different project, supply a new unused `WEATHER_PROJECT` ID. The script does not restore or delete old projects. Setup may take several minutes; keep Cloud Shell open until it prints the final URL. New-project permission propagation is retried a bounded number of times. If a command fails, rerun the same script; persistent permission errors still require fixing your Google account's access.

## METAR observations

Only routine NOAA Aviation Weather Center METARs are accepted, including reporting ASOS/AWOS airport sites. The Upper Midwest bounds are 40–50°N, 100–85°W. KCFE/KFCE and KSGS retain the existing station exclusions.

Collection runs once an hour at **:02**. For each hour, accepted report timestamps are strictly **:50:00–:59:59 of the previous hour**. Prefer the report nearest :53; ties prefer newer observations and then corrections. An 11:53 report is labeled noon and retains 11:53 in its popup. SPECI and rapid MADISHF reports, out-of-window sites and missing values are omitted. These strict rules intentionally reduce station coverage.

Each collection queries the previous hour's NOAA archive, so a newer SPECI or off-window report cannot hide an eligible routine METAR in a latest-only cache. AWC's 400-result cap is handled by splitting geographic queries; requests are globally rate limited to fewer than 100/minute. Collection runs once per hour even when several capped queries are needed to retrieve that hour. Browser Refresh only reads prepared data.

Twelve real hourly frames are backfilled during setup. History remains in a private Cloud Storage bucket when Cloud Run scales to zero. No synthetic times or station values fill gaps. Failed collections retain saved data, and the page shows delayed-update status. The initial import pauses the hourly writer, resumes it on exit, and immediately runs it afterward.

Plots show temperature and dew point in °F and wind in mph, with arrows pointing toward wind flow. The central circle now shows reported sky cover: open for CLR/SKC, quarter-filled FEW, half-filled SCT, three-quarter BKN and solid OVC. Fractional fills represent METAR categories (1–2, 3–4 and 5–7 eighths), not exact measured oktas. The wind arrow has a longer, thicker shaft and solid arrowhead outside the circle; adjacent labels move just enough to clear its direction. Blue wind speed matches the temperature text size; calm winds have a second ring. Temperature and dew point sit close to the circle on the left, blue wind speed is at the lower right, and the lowest BKN/OVC base appears in black at the upper right in hundreds of feet AGL, such as `27` for 2,700 feet or `03` for 300 feet. Cloud height matches the temperature/dew-point text size. Bases above 9,900 feet retain three digits for accuracy. Obscured sky uses an X and a separately labeled VV value; unknown sky uses ?. Popups include all layers and exact heights. Existing history obtains cloud information from its saved raw METARs without new archive downloads. Regional collection discovers airport IDs from the NOAA station catalog and queries explicit station batches, splitting capped responses, because NOAA bbox queries can omit stations even below the cap. The version update repairs saved twelve-hour history once; subsequent collections remain hourly. Zoom reveals more non-overlapping stations; the searchable list includes plots hidden to prevent overlap. Actual METAR timestamps and raw reports remain in popups. Basic range, coordinate and dew-point checks apply; these do not constitute complete instrument QC.

## Radar, satellite and forecast

- KMPX native Level II 0.5° reflectivity, the original continuous COD-style green-to-yellow/orange/red/magenta gradient, and all available scans in the rolling **two-hour** window. No personal-location dots. Faint major highways have no city labels. Radar collection runs every minute; native scan timing is controlled by NWS.
- Central Minnesota GOES-East True Color, Day Cloud Phase and Nighttime Microphysics. Twenty-four images per product, original colors, state/county overlays, manual timeline. Prepared every five minutes.
- Official NWS day/night point forecast for Hopkins at 44.9244, -93.4140, checked at :00 and :30 each hour and retaining NWS wording and issuance time.

Both Cloud Run services scale to zero and have a maximum of one instance. There are four Cloud Scheduler jobs. Only the web service is public; collection requires authenticated invocation. The dedicated private bucket removes replaceable imagery after one day; live hourly history is retained.

## Local checks

Install `requirements.txt`, then run `python -m unittest discover -s tests -v` and `node tests/metar_views.test.js`. Additional JS checks cover radar history, highways and tabs. `python app.py` starts the web view; native radar requires the collector and `WEATHER_DATA_BUCKET`.
