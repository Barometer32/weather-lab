"""Twin Cities observations and MPX radar. Run locally: python app.py."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import BytesIO
import json
import gzip
import logging
import math
import os
import re
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, request, send_from_directory, render_template
import numpy as np
from PIL import Image
from realtime import get_store
from native_radar import VERSION as NATIVE_VERSION, SITES as RADAR_SITES, HISTORY_HOURS as RADAR_HISTORY_HOURS

app = Flask(__name__, static_folder="static", template_folder="static")

@app.after_request
def compress_json(response):
    # Native radar is already compressed. JSON histories compress particularly
    # well because station metadata repeats across the twelve hourly frames.
    if (response.status_code == 200 and response.mimetype == "application/json"
            and not response.headers.get("Content-Encoding")
            and request.accept_encodings["gzip"] > 0):
        raw = response.get_data()
        if len(raw) >= 1024:
            packed = gzip.compress(raw, compresslevel=5, mtime=0)
            if len(packed) < len(raw):
                response.set_data(packed)
                response.headers["Content-Encoding"] = "gzip"
                response.vary.add("Accept-Encoding")
    return response

UTC = timezone.utc
STATIONS = {"KFCM": "Flying Cloud", "KMSP": "Minneapolis–St. Paul", "KMIC": "Crystal"}
OBSERVATION_CHECK_MINUTES = (2,)
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
RENDER_VERSION = "cod-gradient-v10-native"
_cache, _locks = {}, {}
_lock_guard = threading.Lock()


def radar_palette():
    return [{"dbz": value, "color": color} for value, color in PALETTE]


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


def valid_number(value, minimum, maximum):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and minimum <= value <= maximum


def valid_dewpoint(report):
    value, temperature = report.get("dewp"), report.get("temp")
    # Allow half a degree for reported-value rounding near saturation.
    return valid_number(value, -100, 60) and (not valid_number(temperature, -90, 60)
                                            or value <= temperature + 0.5)


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
            "speedKnots": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "variable": any(r.get("wdir") == "VRB" for r in reports),
            "direction": direction, "speedCount": len(speeds), "directionCount": len(vectors)}


def routine_hour(report, as_of):
    """Label the scheduled :53 METAR with the following hour; exclude SPECIs."""
    if (report.get("metarType") != "METAR" or str(report.get("rawOb", "")).startswith("SPECI")
            or "MADISHF" in str(report.get("rawOb", ""))):
        return None
    stamp = report.get("obsTime")
    if not valid_number(stamp, 0, as_of.timestamp()):
        return None
    observed = datetime.fromtimestamp(stamp, UTC)
    # Accept the user’s :50–:59 window; selection still prefers routine :53.
    if not 50 <= observed.minute <= 59:
        return None
    return (observed + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def receipt_timestamp(report):
    try:
        return datetime.fromisoformat(report.get("receiptTime", "").replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0


def metar_precision(report):
    """Prefer the actual METAR T remark over its whole-degree body group."""
    result = dict(report)
    remarks = str(report.get("rawOb", "")).partition(" RMK")[2]
    match = re.search(r"\bT([01])(\d{3})(?:([01])(\d{3}))?\b", remarks)
    if match:
        result["temp"] = int(match[2]) / 10 * (-1 if match[1] == "1" else 1)
        if match[3] is not None:
            result["dewp"] = int(match[4]) / 10 * (-1 if match[3] == "1" else 1)
    return result


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


def recolor_and_project(png, worldfile):
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
    # Retain the source raster dimensions and nearest-source-cell projection.
    # No antialiasing, extra display pixels, or blending of neighboring echoes.
    output = BytesIO()
    projected.save(output, format="PNG", optimize=True)
    return output.getvalue(), [[south, west], [north, east]]


@lru_cache(maxsize=128)
def radar_frame(scan_id):
    return recolor_and_project(*raw_radar(scan_id))


def radar_manifest(scans, now):
    return {"frames": scans, "palette": radar_palette(),
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


def prepared_hourly_snapshot(name):
    data = prepared_snapshot(name, 3600)
    if data is None:
        return None
    now = utcnow()
    # Allow two minutes for the shared hourly bulk download to finish.
    cutoff = now - timedelta(minutes=2)
    hour = now.replace(minute=0, second=0, microsecond=0)
    expected = max(hour-timedelta(hours=offset)+timedelta(minutes=minute)
                   for offset in (0, 1) for minute in OBSERVATION_CHECK_MINUTES
                   if hour-timedelta(hours=offset)+timedelta(minutes=minute) <= cutoff)
    checked = datetime.fromisoformat(data["checkedAt"].replace("Z", "+00:00"))
    data["stale"] = checked < expected
    return data


def get_forecast(now=None):
    from nws_forecast import FORECAST_URL, normalize_forecast
    # Use MapClick's structured feed so wording and period selection match the
    # linked NWS webpage. Do not mix its issuance timestamp with another feed.
    document = cached("nws-forecast", 1800, lambda: json.loads(download(FORECAST_URL)))
    return normalize_forecast(document, now or utcnow())


@app.get("/")
def index():
    # The opening view is the individual METAR map; no metro average is
    # calculated while rendering the page and no source fetch occurs here.
    return render_template("index.html"), 200, {"Cache-Control": "no-store"}


@app.get("/api/forecast")
def forecast_api():
    try:
        from nws_forecast import FORECAST_VERSION, current_periods
        now = utcnow()
        data = prepared_snapshot("forecast", 2100) or get_forecast(now)
        if data.get("forecastVersion") != FORECAST_VERSION:
            return jsonify(error="The matching NWS webpage forecast is being prepared. Please refresh shortly."), 503
        periods = current_periods(data["periods"], now)
        if not periods:
            return jsonify(error="No current forecast periods remain. Background updates may be delayed."), 503
        return jsonify({**data, "periods": periods}), 200, {"Cache-Control": "no-store"}
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


@app.get("/api/maps")
def maps_api():
    try:
        from surface_analysis import VERSION
        data = prepared_hourly_snapshot("maps")
        if data is None or data.get("version") not in (VERSION, "metar-maps-v2", "metar-maps-v1"):
            raise ValueError("Maps are still preparing")
        return jsonify(data), 200, {"Cache-Control": "no-store"}
    except Exception:
        app.logger.info("Maps are not prepared yet")
        return jsonify(error="Maps are preparing from the saved METAR history. Please refresh shortly."), 503


@app.get("/api/station-plots")
def station_plots_api():
    from airport_plots import collect, current
    try:
        now = utcnow()
        data = prepared_hourly_snapshot("station-plots")
        if data is None:
            hour = now.replace(minute=0, second=0, microsecond=0)
            entry = _cache.get("local-station-plots")
            if entry and entry[1].get("hour") != iso(hour):
                _cache.pop("local-station-plots", None)
            data = cached("local-station-plots", 3600, lambda: collect(download, now))
        response = jsonify(current(data, now))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Accept-Encoding"
        if request.accept_encodings["gzip"] > 0 and len(response.data) >= 10_000:
            response.set_data(gzip.compress(response.data, compresslevel=3))
            response.headers["Content-Encoding"] = "gzip"
        return response
    except Exception:
        app.logger.exception("Station plots unavailable")
        return jsonify(error="Station reports are being prepared or collection is delayed. Please refresh shortly."), 503, {"Cache-Control": "no-store"}


@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.get("/api/radar")
def radar_api():
    try:
        now = utcnow()
        site = request.args.get("site", "KMPX")
        if site not in RADAR_SITES:
            return jsonify(error="Unknown radar site."), 400
        data = prepared_snapshot("radar-" + site, 180)
        if not data or data.get("renderVersion") != NATIVE_VERSION:
            return jsonify(error="Native radar is being prepared. Please refresh shortly."), 503
        scans = [frame for frame in data["frames"]
                 if now - timedelta(hours=RADAR_HISTORY_HOURS) <= datetime.fromisoformat(frame["time"].replace("Z", "+00:00")) <= now]
        if not scans:
            return jsonify(error=f"No recent {site} scans are available."), 503
        # Native packets retain raw reflectivity codes, so the current palette
        # applies immediately to every saved scan without recollecting history.
        return jsonify({**data, "frames": scans, "palette": radar_palette(),
                        "paletteMode": "continuous", "windowStart": iso(now-timedelta(hours=RADAR_HISTORY_HOURS)), "windowEnd": iso(now), "historyHours": RADAR_HISTORY_HOURS})
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
    # Visitors can read immutable radar, satellite and METAR map assets.
    # Arbitrary bucket files remain private. Only the private collector can trigger processing.
    allowed = (re.fullmatch(r"radar/" + re.escape(NATIVE_VERSION) + r"/KMPX/\d{17}\.bin", key)
               or re.fullmatch(r"radar/" + re.escape(RENDER_VERSION) + r"/\d{12}\.png", key)
               or re.fullmatch(r"satellite/(truecolor|dcphase|ntmicro)/\d{14}\.jpg", key)
               or re.fullmatch(r"satellite/maps/[a-f0-9]{24}\.png", key)
               or re.fullmatch(r"analysis/metar-maps-v[123]/\d{12}/[a-f0-9]{16}/(manifest\.json|tempF\.png|dewpointF\.png|wind\.png)", key))
    if not allowed:
        return jsonify(error="Unknown image"), 404
    try:
        image = prepared_image(key)
        if image is None:
            prepared_image.cache_clear()  # Do not permanently cache a missing object.
            return jsonify(error="Image not prepared yet"), 404
        headers = {"Cache-Control": "public, max-age=86400, immutable"}
        if key.endswith(".bin"):
            headers["Content-Encoding"] = "gzip"
        return Response(image, mimetype="application/json" if key.endswith(".json") else "application/octet-stream" if key.endswith(".bin") else "image/jpeg" if key.endswith(".jpg") else "image/png",
                        headers=headers)
    except Exception:
        app.logger.exception("Prepared image read failed")
        return jsonify(error="Prepared image temporarily unavailable"), 502


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
