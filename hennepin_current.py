"""Five-minute prepared averages of the twelve user-selected Hennepin West sites."""
from datetime import datetime, timedelta, timezone
import json
import math
from statistics import median
from urllib.error import HTTPError

from local_current import finite, iso

VERSION = "hennepin-selected-twelve-v1"
KEY = "live/hennepin-current.json"
STATIONS = {
    "HPN02": "Maple Grove", "HPN07": "MSP Airport", "HPN09": "Plymouth",
    "HPN20": "Hopkins", "HPN21": "Fridley", "HPN24": "Edina",
    "HPN25": "Minnetonka", "HPN26": "Bloomington", "HPN38": "Eden Prairie",
    "HPN39": "Minneapolis", "HPN42": "Minneapolis–Camden", "HPN47": "Golden Valley",
}
UTC = timezone.utc
MIN_STATIONS = 9
MAX_SPREAD = timedelta(minutes=10)
MAX_AGE = timedelta(minutes=45)
FIELDS = ("tempF", "dewpointF", "wind")


def stamp(text):
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Observation time requires a timezone")
    return value.astimezone(UTC)


def normalize(rows, now):
    chosen = {}
    for source in rows:
        identifier = source.get("station")
        if identifier not in STATIONS or source.get("network") != "Hennepin West":
            continue
        try:
            observed = stamp(source["time"])
        except (ValueError, TypeError, KeyError):
            continue
        if not now-timedelta(hours=2) <= observed <= now:
            continue
        row = {**source, "time": iso(observed), "displayName": STATIONS[identifier]}
        def failed(name):
            qc = row.get("qc", {}).get(name, {})
            return qc.get("descriptor") in ("X", "Q", "B") or finite(qc.get("results"), 1)
        for field in ("tempF", "dewpointF"):
            if not finite(row.get(field), -150, 150) or failed("temperature" if field == "tempF" else "dewpoint"):
                row[field] = None
        if row["tempF"] is not None and row["dewpointF"] is not None and row["dewpointF"] > row["tempF"]+.2:
            row["dewpointF"] = None
        wind = row.get("wind") or {}
        row["wind"] = {"speedMph": wind.get("speedMph") if finite(wind.get("speedMph"), 0, 230) and not failed("windSpeed") else None,
                       "direction": wind.get("direction") if finite(wind.get("direction"), 0, 360) and not failed("windDir") else None}
        key = (identifier, row["time"])
        chosen[key] = row  # Later copy includes any NOAA QC correction.
    return sorted(chosen.values(), key=lambda row: (row["time"], row["station"]))


def nearby(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 3958.7613*2*math.asin(math.sqrt(min(1, h))) <= 15


def candidate(reports, now, previous_watch=None):
    latest = {}
    for row in normalize(reports, now):
        latest[row["station"]] = row
    useful = lambda r: any(r.get(k) is not None for k in ("tempF", "dewpointF")) or r["wind"]["speedMph"] is not None
    recent = [r for r in latest.values() if useful(r) and now-stamp(r["time"]) <= MAX_AGE]
    newest = max((stamp(r["time"]) for r in recent), default=now)
    aligned = [r for r in recent if newest-stamp(r["time"]) <= MAX_SPREAD]
    aligned_ids = {r["station"] for r in aligned}
    watch, stations = {}, []
    previous_watch = previous_watch or {}
    for identifier, name in STATIONS.items():
        source = latest.get(identifier)
        row = {**source} if source else {"station": identifier, "displayName": name, "tempF": None,
                "dewpointF": None, "wind": {"speedMph": None, "direction": None}, "time": None}
        row["includedFields"], row["reasons"], row["warnings"] = [], {}, []
        if any(q.get("descriptor") in ("Z", "C") for q in row.get("qc", {}).values()):
            row["warnings"].append("Some measurements have preliminary or limited NOAA checks")
        for field in FIELDS:
            value = row.get(field) if field != "wind" else row["wind"]["speedMph"]
            reason = None
            if source is None:
                reason = "No report available"
            elif now-stamp(row["time"]) > MAX_AGE:
                reason = "Report over 45 minutes old"
            elif identifier not in aligned_ids:
                reason = "Over 10 minutes behind the group"
            elif value is None:
                reason = "Missing value or failed NOAA quality check"
            elif field == "wind" and value >= .5 and row["wind"]["direction"] is None:
                reason = "Wind direction unavailable"
            if reason:
                row["reasons"][field] = reason
                continue
            if field in ("tempF", "dewpointF"):
                neighbors = [s[field] for s in aligned if s["station"] != identifier and s.get(field) is not None
                             and finite(s.get("lat")) and finite(s.get("lon"))
                             and finite(row.get("lat")) and finite(row.get("lon")) and nearby(row, s)]
                isolated = False
                if len(neighbors) >= 3:
                    center = median(neighbors)
                    spread = median(abs(v-center) for v in neighbors)
                    isolated = abs(value-center) > max(6, 4*1.4826*spread)
                key = identifier+":"+field
                old = previous_watch.get(key, {})
                count = (old.get("count", 0)+(row["time"] != old.get("time"))) if isolated else 0
                count = min(3, count)
                watch[key] = {"time": row["time"], "count": count}
                if count >= 3:
                    row["reasons"][field] = "Persistent isolated difference from nearby stations"
                    continue
                if count:
                    row["warnings"].append(field+": monitoring isolated difference")
            row["includedFields"].append(field)
        stations.append(row)
    values = {field: [r for r in stations if field in r["includedFields"]] for field in FIELDS}
    counts = {field: len(rows) for field, rows in values.items()}
    mean = lambda numbers: sum(numbers)/len(numbers) if numbers else None
    wind_rows = values["wind"]
    speeds = [r["wind"]["speedMph"] for r in wind_rows]
    x = sum(r["wind"]["speedMph"]*math.sin(math.radians(r["wind"]["direction"] or 0)) for r in wind_rows)
    y = sum(r["wind"]["speedMph"]*math.cos(math.radians(r["wind"]["direction"] or 0)) for r in wind_rows)
    coherence = math.hypot(x, y)/sum(speeds) if sum(speeds) else 0
    direction = math.degrees(math.atan2(x, y)) % 360 if coherence >= .15 else None
    included = [r for r in stations if r["includedFields"]]
    times = [stamp(r["time"]).timestamp() for r in included]
    state = {"available": all(v >= MIN_STATIONS for v in counts.values()),
             "observedAt": iso(datetime.fromtimestamp(mean(times), UTC)) if times else None,
             "tempF": mean([r["tempF"] for r in values["tempF"]]),
             "dewpointF": mean([r["dewpointF"] for r in values["dewpointF"]]),
             "wind": {"speedMph": mean(speeds), "direction": direction}, "counts": counts,
             "stationCount": len(included), "stations": stations,
             "timestampSpreadSeconds": max(times)-min(times) if times else None}
    return state, watch


def present(saved, now):
    saved = saved if saved and saved.get("version") == VERSION else {}
    current = saved.get("lastGood")
    latest, _ = candidate(saved.get("reports", []), now, saved.get("watch"))
    checked = saved.get("checkedAt")
    delayed = not checked or now-stamp(checked) > timedelta(minutes=10)
    old = bool(current and now-stamp(current["observedAt"]) > MAX_AGE)
    return {"version": VERSION, "current": current, "candidate": latest, "available": bool(current),
            "held": bool(current and (not latest["available"] or old)), "collectorDelayed": delayed,
            "checkedAt": checked, "serverTime": iso(now), "sourceFailures": saved.get("sourceFailures", []),
            "selectedStations": STATIONS, "minStationsPerField": MIN_STATIONS,
            "maxSpreadMinutes": 10, "maxAgeMinutes": 45, "collectionMinutes": 5}


def collect(store, now, download=None, parse=None):
    import regional_madis
    download, parse = download or regional_madis.fetch, parse or regional_madis.parse_file
    previous = store.read_json(KEY) or {}
    if previous.get("version") != VERSION:
        previous = {}
    files = previous.get("files", {})
    reports, failures, used_files = list(previous.get("reports", [])), [], {}
    hour = now.replace(minute=0, second=0, microsecond=0)
    # The current file normally supplies all selected sites later in the hour.
    # Fetch the previous file only while this hour's station set is incomplete.
    current_ids = set()
    for offset in (0, 1):
        if offset and current_ids == set(STATIONS):
            break
        name = (hour-timedelta(hours=offset)).strftime("%Y%m%d_%H00.gz")
        old = files.get(name, {})
        try:
            payload, metadata = download(regional_madis.SOURCE+name, old.get("metadata"))
            fresh = old.get("reports", []) if payload is None else parse(payload, now,
                window_start=now-timedelta(hours=2), window_end=now+timedelta(microseconds=1),
                bounds=(44.7, -93.6, 45.2, -93.15), station_ids=set(STATIONS), include_qc=True,
                include_invalid=True, excluded_stations=())
            reports.extend(fresh)
            used_files[name] = {"metadata": metadata, "reports": fresh}
            if not offset:
                current_ids = {r["station"] for r in fresh if r["station"] in STATIONS and useful_current(r, hour)}
        except Exception as error:
            if not (isinstance(error, HTTPError) and error.code == 404 and offset == 0):
                failures.append({"file": name, "error": str(error)[:160]})
            if old:
                used_files[name] = old
    reports = normalize(reports, now)
    latest, watch = candidate(reports, now, previous.get("watch"))
    good = latest if latest["available"] else previous.get("lastGood")
    saved = {"version": VERSION, "reports": reports, "lastGood": good, "watch": watch,
             "checkedAt": iso(now), "files": used_files, "sourceFailures": failures}
    if good is None and not reports:
        raise ValueError("No selected Hennepin West data available; previous state retained")
    store.write_json(KEY, saved)
    result = present(saved, now)
    return {"available": result["available"], "held": result["held"], "counts": latest["counts"],
            "observedAt": good["observedAt"] if good else None, "sourceFailures": failures}


def useful_current(row, hour):
    return stamp(row["time"]) >= hour and any(row.get(f) is not None for f in ("tempF", "dewpointF"))


if __name__ == "__main__":
    from realtime import get_store
    store = get_store()
    if store is None:
        raise SystemExit("WEATHER_DATA_BUCKET is required")
    result = collect(store, datetime.now(UTC))
    print(json.dumps(result), flush=True)
    if not result["available"] or result["held"]:
        raise SystemExit("Waiting for nine usable selected stations per field; the existing website is unchanged")
