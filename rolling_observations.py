"""A time-matched Twin Cities summary from NOAA MADIS five-minute ASOS."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

KEY = "live/three-airport-observations-v1.json"
STATIONS = {"KFCM": "Flying Cloud", "KMIC": "Crystal", "KMSP": "Minneapolis–St. Paul"}
HOUR = 3600
HISTORY_HOURS = 12
MAX_AGE = 1800
WIND_QC_VERSION = "madis-advisory-wind-v1"


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")


def whole_celsius(c):
    # The HF-ASOS fields are native integer Celsius encoded in Kelvin.
    # Allow float conversion noise only; never promote a tenths value.
    if c is not None and -90 <= c <= 65 and abs(c - round(c)) < .001:
        return round(c)
    return None


def summary(stamp, stations):
    from app import wind_mean

    reports = [stations[code] for code in STATIONS]

    def fahrenheit(field):
        # Average the native whole-degree Celsius observations before converting.
        return round(sum(r[field] for r in reports) / len(reports) * 1.8 + 32)

    wind = wind_mean(reports)
    return {
        "observedAt": iso(stamp), "tempF": fahrenheit("temp"), "dewpointF": fahrenheit("dewp"),
        "wind": {
            "speedMph": round(wind["speedMph"]) if wind["speedCount"] == len(STATIONS) else None,
            # wind_mean leaves variable and missing bearings out of its
            # vector mean while retaining their valid scalar speeds.
            "direction": wind["direction"],
            "variable": wind["direction"] is None and (wind["variable"] or wind["directionCount"] == len(STATIONS)),
        },
    }


def present(saved, now):
    saved = saved or {}
    stamp = now.timestamp()
    groups = defaultdict(dict)
    for t, code, report in saved.get("reports", []):
        if t <= stamp:
            groups[t][code] = report
    complete = {t: stations for t, stations in groups.items() if STATIONS.keys() <= stations.keys()}
    latest = max(complete, default=None)
    # The history can advance when an hour starts reporting, even while the
    # live card is holding the last synchronized set from the previous hour.
    newest = max(groups, default=None)
    anchor = int(stamp if newest is None or stamp-newest > HISTORY_HOURS*HOUR else newest) // HOUR * HOUR
    history = []
    for i in range(HISTORY_HOURS):
        t = anchor - i * HOUR
        chosen = max((candidate for candidate in complete if t-HOUR < candidate <= t), default=None)
        history.append({"time": iso(t), "reading": summary(chosen, complete[chosen]) if chosen is not None else None})
    return {
        "current": summary(latest, complete[latest]) if latest is not None and stamp-latest <= MAX_AGE else None,
        "lastCompleteAt": iso(latest) if latest is not None else None,
        "history": history, "checkedAt": saved.get("checkedAt"), "serverTime": iso(stamp),
        "stationNames": STATIONS, "windowMinutes": MAX_AGE // 60,
        "windQcVersion": saved.get("windQcVersion"),
    }


def fetch_archive(url):
    request = Request(url, headers={"User-Agent": "Weather-Lab (https://github.com/Barometer32/weather-lab)"})
    with urlopen(request, timeout=12) as response:
        payload = response.read(8_000_001)
    if len(payload) > 8_000_000:
        raise ValueError("MADIS archive file exceeds expected size")
    return payload


def prepare(store, now, payloads, archive_download=None):
    from madis_observations import file_url, parse_file

    saved = store.read_json(KEY) or {}
    stamp = now.timestamp()
    hour = now.replace(minute=0, second=0, microsecond=0)
    lower = int(hour.timestamp()) - HISTORY_HOURS * HOUR
    reports = {(t, code): r for t, code, r in saved.get("reports", [])
               if lower <= t <= stamp}

    def merge(payload, as_of):
        for row in parse_file(payload, STATIONS, as_of, high_frequency_only=True, allow_advisory_wind=True):
            t, code = row["obsTime"], row["icaoId"]
            if code not in STATIONS or row["metarType"] != "HFMETAR" or not lower <= t <= stamp or t % 300:
                continue
            temp, dew = whole_celsius(row["temp"]), whole_celsius(row["dewp"])
            if temp is None or dew is None:
                continue
            reports[int(t), code] = {"temp": temp, "dewp": dew, "wspd": row["wspd"], "wdir": row["wdir"]}

    for target, payload in payloads:
        merge(payload, min(now, target + timedelta(hours=1)))
    # Seed the nearby hours the public live endpoint still retains. Older
    # slots fill from scheduled collection rather than another report feed.
    # Re-read available archive files once after the QC change. Keep saved
    # reports for hours that have already fallen out of the public feed.
    scanned = ({t for t in saved.get("scannedHours", []) if t >= lower}
               if saved.get("windQcVersion") == WIND_QC_VERSION else set())
    missing = [hour - timedelta(hours=i) for i in range(2, 5)
               if int(hour.timestamp()) - i * HOUR not in scanned]
    archive_download = archive_download or fetch_archive

    def archived(target):
        try:
            return target, archive_download(file_url(target)), False
        except OSError as error:
            return target, None, getattr(error, "code", None) in (403, 404)
        except ValueError:
            return target, None, True

    # Bound one invocation even when the source is slow. Unavailable or
    # incomplete exact-hour sets stay blank.
    with ThreadPoolExecutor(max_workers=3) as pool:
        for target, payload, unavailable in pool.map(archived, missing):
            if unavailable:
                scanned.add(int(target.timestamp()))
            if payload is None:
                continue
            try:
                merge(payload, target + timedelta(hours=1))
            except (OSError, ValueError, KeyError):
                continue
            scanned.add(int(target.timestamp()))
    state = {"checkedAt": iso(stamp), "scannedHours": sorted(scanned), "windQcVersion": WIND_QC_VERSION,
             "reports": [[t, code, r] for (t, code), r in reports.items()]}
    store.write_json(KEY, state)
    result = present(state, now)
    return {"current": result["current"] is not None,
            "hours": sum(slot["reading"] is not None for slot in result["history"])}
