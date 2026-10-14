"""Open IEM station observations, collected in bulk rather than per visitor.

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
VERSION = 1
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
                "source": "Iowa Environmental Mesonet", "quality": "range-and-age-checked"}
        if key not in latest or item["time"] >= latest[key]["time"]:
            latest[key] = item
    return list(latest.values())


def valid_saved(row, reference, age=MAX_AGE):
    stamp = timestamp(row.get("time"))
    return (stamp is not None and reference-age <= stamp <= reference
            and row.get("station") not in EXCLUDED_STATIONS
            and number(row.get("lat"), 40, 50) is not None
            and number(row.get("lon"), -100, -85) is not None)


def history(rows, now):
    end = now.replace(minute=0, second=0, microsecond=0)
    selected = {}
    for row in rows:
        if not valid_saved(row, now, timedelta(hours=13)):
            continue
        observed = timestamp(row["time"])
        hour = observed.replace(minute=0, second=0, microsecond=0)
        if observed != hour:
            hour += timedelta(hours=1)
        key = (iso(hour), row["stationKey"])
        if key not in selected or row["time"] >= selected[key]["time"]:
            selected[key] = row
    def frame(hour):
        return {"hour": iso(hour), "stations": sorted(
            (row for (label, _), row in selected.items() if label == iso(hour)),
            key=lambda row: row["stationKey"])}
    return [frame(end-timedelta(hours=i)) for i in reversed(range(12))], frame(end+timedelta(hours=1))


def collect(download, now, previous=None):
    previous = previous if previous and previous.get("version") == VERSION else {}
    fresh, failed, successes = [], [], []
    def fetch_state(state):
        return parse(download(SOURCE + "?state=" + state), now)
    with ThreadPoolExecutor(max_workers=3) as pool:
        work = {state: pool.submit(fetch_state, state) for state in STATES}
        for state, result in work.items():
            try:
                fresh.extend(result.result())
                successes.append(state)
            except Exception:
                failed.append(state)
                logger.exception("Station collection failed for %s", state)
    if not fresh:
        raise ValueError("No fresh station weather reports; previous data retained")
    # A failed state request may retain recent values, with their original
    # timestamps and a visible partial-feed notice. Successful feeds replace
    # their prior station lists, including stations no longer reporting.
    carried = [row for row in previous.get("stations", [])
               if row.get("state") in failed and valid_saved(row, now)]
    current = {row["stationKey"]: row for row in carried + fresh}
    rows = [row for frame in previous.get("history", []) for row in frame["stations"]]
    rows += previous.get("pendingHour", {}).get("stations", []) + list(current.values())
    frames, pending = history(rows, now)
    return {"version": VERSION, "checkedAt": iso(now), "bounds": BOUNDS,
            "stations": sorted(current.values(), key=lambda row: row["stationKey"]),
            "history": frames, "pendingHour": pending,
            "source": "Iowa Environmental Mesonet", "sourceUrl": SOURCE,
            "maxAgeMinutes": 90, "successfulStates": successes, "failedStates": failed}


def current(data, now):
    frames, _ = history([row for frame in data.get("history", []) for row in frame["stations"]]
                        + data.get("pendingHour", {}).get("stations", []), now)
    return {key: value for key, value in data.items() if key not in ("pendingHour", "stations", "history")} | {
        "history": frames, "stations": [row for row in data.get("stations", []) if valid_saved(row, now)]}
