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
                "cloudDataAvailable": bool(layers), "delayed": (now-stamp).total_seconds() > 5400}
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
            chosen[key] = (rank, row)
    history = []
    for i in reversed(range(12)):
        hour = iso(latest-timedelta(hours=i))
        stations = sorted((item[1] for (label, _), item in chosen.items() if label == hour),
                          key=lambda row: row["station"])
        history.append({"hour": hour, "stations": stations})
    return {"version": 2, "history": history, "stations": history[-1]["stations"],
            "bounds": BOUNDS, "heightUnit": "feet AGL", "checkedAt": checked_at or iso(now),
            "source": "NOAA Aviation Weather Center", "sourceUrl": "https://aviationweather.gov/data/api/"}


def current(data, now):
    rows = [row for hour in data.get("history", []) for row in hour["stations"]]
    # A legacy latest-only snapshot cannot supply the requested hourly history.
    if data.get("version") != 2:
        rows = data.get("stations", [])
    return {**snapshot(rows, now, data["checkedAt"]), "stale": data.get("stale", False)}


def collect(download, now, previous=None):
    previous = previous or {}
    cache = reports(download(SOURCE_URL), now)
    retained = [row for hour in previous.get("history", []) for row in hour["stations"]]
    ids = sorted({row["station"] for row in cache["stations"]+retained})
    hours = 13
    if previous.get("version") == 2:
        gap = (now-datetime.fromisoformat(previous["checkedAt"].replace("Z", "+00:00"))).total_seconds()
        hours = min(13, max(2, math.ceil(gap/3600)+1))
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
    for start in range(0, len(ids), batch_size):
        rows.extend(fetch_group(ids[start:start+batch_size]))
    data = snapshot(rows, now)
    if not any(hour["stations"] for hour in data["history"]):
        raise ValueError("No routine hourly regional reports; previous history retained")
    return data
