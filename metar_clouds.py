"""Routine hourly U.S. METAR ceilings and weather plots."""
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import math
import logging
import re
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

SOURCE_URL = "https://aviationweather.gov/data/cache/metars.cache.xml.gz"
# Include the lower 48, Alaska, Hawaii and U.S. territories. ICAO prefixes
# select U.S. airports rather than a rectangle that also includes foreign sites.
BOUNDS = [[-15, -180], [72, 180]]
US_PREFIXES = ("K", "PA", "PF", "PO", "PP", "PH", "TJ", "PG")
US_ISLAND_STATIONS = frozenset({"PWAK", "NSTU"})
COLLECTION_BUDGET_SECONDS = 720
COVERS = {"CLR", "SKC", "FEW", "SCT", "BKN", "OVC", "VV", "NSC", "NCD", "CAVOK"}
# User-excluded unreliable cloud station. Enforce on fresh and retained history.
EXCLUDED_STATIONS = frozenset({"KCFE"})


def included_station(station):
    return (bool(re.fullmatch(r"[A-Z0-9]{3,5}", station))
            and station not in EXCLUDED_STATIONS
            and (station.startswith(US_PREFIXES) or station in US_ISLAND_STATIONS))


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
        if not included_station(station):
            continue
        lat, lon = value(row.findtext("latitude"), -90, 90), value(row.findtext("longitude"), -180, 180)
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
        raise ValueError("No recent U.S. METAR reports are available")
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
        if not included_station(row["station"]):
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
        history.append({"hour": hour, "stations": stations, "metro": metro_report(stations, now, hour)})
    return {"version": 3, "coverage": "usa", "mode": "routine-hourly", "history": history, "stations": history[-1]["stations"],
            "bounds": BOUNDS, "heightUnit": "feet AGL", "checkedAt": checked_at or iso(now),
            "source": "NOAA Aviation Weather Center", "sourceUrl": "https://aviationweather.gov/data/api/"}


def current(data, now):
    rows = [row for hour in data.get("history", []) for row in hour["stations"]]
    # A legacy latest-only snapshot cannot supply the requested hourly history.
    if data.get("version") not in (2, 3):
        rows = data.get("stations", [])
    result = snapshot(rows, now, data["checkedAt"])
    result["historyPending"] = data.get("version") != 3 or data.get("coverage") != "usa" or bool(data.get("backfillPending"))
    return {**result, "stale": data.get("stale", False) or bool(data.get("partialCollection"))}


def metro_position():
    # Circumcenter in a local latitude/longitude projection: approximately equal
    # ground distance from all three airports, independent of map zoom.
    import numpy as np
    points = np.array([[44.83, -93.45], [44.88, -93.22], [45.07, -93.35]])
    scale = math.cos(math.radians(points[:, 0].mean()))
    xy = np.column_stack((points[:, 1]*scale, points[:, 0]))
    center = np.linalg.solve(2*(xy[1:]-xy[0]), (xy[1:]**2).sum(axis=1)-(xy[0]**2).sum())
    return float(center[1]), float(center[0]/scale)


def metro_report(rows, now, hour):
    from app import STATIONS, hourly_snapshot
    reports = [{**row, "icaoId": row["station"],
                "obsTime": datetime.fromisoformat(row.get("weatherTime", row["time"]).replace("Z", "+00:00")).timestamp(),
                "metarType": row.get("reportType", "METAR")} for row in rows if row["station"] in STATIONS]
    data = hourly_snapshot(reports, datetime.fromisoformat(hour.replace("Z", "+00:00")), now)
    available = data["qa"]["allStationsUsed"]
    lat, lon = metro_position()
    return {"station": "METRO", "lat": lat, "lon": lon, "isMetro": True, "available": available,
            "tempF": data["tempF"] if available else None,
            "dewpointF": data["dewpointF"] if available else None,
            "wind": data["wind"] if available else {"speedKnots": None, "direction": None},
            "time": data.get("observedAt") or (max((row["time"] for row in rows if row["station"] in STATIONS), default=None)),
            "oldestObservedAt": data.get("oldestObservedAt"), "qa": data["qa"]}


def collect(download, now, previous=None):
    started = time.monotonic()
    previous = previous or {}
    cache = reports(download(SOURCE_URL), now)
    retained = [row for hour in previous.get("history", []) for row in hour["stations"]
                if included_station(row["station"])]
    ids = sorted({row["station"] for row in cache["stations"]+retained})
    hours = 13
    if previous.get("version") == 3:
        gap = (now-datetime.fromisoformat(previous.get("historyCheckedAt", previous["checkedAt"]).replace("Z", "+00:00"))).total_seconds()
        hours = min(13, max(2, math.ceil(gap/3600)+1))
    # Backfill newly added nationwide sites without refetching old sites' full
    # history every hour. Upgrading from the regional feed backfills all sites.
    known = set(previous.get("historyStationIds", [row["station"] for row in retained])) if previous.get("coverage") == "usa" else set()
    new_ids = [station for station in ids if station not in known]
    warm_ids = [station for station in ids if station in known]
    rows = retained + cache["stations"]
    # Fetch the complete overlap once for each new labeled hour. At :58/:02,
    # the bulk cache supplies ordinary corrections; only missing reports or
    # stations whose routine report is hidden by a SPECI need historical calls.
    # This avoids downloading the entire country's history three times/hour.
    from app import routine_hour
    labels = {}
    latest = now.replace(minute=0, second=0, microsecond=0)
    for row in rows:
        stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        label = routine_hour({"metarType": row["reportType"], "obsTime": stamp.timestamp(),
                              "rawOb": row.get("rawOb", "")}, now)
        if label is not None:
            labels.setdefault(row["station"], set()).add(label)
            latest = max(latest, label)
    full_overlap = previous.get("collectedHour") != iso(latest) or hours > 2
    if not full_overlap:
        special = {row["station"] for row in cache["stations"]
                   if row["reportType"] == "SPECI" or row.get("rawOb", "").startswith("SPECI")}
        warm_ids = [station for station in warm_ids if latest not in labels.get(station, set()) or station in special]
    last_request = None
    def fetch_group(group, query_hours):
        nonlocal last_request
        if last_request is not None:
            time.sleep(max(0, 1-(time.monotonic()-last_request)))
        last_request = time.monotonic()
        url = "https://aviationweather.gov/api/data/metar?" + urlencode(
            {"ids": ",".join(group), "format": "xml", "hours": query_hours})
        raw = download(url)
        if not raw:  # AWC 204: a valid request with no reports.
            return []
        parsed = parse_reports(raw, now, hours=13)
        count = len(ET.fromstring(raw).findall(".//METAR"))
        if count >= 400:
            if len(group) == 1:
                raise ValueError("AWC report limit reached for a station; previous history retained")
            mid = len(group)//2
            return fetch_group(group[:mid], query_hours)+fetch_group(group[mid:], query_hours)
        return parsed
    # AWC's latest bulk cache discovers every site in one request. Historical
    # API requests are paced below the 100/minute limit and split at its cap.
    batches = []
    for group_ids, query_hours in ((new_ids, 13), (warm_ids, hours)):
        batch_size = 12 if query_hours > 3 else 40
        for start in range(0, len(group_ids), batch_size):
            batches.append((group_ids[start:start+batch_size], query_hours))
    completed, failed = known.intersection(ids)-set(warm_ids), set()
    queried = set()
    last_error = None
    for index, (group, query_hours) in enumerate(batches):
        # Save successful progress before the HTTP deadline. Unfinished/new
        # groups receive their full backfill again at the next scheduled check.
        if time.monotonic()-started > COLLECTION_BUDGET_SECONDS:
            failed.update(station for pending, _ in batches[index:] for station in pending)
            break
        try:
            rows.extend(fetch_group(group, query_hours))
            completed.update(group)
            queried.update(group)
        except Exception as error:
            last_error = error
            failed.update(group)
            logging.getLogger(__name__).warning("METAR history batch delayed (%d sites): %s", len(group), error)
    if batches and not queried:
        raise last_error or ValueError("No METAR history queries completed; previous snapshot retained")
    data = snapshot(rows, now)
    if not any(hour["stations"] for hour in data["history"]):
        raise ValueError("No routine hourly U.S. reports; previous history retained")
    data["historyCheckedAt"] = iso(now)
    data["historyStationIds"] = sorted(completed)
    data["collectedHour"] = iso(latest)
    data["partialCollection"] = bool(failed)
    data["backfillPending"] = bool(failed & set(new_ids))
    return data
