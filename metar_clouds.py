"""Cloud-only latest station reports from AWC's complete METAR cache."""
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import math
import re
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


def reports(xml, now):
    if xml.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=BytesIO(xml)) as file:
            xml = file.read(30_000_001)
    if len(xml) > 30_000_000:
        raise ValueError("METAR cache exceeds the expected size")
    root = ET.fromstring(xml)
    if root.find("errors") is not None and list(root.find("errors")):
        raise ValueError("AWC returned an error")
    latest = {}
    for row in root.findall(".//METAR"):
        station = row.findtext("station_id", "")
        lat, lon = value(row.findtext("latitude"), 40, 50), value(row.findtext("longitude"), -100, -85)
        if not re.fullmatch(r"[A-Z0-9]{3,5}", station) or lat is None or lon is None:
            continue
        try:
            stamp = datetime.fromisoformat(row.findtext("observation_time", "").replace("Z", "+00:00"))
            if stamp.tzinfo is None or not now-timedelta(hours=2) <= stamp <= now:
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
                "reportType": row.findtext("metar_type", "METAR"), "layers": layers,
                "cloudDataAvailable": bool(layers), "delayed": (now-stamp).total_seconds() > 5400}
        # Keep the last cache entry if equally timed. An older clear report
        # must not mask a newer missing-cloud report or special observation.
        previous = latest.get(station)
        if previous is None or item["time"] >= previous["time"]:
            latest[station] = item
    if not latest:
        raise ValueError("No recent regional METAR cloud reports are available")
    return {"stations": sorted(latest.values(), key=lambda row: row["station"]),
            "bounds": BOUNDS, "heightUnit": "feet AGL", "checkedAt": now.isoformat().replace("+00:00", "Z"),
            "source": "NOAA Aviation Weather Center", "sourceUrl": SOURCE_URL}


def current(data, now):
    rows = []
    for station in data["stations"]:
        moment = datetime.fromisoformat(station["time"].replace("Z", "+00:00"))
        age = (now-moment).total_seconds()
        if 0 <= age <= 7200:
            rows.append({**station, "delayed": age > 5400})
    return {**data, "stations": rows}
