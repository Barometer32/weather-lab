"""Cloud-only routine hourly METAR history across the Upper Midwest."""
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import math
import re
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

SOURCE_URL = "https://aviationweather.gov/data/cache/metars.cache.xml.gz"
# Regional coverage around Minnesota; no airport list or station-count cap.
BOUNDS = [[40, -100], [50, -85]]
COVERS = {"CLR", "SKC", "FEW", "SCT", "BKN", "OVC", "VV", "NSC", "NCD", "CAVOK"}
# User-excluded unreliable cloud station. Enforce on fresh and retained history.
EXCLUDED_STATIONS = frozenset({"KCFE"})


def cloud_summary(row):
    """Map the lowest ceiling, while preserving every layer for the popup."""
    layers = row.get("layers", [])
    ceilings = [layer for layer in layers if layer["cover"] in ("BKN", "OVC", "VV")]
    candidates = ceilings or layers
    layer = min(candidates, key=lambda item: (item["baseFtAGL"] is None,
                                             item["baseFtAGL"] or 0)) if candidates else None
    from app import valid_number, valid_dewpoint, wind_mean
    temperature = row.get("temp")
    return {**row, "mapLayer": layer, "hasCeiling": bool(ceilings),
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
        if station in EXCLUDED_STATIONS:
            continue
        lat, lon = value(row.findtext("latitude"), 40, 50), value(row.findtext("longitude"), -100, -85)
        if not re.fullmatch(r"[A-Z0-9]{3,5}", station) or lat is None or lon is None:
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
        raise ValueError("No recent regional METAR cloud reports are available")
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
        if row["station"] in EXCLUDED_STATIONS:
            continue
        stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if stamp < now-timedelta(hours=13):
            continue
        report = {"metarType": row["reportType"], "obsTime": stamp.timestamp(),
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
        history.append({"hour": hour, "stations": stations, "metro": metro_report(stations, now, hour)})
    return {"version": 3, "history": history, "stations": history[-1]["stations"],
            "bounds": BOUNDS, "heightUnit": "feet AGL", "checkedAt": checked_at or iso(now),
            "source": "NOAA Aviation Weather Center", "sourceUrl": "https://aviationweather.gov/data/api/"}


def current(data, now):
    rows = [row for hour in data.get("history", []) for row in hour["stations"]]
    # A legacy latest-only snapshot cannot supply the requested hourly history.
    if data.get("version") not in (2, 3):
        rows = data.get("stations", [])
    result = snapshot(rows, now, data["checkedAt"])
    result["live"] = live_snapshot(data.get("liveReports", []), now)
    result["live"]["checkedAt"] = data["checkedAt"]
    result["historyPending"] = data.get("version") != 3
    return {**result, "stale": data.get("stale", False)}


def metro_position():
    # Circumcenter in a local latitude/longitude projection: approximately equal
    # ground distance from all three airports, independent of map zoom.
    import numpy as np
    points = np.array([[44.83, -93.45], [44.88, -93.22], [45.07, -93.35]])
    scale = math.cos(math.radians(points[:, 0].mean()))
    xy = np.column_stack((points[:, 1]*scale, points[:, 0]))
    center = np.linalg.solve(2*(xy[1:]-xy[0]), (xy[1:]**2).sum(axis=1)-(xy[0]**2).sum())
    return float(center[1]), float(center[0]/scale)


def metro_report(rows, now, hour=None):
    from app import STATIONS, hourly_snapshot
    from rapid_observations import current_snapshot
    reports = [{**row, "icaoId": row["station"],
                "obsTime": datetime.fromisoformat(row.get("weatherTime", row["time"]).replace("Z", "+00:00")).timestamp(),
                "metarType": row.get("reportType", "METAR")} for row in rows if row["station"] in STATIONS]
    data = hourly_snapshot(reports, datetime.fromisoformat(hour.replace("Z", "+00:00")), now) if hour else current_snapshot(reports, now)
    available = data["qa"]["allStationsUsed"]
    lat, lon = metro_position()
    return {"station": "METRO", "lat": lat, "lon": lon, "isMetro": True, "available": available,
            "tempF": data["tempF"] if available else None,
            "dewpointF": data["dewpointF"] if available else None,
            "wind": data["wind"] if available else {"speedKnots": None, "direction": None},
            "time": data.get("observedAt") or (max((row["time"] for row in rows if row["station"] in STATIONS), default=None)),
            "oldestObservedAt": data.get("oldestObservedAt"), "qa": data["qa"]}


def live_snapshot(rows, now):
    latest_weather, latest_cloud = {}, {}
    for row in rows:
        station = row["station"]
        if station in EXCLUDED_STATIONS:
            continue
        stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if not now-timedelta(minutes=90) <= stamp <= now:
            continue
        rank = (row["time"], row.get("receiptTime", ""))
        if station not in latest_weather or rank >= (latest_weather[station]["time"], latest_weather[station].get("receiptTime", "")):
            latest_weather[station] = row
        if row.get("cloudReportAvailable", True) and (station not in latest_cloud or rank >= (latest_cloud[station]["time"], latest_cloud[station].get("receiptTime", ""))):
            latest_cloud[station] = row
    stations = []
    for station, weather in sorted(latest_weather.items()):
        clouds = latest_cloud.get(station, {"layers": [], "time": weather["time"]})
        stations.append(cloud_summary({**weather, "time": clouds["time"], "weatherTime": weather["time"],
                                       "layers": clouds["layers"], "cloudDataAvailable": bool(clouds["layers"])}))
    return {"isLive": True, "hour": iso(now), "stations": stations, "metro": metro_report(stations, now)}


def collect(download, now, previous=None, rapid_rows=None):
    previous = previous or {}
    cache = reports(download(SOURCE_URL), now)
    retained = [row for hour in previous.get("history", []) for row in hour["stations"]
                if row["station"] not in EXCLUDED_STATIONS]
    ids = sorted({row["station"] for row in cache["stations"]+retained})
    hours = 13
    if previous.get("version") == 3:
        gap = (now-datetime.fromisoformat(previous.get("historyCheckedAt", previous["checkedAt"]).replace("Z", "+00:00"))).total_seconds()
        hours = min(13, max(2, math.ceil(gap/3600)+1))
    needs_history = previous.get("version") != 3 or gap >= 900 or now.minute in (3, 56, 59)
    # Bootstrap all twelve hours once. Later runs merge a short overlap with
    # durable history. Split capped responses; never silently lose stations.
    batch_size = 8 if hours > 3 else 40
    rows = retained + cache["stations"]
    last_request = None
    def fetch_group(group):
        nonlocal last_request
        if last_request is not None:
            time.sleep(max(0, 1-(time.monotonic()-last_request)))
        last_request = time.monotonic()
        url = "https://aviationweather.gov/api/data/metar?" + urlencode(
            {"ids": ",".join(group), "format": "xml", "hours": hours})
        raw = download(url)
        if not raw:  # AWC 204: a valid request with no reports.
            return []
        parsed = parse_reports(raw, now, hours=13)
        count = len(ET.fromstring(raw).findall(".//METAR"))
        if count >= 400:
            if len(group) == 1:
                raise ValueError("AWC report limit reached for a station; previous history retained")
            mid = len(group)//2
            return fetch_group(group[:mid])+fetch_group(group[mid:])
        return parsed
    if needs_history:
        for start in range(0, len(ids), batch_size):
            rows.extend(fetch_group(ids[start:start+batch_size]))
    data = snapshot(rows, now)
    if not any(hour["stations"] for hour in data["history"]):
        raise ValueError("No routine hourly regional reports; previous history retained")
    rapid = [{**row, "station": row["icaoId"], "time": iso(datetime.fromtimestamp(row["obsTime"], timezone.utc)),
              "reportType": "HFMETAR", "receiptTime": ""} for row in (rapid_rows or [])]
    data["liveReports"] = cache["stations"] + rapid
    data["live"] = live_snapshot(data["liveReports"], now)
    data["historyCheckedAt"] = iso(now) if needs_history else previous.get("historyCheckedAt", previous["checkedAt"])
    return data
