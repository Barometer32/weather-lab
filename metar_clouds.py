"""One hourly bulk METAR collection for Upper Midwest observations and maps."""
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import math
import re
import xml.etree.ElementTree as ET

SOURCE_URL = "https://aviationweather.gov/data/cache/metars.cache.xml.gz"
# Original regional extent, shared by cloud ceilings and weather plots.
BOUNDS = [[40, -100], [50, -85]]
COVERS = {"CLR", "SKC", "FEW", "SCT", "BKN", "OVC", "VV", "NSC", "NCD", "CAVOK"}
# User-excluded unreliable cloud station. Enforce on fresh and retained history.
EXCLUDED_STATIONS = frozenset({"KCFE", "KFCE", "KSGS"})


def included_station(station):
    return (bool(re.fullmatch(r"[A-Z0-9]{3,5}", station))
            and station not in EXCLUDED_STATIONS)


def in_region(row):
    return (included_station(row["station"])
            and value(row.get("lat"), 40, 50) is not None
            and value(row.get("lon"), -100, -85) is not None)


def cloud_summary(row):
    """Map the lowest ceiling, while preserving every layer for the popup."""
    layers = row.get("layers", [])
    ceilings = [layer for layer in layers if layer["cover"] in ("BKN", "OVC", "VV")]
    candidates = ceilings or layers
    layer = min(candidates, key=lambda item: (item["baseFtAGL"] is None,
                                             item["baseFtAGL"] or 0)) if candidates else None
    from app import valid_number, valid_dewpoint, wind_mean, metar_precision
    row = metar_precision(row)
    temperature = row.get("temp")
    from cloud_conditions import summarize
    return {**row, **summarize(row), "mapLayer": layer, "hasCeiling": bool(ceilings),
            "tempF": round(temperature * 9 / 5 + 32, 1) if valid_number(temperature, -90, 60) else None,
            "dewpointF": round(row["dewp"] * 9 / 5 + 32, 1) if valid_dewpoint(row) else None,
            "wind": wind_mean([row])}


def value(text, low, high):
    try:
        number = float(text)
        return number if math.isfinite(number) and low <= number <= high else None
    except (TypeError, ValueError):
        return None


def parse_reports(xml, now, hours=13):
    if xml.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=BytesIO(xml)) as file:
            xml = file.read(30_000_001)
    if len(xml) > 30_000_000:
        raise ValueError("METAR cache exceeds the expected size")
    root = ET.fromstring(xml)
    if root.find("errors") is not None and list(root.find("errors")):
        raise ValueError("AWC returned an error")
    entries = []
    for row in root.findall(".//METAR"):
        station = row.findtext("station_id", "")
        if not included_station(station):
            continue
        lat, lon = value(row.findtext("latitude"), 40, 50), value(row.findtext("longitude"), -100, -85)
        if lat is None or lon is None:
            continue
        try:
            stamp = datetime.fromisoformat(row.findtext("observation_time", "").replace("Z", "+00:00"))
            if stamp.tzinfo is None or not now-timedelta(hours=hours) <= stamp <= now:
                continue
            stamp = stamp.astimezone(timezone.utc)
        except ValueError:
            continue
        if row.findtext("metar_type", "METAR") not in ("METAR", "SPECI"):
            continue
        raw = row.findtext("raw_text", "").split(" RMK")[0]
        if re.search(r"\bNIL\b", raw):
            continue
        layers = []
        for sky in row.findall("sky_condition"):
            cover = sky.get("sky_cover", "")
            if cover == "OVX":
                cover = "VV"
            if cover not in COVERS:
                continue
            base = value(sky.get("cloud_base_ft_agl"), 0, 60000)
            if cover in ("CLR", "SKC", "NSC", "NCD", "CAVOK"):
                base = None
            if cover == "VV":
                base = value(row.findtext("vert_vis_ft"), 0, 60000) if row.findtext("vert_vis_ft") is not None else base
            layers.append({"cover": cover, "baseFtAGL": int(base) if base is not None else None,
                           "heightType": "verticalVisibility" if cover == "VV" else "cloudBase"})
        # A missing cloud group is unknown, never an invented clear sky.
        if not layers:
            clear = re.search(r"\b(CLR|SKC|NSC|NCD|CAVOK)\b", raw)
            if clear:
                layers = [{"cover": clear.group(1), "baseFtAGL": None, "heightType": "cloudBase"}]
        layers.sort(key=lambda layer: (layer["baseFtAGL"] is None, layer["baseFtAGL"] or 0))
        item = {"station": station, "lat": lat, "lon": lon, "time": stamp.isoformat().replace("+00:00", "Z"),
                "reportType": "SPECI" if raw.startswith("SPECI") else row.findtext("metar_type", "METAR"),
                "receiptTime": row.findtext("receipt_time", ""), "layers": layers,
                "rawOb": row.findtext("raw_text", ""),
                "cloudDataAvailable": bool(layers), "cloudReportAvailable": True,
                "temp": value(row.findtext("temp_c"), -90, 60),
                "dewp": value(row.findtext("dewpoint_c"), -100, 60),
                "wspd": value(row.findtext("wind_speed_kt"), 0, 200),
                "wdir": "VRB" if row.findtext("wind_dir_degrees") == "VRB" or re.search(r"\bVRB\d{2,3}(?:G\d{2,3})?KT\b", raw) else value(row.findtext("wind_dir_degrees"), 0, 360),
                "delayed": (now-stamp).total_seconds() > 5400}
        entries.append(item)
    return entries


def reports(xml, now):
    """Complete current cache for station discovery, including off-hour sites."""
    latest = {}
    for item in parse_reports(xml, now, hours=2):
        previous = latest.get(item["station"])
        if previous is None or item["time"] >= previous["time"]:
            latest[item["station"]] = item
    if not latest:
        raise ValueError("No recent Upper Midwest METAR reports are available")
    return {"stations": sorted(latest.values(), key=lambda row: row["station"]),
            "bounds": BOUNDS, "heightUnit": "feet AGL", "checkedAt": iso(now),
            "source": "NOAA Aviation Weather Center", "sourceUrl": SOURCE_URL}


def iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


def snapshot(rows, now, checked_at=None):
    # Reuse the main observations' exact selection and correction tie breakers.
    from app import routine_hour, receipt_timestamp
    chosen = {}
    latest = now.replace(minute=0, second=0, microsecond=0)
    for row in rows:
        if not in_region(row):
            continue
        stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if stamp < now-timedelta(hours=13):
            continue
        report = {"metarType": row["reportType"], "obsTime": stamp.timestamp(), "rawOb": row.get("rawOb", ""),
                  "receiptTime": row.get("receiptTime", "")}
        hour = routine_hour(report, now)
        if hour is None:
            continue
        latest = max(latest, hour)
        rank = (abs((stamp-(hour-timedelta(minutes=7))).total_seconds()),
                -stamp.timestamp(), -receipt_timestamp(report))
        key = (iso(hour), row["station"])
        if key not in chosen or rank <= chosen[key][0]:
            chosen[key] = (rank, cloud_summary(row))
    history = []
    for i in reversed(range(12)):
        hour = iso(latest-timedelta(hours=i))
        stations = sorted((item[1] for (label, _), item in chosen.items() if label == hour),
                          key=lambda row: row["station"])
        history.append({"hour": hour, "stations": stations})
    return {"version": 3, "coverage": "upper-midwest", "mode": "routine-hourly", "history": history, "stations": history[-1]["stations"],
            "bounds": BOUNDS, "heightUnit": "feet AGL", "checkedAt": checked_at or iso(now),
            "source": "NOAA Aviation Weather Center", "sourceUrl": "https://aviationweather.gov/data/api/"}


def current(data, now):
    rows = [row for hour in data.get("history", []) for row in hour["stations"]]
    # A legacy latest-only snapshot cannot supply the requested hourly history.
    if data.get("version") not in (2, 3):
        rows = data.get("stations", [])
    target = now.replace(minute=0, second=0, microsecond=0)
    rows = [row for row in rows if datetime.fromisoformat(row["time"].replace("Z", "+00:00")) < target]
    result = snapshot(rows, target, data["checkedAt"])
    result["historyPending"] = data.get("version") != 3
    return {**result, "stale": data.get("stale", False)}


def observation_reports(data):
    """Use the very same selected regional reports for the three-site average."""
    from app import STATIONS
    return [{**row, "icaoId": row["station"], "metarType": row["reportType"],
             "obsTime": datetime.fromisoformat(row["time"].replace("Z", "+00:00")).timestamp()}
            for hour in data["history"] for row in hour["stations"]
            if row["station"] in STATIONS]


def collect(download, now, previous=None):
    """Download only the last completed hour, preserving twelve saved hours."""
    from metar_history import fetch_history
    previous = previous or {}
    target = now.replace(minute=0, second=0, microsecond=0)
    archive = fetch_history(download, now, hours=1)
    retained = [row for frame in previous.get("history", [])
                for row in frame.get("stations", []) if in_region(row)]
    data = snapshot(retained+archive["reports"], target, iso(now))
    if not data["stations"]:
        raise ValueError("No routine METARs in the completed hour's :50–:59 window; previous data retained")
    data["observationReports"] = observation_reports(data)
    data["collectionMode"] = "official-hourly-archive"
    data["hourlyTarget"] = iso(target)
    return data

