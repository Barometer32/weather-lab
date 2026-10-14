"""Hourly IEM and Wisconet station observations, collected in bulk.

IEM currents explicitly supply tmpf/dwpf in Fahrenheit and sknt in knots.
This feed does not expose the complete MADIS QC flags. Checks here reject
missing, impossible, future and stale values; they are not full MADIS QC.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re

from metar_clouds import BOUNDS, EXCLUDED_STATIONS

SOURCE = "https://mesonet.agron.iastate.edu/api/1/currents.json"
STATES = ("MN", "WI", "IA", "ND", "SD", "NE", "IL", "MI", "IN", "OH", "KS", "MO")
MAX_AGE = timedelta(minutes=90)
VERSION = 2
WINDOW = timedelta(minutes=10)
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
    return hour-WINDOW <= stamp <= hour


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
    return (stamp is not None and reference-age <= stamp <= reference
            and row.get("station") not in EXCLUDED_STATIONS
            and number(row.get("lat"), 40, 50) is not None
            and number(row.get("lon"), -100, -85) is not None)


def history(frames, hour):
    selected = {}
    for frame in frames:
        reference = timestamp(frame.get("hour"))
        if reference is None or reference > hour:
            continue
        for row in frame.get("stations", []):
            if not valid_saved(row, reference, WINDOW):
                continue
            key = (iso(reference), row["stationKey"])
            if key not in selected or row["time"] >= selected[key]["time"]:
                selected[key] = row
    return [{"hour": iso(hour-timedelta(hours=i)), "stations": sorted(
             (row for (label, _), row in selected.items() if label == iso(hour-timedelta(hours=i))),
             key=lambda row: row["stationKey"])} for i in reversed(range(12))]


def collect(download, now, previous=None, airport_rows=None, airport_failed=False):
    import wisconet
    # Read feeds once for this UTC hour; accept only :50 through :00, even if
    # deployment or a retry happens later. Never re-label newer readings.
    hour = now.replace(minute=0, second=0, microsecond=0)
    previous = previous or {}
    fresh, failed, successes = [], [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        work = {state: pool.submit(lambda st=state: parse(download(SOURCE + "?state=" + st), now)) for state in STATES}
        work["WISCONET"] = pool.submit(lambda: wisconet.parse(download(wisconet.url(hour)), hour))
        for source, result in work.items():
            try:
                fresh.extend(result.result())
                successes.append(source)
            except Exception:
                failed.append(source)
                logger.exception("Station collection failed for %s", source)
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
        rank = (row["time"], row.get("source") == "NOAA Aviation Weather Center")
        old = selected.get(key)
        if old is None or rank >= (old["time"], old.get("source") == "NOAA Aviation Weather Center"):
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
    # Retain only still-valid reports from the same ten-minute window when a
    # source fails. Previous hours are kept on their own historical positions.
    for row in previous.get("stations", []):
        source_failed = (row.get("network") == "WISCONET" and "WISCONET" in failed) or (
            row.get("network") != "WISCONET" and row.get("state") in failed)
        if source_failed:
            add(row)
    if not selected:
        raise ValueError("No station reports in the ten-minute hourly window; previous data retained")
    frames = previous.get("history", []) + [{"hour": iso(hour), "stations": list(selected.values())}]
    frames = history(frames, hour)
    return {"version": VERSION, "collectionMode": "hourly-window", "hour": iso(hour), "checkedAt": iso(now), "bounds": BOUNDS,
            "stations": frames[-1]["stations"], "history": frames, "windowMinutes": 10,
            "source": "Iowa Environmental Mesonet, NOAA AWC and UW–Madison Wisconet",
            "sourceUrl": SOURCE, "successfulStates": [s for s in successes if s in STATES],
            "failedStates": [s for s in failed if s in STATES], "failedSources": failed}


def current(data, now):
    # A delayed collector leaves the last genuine snapshot on its original
    # hour; the API never invents a new hour from older station readings.
    hour = timestamp(data.get("hour")) or now.replace(minute=0, second=0, microsecond=0)
    frames = history(data.get("history", []), hour)
    return {key: value for key, value in data.items() if key not in ("pendingHour", "stations", "history", "maxAgeMinutes")} | {
        "history": frames, "stations": frames[-1]["stations"], "windowMinutes": 10}
