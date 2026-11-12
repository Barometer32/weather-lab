"""Prepared five-minute-only raw reports; never mix routine/SPECI or T remarks."""
import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
import math
import re
from urllib.parse import urlencode
from rtmetar_stations import STATION_STATES

KEY = "live/rtmetar-v1.json"
VERSION = "rtmetar-raw-c-v1"
STATES = ("SD", "ND", "MN", "IA", "WI")
MAX_AGE_SECONDS = 3600
DELAY_SECONDS = 15 * 60
SOURCE = "Iowa Environmental Mesonet · NOAA MADIS five-minute ASOS"


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def source_url(now):
    return "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" + urlencode({
        "network": ",".join(state + "_ASOS" for state in STATES), "data": "metar",
        "sts": (now - timedelta(seconds=MAX_AGE_SECONDS)).strftime("%Y-%m-%dT%H:%MZ"),
        "ets": (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%MZ"),
        "tz": "Etc/UTC", "format": "onlycomma", "latlon": "yes", "elev": "no",
        "missing": "M", "trace": "T", "direct": "no", "report_type": "1",
    })


def number(value, low, high):
    try:
        result = float(value)
        return result if math.isfinite(result) and low <= result <= high else None
    except (ValueError, TypeError):
        return None


def parse_reports(payload, state, now):
    if state is not None and state not in STATES:
        raise ValueError("Unsupported RTMETAR state")
    rows = csv.DictReader(StringIO(payload.decode("utf-8-sig")))
    if not rows.fieldnames or not {"station", "valid", "lat", "lon", "metar"} <= set(rows.fieldnames):
        raise ValueError("Invalid five-minute raw-report response")
    reports = []
    for row in rows:
        raw = row.get("metar") or ""
        body, _, remarks = raw.partition(" RMK")
        # The request filter AND explicit provenance marker are required.
        # A timestamp divisible by five alone never establishes a rapid report.
        if not re.search(r"\bMADISHF\b", remarks) or re.match(r"\s*SPECI\b", body):
            continue
        station = row["station"].strip().upper()
        station = station if station.startswith("K") and len(station) == 4 else "K" + station
        if not re.fullmatch(r"K[A-Z0-9]{3}", station):
            continue
        report_state = STATION_STATES.get(station)
        if report_state not in STATES or state is not None and report_state != state:
            continue
        if not re.match(r"^(?:METAR\s+)?" + re.escape(station) + r"\s+", body) or re.search(r"\bNIL\b", body):
            continue
        try:
            observed = datetime.fromisoformat(row["valid"].replace("Z", "+00:00"))
            observed = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        if observed.minute % 5 or observed.second or observed.microsecond:
            continue
        if not 0 <= (now - observed).total_seconds() <= MAX_AGE_SECONDS:
            continue
        stamp = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", body)
        if not stamp or tuple(map(int, stamp.groups())) != (observed.day, observed.hour, observed.minute):
            continue
        lat, lon = number(row["lat"], 40, 50), number(row["lon"], -105, -86)
        if lat is None or lon is None:
            continue
        # Parse only the main whole-Celsius group, including M for negative.
        # Missing fields stay missing even when RMK contains a usable T group.
        group = re.search(r"(?:^|\s)(M?\d{2}|//)/(M?\d{2}|//)(?=\s|$)", body)
        def degrees(text):
            return None if text == "//" else int(text.replace("M", "-"))
        temp, dew = (degrees(group[1]), degrees(group[2])) if group else (None, None)
        if temp is not None and not -90 <= temp <= 65:
            temp = None
        if dew is not None and (not -100 <= dew <= 60 or temp is not None and dew > temp):
            dew = None
        wind = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b", body)
        speed = int(wind[2]) if wind else None
        direction = None if not wind or wind[1] == "VRB" else int(wind[1])
        if direction is not None and direction > 360:
            direction = None
        if speed is not None and speed > 250:
            speed = None
        reports.append({"station": station, "state": report_state, "lat": lat, "lon": lon,
                        "time": iso(observed), "observedEpoch": observed.timestamp(),
                        "tempC": temp, "dewpointC": dew,
                        "wind": {"speedMph": speed * 1852 / 1609.344 if speed is not None else None,
                                 "direction": direction, "variable": bool(wind and wind[1] == "VRB")},
                        "reportType": "HFMETAR", "rawOb": raw,
                        "temperatureBasis": "main-XX/XX"})
    return reports


def collect(store, now, download=None):
    if download is None:
        from app import download
    previous = store.read_json(KEY) or {}
    stamp = now.timestamp()
    latest = {s["station"]: s for s in previous.get("stations", [])
              if s.get("state") in STATES and s.get("reportType") == "HFMETAR"
              and s.get("temperatureBasis") == "main-XX/XX"
              and 0 <= stamp - s.get("observedEpoch", 0) <= MAX_AGE_SECONDS}
    # One combined request respects IEM's per-IP throttle and avoids five
    # overlapping archive downloads. Any failure retains the saved snapshot.
    reports = parse_reports(download(source_url(now)), None, now)
    errors = {}
    for report in reports:
        old = latest.get(report["station"])
        if old is None or report["observedEpoch"] >= old["observedEpoch"]:
            latest[report["station"]] = report
    snapshot = {"version": VERSION, "checkedAt": iso(now), "checkedEpoch": stamp,
                "sourceErrors": errors, "stations": [latest[key] for key in sorted(latest)]}
    store.write_json(KEY, snapshot)
    return {"stations": len(latest), "sourceErrors": errors}


def present(snapshot, now):
    if not snapshot or snapshot.get("version") != VERSION:
        raise ValueError("Five-minute raw reports have not been prepared")
    stamp = now.timestamp()
    stations = [{**s, "ageSeconds": round(stamp - s["observedEpoch"]),
                 "delayed": stamp - s["observedEpoch"] > DELAY_SECONDS}
                for s in snapshot.get("stations", []) if s.get("state") in STATES
                and s.get("reportType") == "HFMETAR" and s.get("temperatureBasis") == "main-XX/XX"
                and 0 <= stamp - s.get("observedEpoch", 0) <= MAX_AGE_SECONDS]
    return {"version": VERSION, "stations": stations, "checkedAt": snapshot["checkedAt"],
            "serverTime": iso(now), "source": SOURCE, "states": list(STATES),
            "temperatureUnit": "C", "windUnit": "mph", "reportType": "HFMETAR",
            "temperatureBasis": "main-XX/XX", "updateIntervalSeconds": 300,
            "maxAgeSeconds": MAX_AGE_SECONDS, "delaySeconds": DELAY_SECONDS,
            "sourceErrors": snapshot.get("sourceErrors", {}),
            "stale": stamp - snapshot["checkedEpoch"] > 10 * 60,
            "sourceDelayed": not stations or any(s["delayed"] for s in stations)}
