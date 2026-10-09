"""Twin Cities observations and MPX radar. Run locally: python app.py."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import BytesIO
import json
import logging
import math
import os
import re
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, Response, jsonify, send_from_directory
import numpy as np
from PIL import Image
from realtime import get_store

app = Flask(__name__, static_folder="static")
UTC = timezone.utc
STATIONS = {"KFCM": "Flying Cloud", "KMSP": "Minneapolis–St. Paul", "KMIC": "Crystal"}
IEM = "https://mesonet.agron.iastate.edu"
# Reflectivity color stops sampled from the user's COD reference, starting at
# 10 dBZ. Interpolation follows each 0.5 dBZ data code; no rain-rate conversion.
PALETTE = [(10, "#02621e"), (15, "#117f26"), (20, "#24a32f"),
           (25, "#36c538"), (30, "#4ae942"), (31.5, "#50f346"),
           (31.51, "#fffb27"), (35, "#ffe524"), (40, "#ffb51c"),
           (45, "#ff8815"), (50, "#ff580e"), (55, "#ff2606"),
           (60, "#f00000"), (64.99, "#a40000"), (65, "#e600c8"),
           (70, "#f349e4"), (75, "#e88df8"), (79.99, "#bdbeff"),
           (80, "#00d5d0")]
RENDER_VERSION = "cod-gradient-v6"
_cache, _locks = {}, {}
_lock_guard = threading.Lock()


def utcnow():
    return datetime.now(UTC)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def download(url):
    req = Request(url, headers={"User-Agent": "Weather-Lab (https://github.com/Barometer32/weather-lab)"})
    with urlopen(req, timeout=20) as response:
        return response.read(8_000_000)


def cached(key, seconds, loader):
    # One upstream request per cache key even with simultaneous browser requests.
    with _lock_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        entry = _cache.get(key)
        if entry and time.monotonic() - entry[0] < seconds:
            return entry[1]
        value = loader()
        _cache[key] = (time.monotonic(), value)
        return value


def get_reports():
    url = "https://aviationweather.gov/api/data/metar?" + urlencode(
        {"ids": ",".join(STATIONS), "format": "json", "hours": 16})
    return cached("metar", 120, lambda: json.loads(download(url)))


def valid_number(value, minimum, maximum):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and minimum <= value <= maximum


def valid_dewpoint(report):
    value, temperature = report.get("dewp"), report.get("temp")
    # Allow half a degree for reported-value rounding near saturation.
    return valid_number(value, -100, 60) and (not valid_number(temperature, -90, 60)
                                            or value <= temperature + 0.5)


def quality_summary(chosen):
    checks = {"temperature": 0, "dewpoint": 0, "wind": 0}
    used = 0
    for report in chosen:
        passed = {"temperature": valid_number(report.get("temp"), -90, 60),
                  "dewpoint": valid_dewpoint(report),
                  "wind": valid_number(report.get("wspd"), 0, 200) and (
                      report.get("wspd") == 0 or report.get("wdir") == "VRB"
                      or valid_number(report.get("wdir"), 0, 360))}
        for field, ok in passed.items():
            checks[field] += int(ok)
        used += int(all(passed.values()))
    all_used = used == len(STATIONS)
    return {"status": "passed" if all_used else "incomplete",
            "stationsUsed": used, "stationsAvailable": len(chosen),
            "stationsExpected": len(STATIONS), "allStationsUsed": all_used,
            "checks": checks}


def average(values):
    return round(sum(values) / len(values), 1) if values else None


def wind_mean(reports):
    speeds = [r["wspd"] for r in reports if valid_number(r.get("wspd"), 0, 200)]
    vectors = []
    for r in reports:
        speed, direction = r.get("wspd"), r.get("wdir")
        if not valid_number(speed, 0, 200):
            continue
        if speed == 0:
            vectors.append((0, 0))
        elif valid_number(direction, 0, 360):
            rad = math.radians(direction)
            vectors.append((speed * math.sin(rad), speed * math.cos(rad)))
    # Mean speed is scalar; direction is speed-weighted circular, never arithmetic.
    direction = None
    if vectors:
        u, v = (sum(x[i] for x in vectors) for i in range(2))
        if math.hypot(u, v) > 0.01:
            direction = round(math.degrees(math.atan2(u, v)) % 360)
    return {"speedMph": round(average(speeds) * 1.150779, 1) if speeds else None,
            "direction": direction, "speedCount": len(speeds), "directionCount": len(vectors)}


def routine_hour(report, as_of):
    """Label the scheduled :53 METAR with the following hour; exclude SPECIs."""
    if report.get("metarType") != "METAR" or str(report.get("rawOb", "")).startswith("SPECI"):
        return None
    stamp = report.get("obsTime")
    if not valid_number(stamp, 0, as_of.timestamp()):
        return None
    observed = datetime.fromtimestamp(stamp, UTC)
    # Permit small changes in the routine reporting minute, never other reports.
    if not 50 <= observed.minute <= 59:
        return None
    return (observed + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def receipt_timestamp(report):
    try:
        return datetime.fromisoformat(report.get("receiptTime", "").replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0


def hourly_snapshot(reports, target, as_of):
    chosen = []
    for station in STATIONS:
        eligible = [r for r in reports if r.get("icaoId") == station
                    and routine_hour(r, as_of) == target]
        # Prefer :53, then newest report/correction receipt at the same timestamp.
        if eligible:
            expected = (target - timedelta(minutes=7)).timestamp()
            chosen.append(min(eligible, key=lambda r: (abs(r["obsTime"] - expected),
                -r["obsTime"], -receipt_timestamp(r))))
    temps = [r["temp"] * 9 / 5 + 32 for r in chosen if valid_number(r.get("temp"), -90, 60)]
    dewpoints = [r["dewp"] * 9 / 5 + 32 for r in chosen if valid_dewpoint(r)]
    pressure = [r["altim"] for r in chosen if valid_number(r.get("altim"), 800, 1100)]
    stations = []
    for code, name in STATIONS.items():
        r = next((r for r in chosen if r["icaoId"] == code), None)
        stations.append({"code": code, "name": name, "available": r is not None,
            "observedAt": iso(datetime.fromtimestamp(r["obsTime"], UTC)) if r else None,
            "tempF": round(r["temp"] * 9 / 5 + 32, 1) if r and valid_number(r.get("temp"), -90, 60) else None,
            "dewpointF": round(r["dewp"] * 9 / 5 + 32, 1) if r and valid_dewpoint(r) else None,
            "cloudCover": r.get("cover") if r else None, "weather": r.get("wxString") if r else None,
            "rawMetar": r.get("rawOb") if r else None})
    return {"hour": iso(target), "tempF": average(temps), "dewpointF": average(dewpoints),
            "pressureHpa": average(pressure), "wind": wind_mean(chosen), "count": len(chosen),
            "tempCount": len(temps), "dewpointCount": len(dewpoints), "stations": stations,
            "qa": quality_summary(chosen)}


def observations(reports=None, now=None):
    now = now or utcnow()
    reports = get_reports() if reports is None else reports
    # Display a routine report as soon as received, using its rounded hour label.
    # An outage must not leave an old complete hour looking current indefinitely.
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    hours = [routine_hour(r, now) for r in reports if r.get("icaoId") in STATIONS]
    target = max([current_hour] + [hour for hour in hours if hour is not None])
    history = [hourly_snapshot(reports, target - timedelta(hours=i), now) for i in range(12)]
    return {"fetchedAt": iso(now), "current": history[0], "history": history,
            "method": "Routine METAR near :53 (:50–:59), labeled with the following hour. SPECI excluded. Equal station weights.",
            "source": "NOAA Aviation Weather Center"}


def scans_in_window(scans, now):
    start = now - timedelta(hours=2)
    times = set()
    for scan in scans:
        try:
            stamp = datetime.fromisoformat(scan["ts"].replace("Z", "+00:00"))
            if stamp.tzinfo is not None and start <= stamp <= now:
                times.add(stamp)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return [{"time": iso(t), "id": t.strftime("%Y%m%d%H%M")} for t in sorted(times)]


def get_scans(now=None):
    now = now or utcnow()
    def load():
        query = urlencode({"operation": "list", "radar": "MPX", "product": "N0B",
            "start": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%MZ"),
            "end": now.strftime("%Y-%m-%dT%H:%MZ")})
        data = json.loads(download(IEM + "/json/radar.py?" + query))
        return data.get("scans", [])
    # Refilter cached results so an old frame cannot extend the two-hour window.
    return scans_in_window(cached("radar-scans", 120, load), now)


def raw_radar(scan_id):
    if not re.fullmatch(r"\d{12}", scan_id):
        raise ValueError("Invalid scan")
    t = datetime.strptime(scan_id, "%Y%m%d%H%M").replace(tzinfo=UTC)
    base = f"{IEM}/archive/data/{t:%Y/%m/%d}/GIS/ridge/MPX/N0B/MPX_N0B_{scan_id}"
    return download(base + ".png"), download(base + ".wld")


def recolor_and_project(png, worldfile, smooth=True):
    image = Image.open(BytesIO(png))
    if image.mode != "P":
        raise ValueError("Radar source format changed: indexed PNG required")
    # IEM N0B PNG indexes retain Level III data codes: 0/1 missing; 2 = -32 dBZ,
    # each subsequent index adds 0.5 dBZ. Classify data indexes, not RGB guesses.
    codes = np.asarray(image)
    dbz = (codes.astype(float) - 2) * 0.5 - 32
    rgba = np.zeros((*codes.shape, 4), dtype=np.uint8)
    stops = np.array([p[0] for p in PALETTE])
    colors = np.array([[int(color[i:i+2], 16) for i in (1, 3, 5)] for _, color in PALETTE])
    visible = (codes >= 2) & (dbz >= 10)
    for channel in range(3):
        rgba[:, :, channel][visible] = np.rint(np.interp(dbz[visible], stops, colors[:, channel])).astype(np.uint8)
    rgba[:, :, 3][visible] = 220
    dx, rot1, rot2, dy, x0, y0 = map(float, worldfile.decode().split())
    if rot1 != 0 or rot2 != 0 or dx <= 0 or dy >= 0:
        raise ValueError("Unsupported radar georeferencing")
    height, width = codes.shape
    west, east = x0 - dx / 2, x0 + dx * (width - 0.5)
    north, south = y0 - dy / 2, y0 + dy * (height - 0.5)
    # Reproject latitude-linear image rows to Web Mercator for Leaflet alignment.
    merc = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    ys = merc(north) + (np.arange(height) + 0.5) / height * (merc(south) - merc(north))
    lats = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)
    rows = np.clip(np.rint((lats - y0) / dy).astype(int), 0, height - 1)
    projected = Image.fromarray(rgba[rows], "RGBA")
    if smooth:
        # Anti-alias the display, never average reflectivity or change bands.
        # Preserve the nearest-neighbor echo footprint: no colored pixels may
        # bleed into source cells that were hidden by the 10 dBZ cutoff.
        size = (width * 2, height * 2)
        footprint = projected.getchannel("A").resize(size, Image.Resampling.NEAREST)
        # Float premultiplied alpha avoids dark halos and preserves uniform
        # band colors exactly, unlike integer RGBA interpolation.
        source = np.array(projected, dtype=np.float32)
        source[:, :, :3] *= source[:, :, 3:4] / 255
        channels = [np.asarray(Image.fromarray(source[:, :, c], "F").resize(
            size, Image.Resampling.BILINEAR)) for c in range(4)]
        interpolated = np.stack(channels, axis=-1)
        interpolated[:, :, :3] *= 255 / np.maximum(interpolated[:, :, 3:4], 1e-8)
        softened = np.rint(np.clip(interpolated, 0, 255)).astype(np.uint8)
        softened[np.asarray(footprint) == 0] = 0
        projected = Image.fromarray(softened, "RGBA")
    output = BytesIO()
    projected.save(output, format="PNG", optimize=True)
    return output.getvalue(), [[south, west], [north, east]]


@lru_cache(maxsize=128)
def radar_frame(scan_id):
    return recolor_and_project(*raw_radar(scan_id))


def radar_manifest(scans, now):
    return {"frames": scans, "palette": [{"dbz": value, "color": color} for value, color in PALETTE],
            "renderVersion": RENDER_VERSION, "windowStart": iso(now - timedelta(hours=2)),
            "windowEnd": iso(now), "product": "N0B", "elevationDegrees": 0.5,
            "source": "NWS MPX N0B via Iowa Environmental Mesonet"}


def prepared_snapshot(name, max_age):
    store = get_store()
    if store is None:
        return None
    data = cached("prepared-" + name, 10, lambda: store.read_json(f"live/{name}.json"))
    if not data:
        raise ValueError("Background collector has not prepared data yet")
    data = dict(data)
    checked = datetime.fromisoformat(data["checkedAt"].replace("Z", "+00:00"))
    data["stale"] = (utcnow() - checked).total_seconds() > max_age
    return data


def get_forecast(now=None):
    from nws_forecast import POINT_URL, normalize_forecast
    def load():
        point = cached("nws-point", 86400, lambda: json.loads(download(POINT_URL)))
        url = point["properties"]["forecast"]
        if not url.startswith("https://api.weather.gov/gridpoints/"):
            raise ValueError("Unexpected NWS forecast endpoint")
        return json.loads(download(url))
    return normalize_forecast(cached("nws-forecast", 300, load), now or utcnow())


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/forecast")
def forecast_api():
    try:
        data = prepared_snapshot("forecast", 900) or get_forecast()
        return jsonify(data)
    except Exception:
        app.logger.exception("NWS forecast unavailable")
        return jsonify(error="The NWS forecast is unavailable. Please try again shortly."), 502


@app.get("/api/satellite/<product>")
def satellite_api(product):
    from satellite import PRODUCTS, page_url, parse_loop
    if product not in PRODUCTS:
        return jsonify(error="Unknown satellite product."), 404
    try:
        data = prepared_snapshot("satellite-" + product, 900)
        if data:
            data.pop("boundarySources", None)
            return jsonify(data)
        html = cached("satellite-" + product, 120, lambda: download(page_url(product)).decode())
        return jsonify(parse_loop(html, product, utcnow()))
    except Exception:
        app.logger.exception("Satellite loop unavailable")
        return jsonify(error="Satellite imagery is unavailable. Please try Refresh images."), 502


@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.get("/api/observations")
def observation_api():
    try:
        data = prepared_snapshot("observations", 4200)
        result = observations(data["reports"]) if data else observations()
        if data:
            result.update(checkedAt=data["checkedAt"], stale=data["stale"])
        return jsonify(result)
    except Exception:
        app.logger.exception("Observation feed failed")
        return jsonify(error="Observation feed unavailable. Please try again shortly."), 502


@app.get("/api/radar")
def radar_api():
    try:
        now = utcnow()
        data = prepared_snapshot("radar", 600)
        if data:
            if data.get("renderVersion") != RENDER_VERSION:
                return jsonify(error="The new radar colors are being prepared. Please refresh shortly."), 503
            scans = [frame for frame in data["frames"]
                     if now - timedelta(hours=2) <= datetime.fromisoformat(frame["time"].replace("Z", "+00:00")) <= now]
        else:
            scans = get_scans(now)
        if not scans:
            return jsonify(error="No recent MPX scans are available."), 503
        result = radar_manifest(scans, now)
        if data:
            result.update(checkedAt=data["checkedAt"], stale=data["stale"], unavailableScans=data.get("unavailableScans", 0))
        return jsonify(result)
    except Exception:
        app.logger.exception("Radar scan list failed")
        return jsonify(error="Radar feed unavailable. Please try again shortly."), 502


@app.get("/api/radar/<scan_id>/metadata")
def radar_metadata(scan_id):
    try:
        data = prepared_snapshot("radar", 600)
        if data:
            frame = next((f for f in data["frames"] if f["id"] == scan_id), None)
            return jsonify(bounds=frame["bounds"]) if frame else (jsonify(error="Unknown prepared scan"), 404)
        if scan_id not in {s["id"] for s in get_scans()}:
            return jsonify(error="Scan is outside the current loop."), 404
        _, bounds = radar_frame(scan_id)
        return jsonify(bounds=bounds)
    except Exception:
        app.logger.exception("Radar frame failed")
        return jsonify(error="This radar scan could not be loaded."), 502


@app.get("/api/radar/<scan_id>.png")
def radar_png(scan_id):
    try:
        if get_store() is not None:
            return prepared_asset(f"radar/{RENDER_VERSION}/{scan_id}.png")
        # Cached frames remain valid even if the scan list has just advanced.
        if scan_id not in {s["id"] for s in get_scans()}:
            return jsonify(error="Scan is outside the current loop."), 404
        png, _ = radar_frame(scan_id)
        return Response(png, mimetype="image/png", headers={"Cache-Control": "public, max-age=3600"})
    except Exception:
        app.logger.exception("Radar frame failed")
        return jsonify(error="This radar scan could not be loaded."), 502


@lru_cache(maxsize=16)
def prepared_image(key):
    store = get_store()
    return store.read(key) if store else None


@app.get("/api/prepared/<path:key>")
def prepared_asset(key):
    # Public visitors may read only immutable image objects, never manifests or
    # arbitrary bucket files. Only the private collector can trigger processing.
    allowed = (re.fullmatch(r"radar/" + re.escape(RENDER_VERSION) + r"/\d{12}\.png", key)
               or re.fullmatch(r"satellite/(truecolor|dcphase|ntmicro)/\d{14}\.jpg", key)
               or re.fullmatch(r"satellite/maps/[a-f0-9]{24}\.png", key))
    if not allowed:
        return jsonify(error="Unknown image"), 404
    try:
        image = prepared_image(key)
        if image is None:
            prepared_image.cache_clear()  # Do not permanently cache a missing object.
            return jsonify(error="Image not prepared yet"), 404
        return Response(image, mimetype="image/jpeg" if key.endswith(".jpg") else "image/png",
                        headers={"Cache-Control": "public, max-age=86400, immutable"})
    except Exception:
        app.logger.exception("Prepared image read failed")
        return jsonify(error="Prepared image temporarily unavailable"), 502


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
