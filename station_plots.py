"""Hourly IEM and Wisconet station observations, collected in bulk.

IEM currents explicitly supply tmpf/dwpf in Fahrenheit and sknt in knots.
This feed does not expose the complete MADIS QC flags. Checks here reject
missing, impossible, future and stale values; they are not full MADIS QC.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import csv
import io
import json
import logging
import math
import re
from urllib.parse import urlencode

from metar_clouds import BOUNDS, EXCLUDED_STATIONS

SOURCE = "https://mesonet.agron.iastate.edu/api/1/currents.json"
STATES = ("MN", "WI", "IA", "ND", "SD", "NE", "IL", "MI", "IN", "OH", "KS", "MO")
MAX_AGE = timedelta(minutes=90)
VERSION = 4
WINDOW = timedelta(minutes=30)
logger = logging.getLogger(__name__)


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp(text):
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and low <= value <= high else None


def in_hour_window(stamp, hour):
    return hour-WINDOW <= stamp < hour


def parse(payload, now):
    document = json.loads(payload)
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        raise ValueError("Invalid IEM currents response")
    latest = {}
    for raw in document["data"]:
        if not isinstance(raw, dict):
            continue
        station, network = raw.get("station"), raw.get("network")
        if not isinstance(station, str) or not re.fullmatch(r"[A-Z0-9_-]{1,24}", station):
            continue
        if not isinstance(network, str) or not re.fullmatch(r"[A-Z0-9_]{1,24}", network):
            continue
        # Standard US airport IDs retain their ICAO K prefix. Mesonet IDs
        # retain their original spelling and are keyed with their network.
        if network.endswith("_ASOS") and len(station) == 3:
            station = "K" + station
        if station in EXCLUDED_STATIONS:
            continue
        lat, lon = number(raw.get("lat"), 40, 50), number(raw.get("lon"), -100, -85)
        observed = timestamp(raw.get("utc_valid"))
        if lat is None or lon is None or observed is None or not now-MAX_AGE <= observed <= now:
            continue
        temp = number(raw.get("tmpf"), -130, 140)
        dew = number(raw.get("dwpf"), -148, 140)
        if temp is not None and dew is not None and dew > temp + 1:
            dew = None
        speed = number(raw.get("sknt"), 0, 200)
        direction = number(raw.get("drct"), 0, 360)
        if temp is None and dew is None and speed is None:
            continue  # Rain-only / river-level-only sites have no plot values.
        key = network + ":" + station
        item = {"station": station, "stationKey": key, "network": network,
                "name": str(raw.get("name") or station)[:160],
                "state": str(raw.get("state") or "")[:2],
                "lat": lat, "lon": lon, "time": iso(observed),
                "tempF": temp, "dewpointF": dew,
                "wind": {"speedKnots": speed, "speedMph": speed * 1.150779448 if speed is not None else None,
                         "direction": direction, "variable": bool(re.search(r"\bVRB\d", str(raw.get("raw") or "")))},
                "source": "Iowa Environmental Mesonet", "quality": "range-and-age-checked",
                "reportType": ("SPECI" if str(raw.get("raw") or "").startswith("SPECI") else
                               "HFMETAR" if "MADISHF" in str(raw.get("raw") or "") else
                               "METAR" if network.endswith("_ASOS") and raw.get("raw") else None)}
        if key not in latest or item["time"] >= latest[key]["time"]:
            latest[key] = item
    return list(latest.values())


def valid_saved(row, reference, age=MAX_AGE):
    stamp = timestamp(row.get("time"))
    return (stamp is not None and reference-age <= stamp < reference
            and row.get("station") not in EXCLUDED_STATIONS
            and number(row.get("lat"), 40, 50) is not None
            and number(row.get("lon"), -100, -85) is not None)


def history(frames, hour):
    selected = {}
    analyses = {}
    for frame in frames:
        reference = timestamp(frame.get("hour"))
        if reference is None or reference > hour:
            continue
        if frame.get("analysisUrl"):
            analyses[iso(reference)] = frame["analysisUrl"]
        for row in frame.get("stations", []):
            if not valid_saved(row, reference, WINDOW):
                continue
            key = (iso(reference), row["stationKey"])
            if key not in selected or row["time"] >= selected[key]["time"]:
                selected[key] = row
    return [{"hour": iso(hour-timedelta(hours=i)), **({"analysisUrl": analyses[iso(hour-timedelta(hours=i))]} if iso(hour-timedelta(hours=i)) in analyses else {}), "stations": sorted(
             (row for (label, _), row in selected.items() if label == iso(hour-timedelta(hours=i))),
             key=lambda row: row["stationKey"])} for i in reversed(range(12))]


RWIS_NETWORKS = ("MN_RWIS", "WI_RWIS", "IA_RWIS", "SD_RWIS", "NE_RWIS", "IL_RWIS", "IN_RWIS")


def rwis_url(network, hour, hours=1):
    return "https://mesonet.agron.iastate.edu/cgi-bin/request/rwis.py?" + urlencode({
        "network": network, "stations": "_ALL", "tz": "UTC", "what": "download", "src": "atmos",
        "sts": iso(hour-timedelta(hours=hours-1)-WINDOW), "ets": iso(hour), "vars": "tmpf,dwpf,sknt,drct", "gis": "true"})


def parse_rwis(payload, network, now, hours=1):
    # Bulk archive recovers the requested window even after a currents feed
    # has replaced its :40 observation with the next :00 observation.
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    if text.strip().startswith("Sorry, no results found"):
        return []
    reader = csv.DictReader(io.StringIO(text))
    required = {"station", "obtime", "longitude", "latitude", "tmpf", "dwpf", "sknt", "drct"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("Invalid RWIS archive response")
    grouped = {}
    for raw in reader:
        def numeric(key):
            try:
                return float(raw[key])
            except (TypeError, ValueError):
                return None
        stamp = raw.get("obtime", "").replace(" ", "T")
        if not stamp.endswith("Z") and "+" not in stamp:
            stamp += "Z"
        observed = timestamp(stamp)
        if observed is None:
            continue
        target = observed.replace(minute=0, second=0, microsecond=0)+timedelta(hours=1)
        if not now-timedelta(hours=hours-1) <= target <= now or not in_hour_window(observed, target):
            continue
        grouped.setdefault(target, []).append({"station": raw["station"], "network": network, "state": network[:2],
                     "utc_valid": stamp, "lat": numeric("latitude"), "lon": numeric("longitude"),
                     "tmpf": numeric("tmpf"), "dwpf": numeric("dwpf"), "sknt": numeric("sknt"), "drct": numeric("drct")})
    return [row for target, rows in grouped.items() for row in parse(json.dumps({"data": rows}), target)]


def collect(download, now, previous=None, airport_rows=None, airport_failed=False):
    import wisconet
    # Read feeds once for this UTC hour; accept only :30 through :59, even if
    # deployment or a retry happens later. Never re-label newer readings.
    hour = now.replace(minute=0, second=0, microsecond=0)
    previous = previous or {}
    fresh, failed, successes = [], [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        work = {state: pool.submit(lambda st=state: parse(download(SOURCE + "?state=" + st), now)) for state in STATES}
        for network in RWIS_NETWORKS:
            work[network] = pool.submit(lambda net=network: parse_rwis(download(rwis_url(net, hour, hours=12)), net, hour, hours=12))
        work["WISCONET"] = pool.submit(lambda: wisconet.parse(download(wisconet.url(hour)), hour))
        for source, result in work.items():
            try:
                fresh.extend(result.result())
                successes.append(source)
            except Exception:
                failed.append(source)
                logger.exception("Station collection failed for %s", source)
    known_rows = [r for f in previous.get("history", []) for r in f.get("stations", [])]
    named = {row["stationKey"]: row for row in known_rows+fresh if row.get("name") and row["name"] != row["station"]}
    for row in fresh:
        if row["name"] == row["station"] and row["stationKey"] in named:
            row["name"] = named[row["stationKey"]]["name"]
    metadata = {row["station"]: row for row in fresh if row["network"].endswith("_ASOS")}
    selected = {}
    def add(row):
        if not valid_saved(row, hour, WINDOW):
            return
        wind = row.get("wind") or {}
        if all(value is None for value in (row.get("tempF"), row.get("dewpointF"),
                                           wind.get("speedMph"), wind.get("speedKnots"))):
            return
        if row["network"].endswith("_ASOS") and row.get("reportType") != "METAR":
            return
        key = row["stationKey"]
        rank = (row.get("source") == "NOAA Aviation Weather Center", row["time"])
        old = selected.get(key)
        if old is None or rank >= (old.get("source") == "NOAA Aviation Weather Center", old["time"]):
            selected[key] = row
    for row in fresh:
        add(row)
    for row in airport_rows or []:
        if not valid_saved(row, hour, WINDOW) or row.get("reportType") != "METAR":
            continue
        original = metadata.get(row["station"], {})
        network = original.get("network", "AWC_METAR")
        add({"station": row["station"], "stationKey": network + ":" + row["station"],
             "network": network, "name": original.get("name", row["station"]), "state": original.get("state", ""),
             "lat": row["lat"], "lon": row["lon"], "time": row["time"],
             "tempF": row.get("tempF"), "dewpointF": row.get("dewpointF"), "wind": row["wind"],
             "source": "NOAA Aviation Weather Center", "reportType": "METAR", "quality": "range-and-age-checked"})
    if airport_failed:
        failed.append("AWC METAR")
    # Retain only still-valid reports from the same 30-minute window when a
    # source fails. Previous hours are kept on their own historical positions.
    for row in previous.get("stations", []):
        source_failed = (row.get("network") == "WISCONET" and "WISCONET" in failed) or (
            row.get("network") != "WISCONET" and row.get("state") in failed)
        if source_failed:
            add(row)
    if not selected:
        raise ValueError("No station reports in the 30-minute hourly window; previous data retained")
    # Late RWIS reports must repair their genuine past-hour frames. Never
    # carry them into the newest hour just to make the map look populated.
    saved = {frame["hour"]: {r["stationKey"]: r for r in frame.get("stations", [])}
             for frame in previous.get("history", [])}
    repaired = {}
    def measurement(row):
        return {key: row.get(key) for key in ("stationKey", "time", "lat", "lon", "tempF", "dewpointF", "wind")}
    for row in fresh:
        if not row["network"].endswith("_RWIS"):
            continue
        stamp = timestamp(row["time"])
        target = stamp.replace(minute=0, second=0, microsecond=0)+timedelta(hours=1)
        if not hour-timedelta(hours=11) <= target < hour or not in_hour_window(stamp, target):
            continue
        label = iso(target)
        old = saved.get(label, {}).get(row["stationKey"])
        if old and (old["time"] > row["time"] or measurement(old) == measurement(row)):
            continue
        repaired.setdefault(label, []).append(row)
    frames = [{k: v for k, v in frame.items() if k != "analysisUrl" or frame["hour"] not in repaired}
              for frame in previous.get("history", [])]
    frames += [{"hour": label, "stations": rows} for label, rows in repaired.items()]
    frames += [{"hour": iso(hour), "stations": list(selected.values())}]
    frames = history(frames, hour)
    coverage = [{"network": net, "available": len({r["stationKey"] for r in fresh if r["network"] == net}),
                 "selected": sum(r["network"] == net for r in selected.values()),
                 "latestReportTime": max((r["time"] for r in fresh if r["network"] == net), default=None)}
                for net in sorted({r["network"] for r in fresh} | {r["network"] for r in selected.values()})]
    delayed = [r["network"] for r in coverage if r["network"].endswith("_RWIS") and not r["selected"]
               and r["latestReportTime"] and timestamp(r["latestReportTime"]) < hour-WINDOW]
    return {"version": VERSION, "collectionMode": "hourly-window", "hour": iso(hour), "checkedAt": iso(now), "bounds": BOUNDS,
            "stations": frames[-1]["stations"], "history": frames, "windowMinutes": 30,
            "source": "Iowa Environmental Mesonet, NOAA AWC and UW–Madison Wisconet",
            "sourceUrl": SOURCE, "successfulStates": [s for s in successes if s in STATES],
            "failedStates": [s for s in failed if s in STATES], "failedSources": failed,
            "coverage": coverage, "delayedNetworks": delayed, "backfilledHours": sorted(repaired)}


def current(data, now):
    # A delayed collector leaves the last genuine snapshot on its original
    # hour; the API never invents a new hour from older station readings.
    hour = timestamp(data.get("hour")) or now.replace(minute=0, second=0, microsecond=0)
    frames = history(data.get("history", []), hour)
    return {key: value for key, value in data.items() if key not in ("pendingHour", "stations", "history", "maxAgeMinutes")} | {
        "history": frames, "stations": frames[-1]["stations"], "windowMinutes": 30}
