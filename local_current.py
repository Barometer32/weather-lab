"""Rolling public MADIS conditions within ten miles of the Hopkins reference."""
from datetime import datetime, timedelta, timezone
import math
import re

VERSION = "madis-hopkins-ten-mile-v1"
KEY = "live/current.json"
CENTER = (44.925, -93.463)
RADIUS_MILES = 10
MAX_SPREAD_SECONDS = 15*60
MIN_STATIONS = 3
UTC = timezone.utc


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def distance_miles(lat, lon):
    a, b, x, y = map(math.radians, (*CENTER, lat, lon))
    h = math.sin((x-a)/2)**2 + math.cos(a)*math.cos(x)*math.sin((y-b)/2)**2
    return 3958.7613*2*math.asin(math.sqrt(min(1, h)))


def finite(value, low=-math.inf, high=math.inf):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def place(row):
    """Prefer the source's readable site/city name; never show only an ID."""
    code, name = row["station"], re.sub(r"\s+", " ", row.get("name") or "").strip()
    airports = {"KFCM": "Eden Prairie · Flying Cloud Airport", "KMIC": "Crystal · Airport",
                "KMSP": "MSP Airport", "KSTP": "St. Paul · Downtown Airport"}
    if code in airports:
        return airports[code]
    name = re.sub(r"\s+[A-Z]{2}\s+(?:US|HE|TG)(?:\s+.*)?$", "", name)
    name = re.sub(r"\s*\(HE\d+[A-Z]?\)", "", name)
    if row.get("network") == "CWOP":
        parts = name.split(" ", 1)
        if len(parts) == 2 and re.search(r"\d", parts[0]):
            name = parts[1]
    if name.isupper():
        name = name.title()
    return name or "Unnamed local station"


def normalize(rows, now):
    latest = {}
    for source in rows:
        row = dict(source)
        lat, lon = row.get("lat"), row.get("lon")
        if not finite(lat, -90, 90) or not finite(lon, -180, 180):
            continue
        distance = distance_miles(lat, lon)
        if distance > RADIUS_MILES:
            continue
        try:
            stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            continue
        if stamp.tzinfo is None or stamp > now:
            continue
        code = row.get("station")
        if not code:
            continue
        row.update(distanceMiles=round(distance, 2), observedAt=iso(stamp), displayName=place(row))
        for field in ("tempF", "dewpointF"):
            if not finite(row.get(field), -150, 150):
                row[field] = None
        if row["tempF"] is not None and row["dewpointF"] is not None and row["dewpointF"] > row["tempF"]+3.6:
            row["dewpointF"] = None
        wind = row.get("wind") or {}
        row["wind"] = {"speedMph": wind.get("speedMph") if finite(wind.get("speedMph"), 0, 230) else None,
                       "direction": wind.get("direction") if finite(wind.get("direction"), 0, 360) else None}
        old = latest.get(code)
        priority = int(row.get("network") == "Airport ASOS")
        if old is None or (row["observedAt"], priority) >= (old["observedAt"], int(old.get("network") == "Airport ASOS")):
            latest[code] = row
    return sorted(latest.values(), key=lambda row: (row["distanceMiles"], row["displayName"], row["station"]))


def candidate(rows, now):
    stations = normalize(rows, now)
    useful = lambda row: any(row.get(k) is not None for k in ("tempF", "dewpointF")) or row["wind"]["speedMph"] is not None
    newest = max((row["observedAt"] for row in stations if useful(row)), default=None)
    newest_time = datetime.fromisoformat(newest.replace("Z", "+00:00")) if newest else None
    included = []
    for row in stations:
        stamp = datetime.fromisoformat(row["observedAt"].replace("Z", "+00:00"))
        row["included"] = useful(row) and (newest_time-stamp).total_seconds() <= MAX_SPREAD_SECONDS
        row["includedFields"] = [label for key, label in (("tempF", "Temperature"), ("dewpointF", "Dewpoint"))
                                 if row["included"] and row[key] is not None]
        if row["included"] and row["wind"]["speedMph"] is not None:
            row["includedFields"].append("Wind")
        row["status"] = ("Included" if row["included"] else
                         "No usable measurements / failed QC" if not useful(row) else "Over 15 min behind group")
        if row["included"]:
            included.append(row)
    temperatures = [row["tempF"] for row in included if row["tempF"] is not None]
    dewpoints = [row["dewpointF"] for row in included if row["dewpointF"] is not None]
    speeds = [row["wind"]["speedMph"] for row in included if row["wind"]["speedMph"] is not None]
    vectors = [(row["wind"]["speedMph"], math.radians(row["wind"]["direction"])) for row in included
               if row["wind"]["speedMph"] is not None and row["wind"]["direction"] is not None]
    x = sum(speed*math.sin(direction) for speed, direction in vectors)
    y = sum(speed*math.cos(direction) for speed, direction in vectors)
    direction = math.degrees(math.atan2(x, y)) % 360 if math.hypot(x, y) > 1e-9 else None
    stamps = [datetime.fromisoformat(row["observedAt"].replace("Z", "+00:00")).timestamp() for row in included]
    mean = lambda values: sum(values)/len(values) if values else None
    available = all(len(values) >= MIN_STATIONS for values in (temperatures, dewpoints, speeds))
    return {"available": available, "observedAt": iso(datetime.fromtimestamp(mean(stamps), UTC)) if stamps else None,
            "tempF": mean(temperatures), "dewpointF": mean(dewpoints),
            "wind": {"speedMph": mean(speeds), "direction": direction},
            "stationCount": len(included), "stations": stations,
            "counts": {"temperature": len(temperatures), "dewpoint": len(dewpoints), "wind": len(speeds)},
            "timestampSpreadSeconds": max(stamps)-min(stamps) if stamps else None,
            "maxSpreadSeconds": MAX_SPREAD_SECONDS, "radiusMiles": RADIUS_MILES}


def present(saved, now):
    compatible = bool(saved and saved.get("version") == VERSION)
    state = candidate(saved.get("reports", []) if compatible else [], now)
    good = (state if state["available"] else saved.get("lastGood")) if compatible else None
    checked = saved.get("checkedAt") if compatible else None
    return {"version": VERSION, "current": good, "candidate": state, "available": good is not None,
            "held": good is not None and not state["available"], "checkedAt": checked, "serverTime": iso(now),
            "collectorDelayed": not checked or (now-datetime.fromisoformat(checked.replace("Z", "+00:00"))).total_seconds() > 300,
            "sourceFailures": saved.get("sourceFailures", []) if compatible else [],
            "radiusMiles": RADIUS_MILES, "center": list(CENTER), "minStationsPerField": MIN_STATIONS}


def collect(store, now, download=None):
    """Fetch current/previous hourly files, including this hour's live records."""
    import regional_madis
    from madis_observations import parse_file as parse_asos, SOURCE as ASOS_SOURCE
    previous = store.read_json(KEY) or {}
    compatible = previous.get("version") == VERSION
    rows = list(previous.get("reports", [])) if compatible else []
    metadata = dict(previous.get("files", {})) if compatible else {}
    hour = now.replace(minute=0, second=0, microsecond=0)
    failures = []
    download = download or regional_madis.fetch
    bounds = (CENTER[0]-.15, CENTER[1]-.21, CENTER[0]+.15, CENTER[1]+.21)
    for kind, source in (("mesonet", regional_madis.SOURCE), ("asos", ASOS_SOURCE)):
        for offset in (0, 1):
            target = hour-timedelta(hours=offset)
            name = kind+"/"+target.strftime("%Y%m%d_%H00.gz")
            try:
                payload, info = download(source+target.strftime("%Y%m%d_%H00.gz"), metadata.get(name))
                if payload is None:
                    continue
                if kind == "mesonet":
                    fresh = regional_madis.parse_file(payload, now, window_start=now-timedelta(hours=2),
                                                      window_end=now+timedelta(microseconds=1), bounds=bounds, include_invalid=True)
                else:
                    raw = parse_asos(payload, None, now)
                    fresh = [{"station": row["icaoId"], "name": row.get("name"), "lat": row["lat"], "lon": row["lon"],
                              "time": iso(datetime.fromtimestamp(row["obsTime"], UTC)),
                              "tempF": row["temp"]*1.8+32 if row["temp"] is not None else None,
                              "dewpointF": row["dewp"]*1.8+32 if row["dewp"] is not None else None,
                              "wind": {"speedMph": row["wspd"]*1.150779 if row["wspd"] is not None else None,
                                       "direction": row["wdir"]}, "source": "NOAA MADIS", "network": "Airport ASOS"}
                             for row in raw if row["obsTime"] % 300 == 0]
                rows.extend(fresh)
                metadata[name] = info
            except Exception as error:
                failures.append({"file": name, "error": str(error)[:160]})
    rows = normalize(rows, now)
    state = candidate(rows, now)
    good = state if state["available"] else previous.get("lastGood") if compatible else None
    valid_files = {kind+"/"+(hour-timedelta(hours=i)).strftime("%Y%m%d_%H00.gz") for kind in ("mesonet", "asos") for i in (0, 1)}
    saved = {"version": VERSION, "reports": rows, "lastGood": good, "checkedAt": iso(now),
             "sourceFailures": failures, "files": {key: value for key, value in metadata.items() if key in valid_files}}
    store.write_json(KEY, saved)
    return present(saved, now)


def main():
    from realtime import get_store
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET must be set")
    result = collect(store, datetime.now(UTC))
    print("Included", result["candidate"]["stationCount"], "of", len(result["candidate"]["stations"]), "local stations", flush=True)
    if not result["available"]:
        raise ValueError("Waiting for at least three coherent usable stations per field: "+str(result["sourceFailures"]))


if __name__ == "__main__":
    main()
