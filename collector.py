"""Private scheduled HTTP collector; Cloud Run IAM authenticates requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import logging
import threading
import time

from flask import Flask, jsonify
from PIL import Image

import app as weather
from realtime import get_store
from satellite import PRODUCTS, page_url, parse_loop

app = Flask(__name__)
locks = {name: threading.Lock() for name in ("radar-KMPX", "satellite", "observations", "forecast", "metar-clouds", "stations")}


def collect_radar_legacy(store, now):
    previous = store.read_json("live/radar.json") or {}
    old = {f["id"]: f for f in previous.get("frames", [])} if previous.get("renderVersion") == weather.RENDER_VERSION else {}
    scans = weather.get_scans(now)
    frames = [old[frame["id"]] for frame in scans if frame["id"] in old]
    deadline = time.monotonic() + 150
    added = 0

    def publish():
        data = weather.radar_manifest(sorted(frames, key=lambda f: f["time"]), now)
        data.update(checkedAt=weather.iso(now), unavailableScans=len(scans)-len(frames))
        store.write_json("live/radar.json", data)

    # Latest first, with durable checkpoints during the initial history backfill.
    for frame in reversed(scans):
        if frame["id"] in old:
            continue
        if time.monotonic() >= deadline:
            break
        try:
            png, bounds = weather.radar_frame(frame["id"])
            key = f"radar/{weather.RENDER_VERSION}/{frame['id']}.png"
            store.write(key, png, "image/png")
            frames.append({**frame, "bounds": bounds, "url": f"/api/prepared/{key}"})
            added += 1
            if added == 1 or added % 4 == 0:
                publish()
        except Exception:
            app.logger.exception("Could not prepare radar %s", frame["id"])
    if not frames:
        raise ValueError("No radar frames prepared; previous manifest retained")
    publish()
    return {"frames": len(frames), "unavailable": len(scans)-len(frames)}


def collect_radar(store, now):
    return {"KMPX": collect_radar_site(store, now, "KMPX")}


def collect_radar_site(store, now, site):
    from native_radar import collect_site
    palette = weather.radar_palette()
    return collect_site(store, now, site, palette, budget=45)


def collect_product(store, product, now):
    data = parse_loop(weather.download(page_url(product)).decode(), product, now)
    previous = store.read_json(f"live/satellite-{product}.json") or {}
    old = {f["time"]: f for f in previous.get("frames", [])}
    old_boundaries = previous.get("boundarySources", {})
    boundaries = []
    for url in data["boundaries"]:
        if url in old_boundaries:
            boundaries.append(old_boundaries[url])
            continue
        image = weather.download(url)
        with Image.open(BytesIO(image)) as opened:
            if opened.size != (data["width"], data["height"]):
                raise ValueError("Satellite boundary grid changed")
            opened.verify()
        key = f"satellite/maps/{sha256(url.encode()).hexdigest()[:24]}.png"
        store.write(key, image, "image/png")
        boundaries.append(f"/api/prepared/{key}")
    source_boundaries = data["boundaries"]
    source_frames = data["frames"]
    frames = [old[frame["time"]] for frame in source_frames if frame["time"] in old]
    deadline = time.monotonic() + 150
    added = 0

    def publish():
        prepared = {**data, "frames": sorted(frames,key=lambda f:f["time"]), "boundaries": boundaries,
                    "boundarySources": dict(zip(source_boundaries,boundaries)),
                    "checkedAt":weather.iso(now), "unavailableImages":len(source_frames)-len(frames)}
        store.write_json(f"live/satellite-{product}.json",prepared)

    for frame in reversed(source_frames):
        if frame["time"] in old:
            continue
        if time.monotonic() >= deadline:
            break
        try:
            image = weather.download(frame["url"])
            with Image.open(BytesIO(image)) as opened:
                if opened.size != (data["width"], data["height"]):
                    raise ValueError("Satellite image grid changed")
                opened.verify()
            stamp = datetime.fromisoformat(frame["time"].replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S")
            key = f"satellite/{product}/{stamp}.jpg"
            store.write(key, image, "image/jpeg")
            frames.append({"time": frame["time"], "url": f"/api/prepared/{key}"})
            added += 1
            if added == 1 or added % 4 == 0:
                publish()
        except Exception:
            app.logger.exception("Could not prepare satellite %s %s", product, frame["time"])
    if not frames:
        raise ValueError("No satellite frames prepared; previous manifest retained")
    publish()
    return {"frames": len(frames), "unavailable": len(source_frames)-len(frames)}


def collect_satellite(store, now):
    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        work = {product: pool.submit(collect_product, store, product, now) for product in PRODUCTS}
        for product, future in work.items():
            try:
                results[product] = future.result()
            except Exception:
                app.logger.exception("Satellite product failed: %s", product)
                results[product] = {"error": "Collection failed; previous images retained"}
    if all("error" in value for value in results.values()):
        raise ValueError("All satellite products failed")
    return results


def collect_metar_clouds(store, now, target_hour=None):
    from metar_clouds import collect
    previous = store.read_json("live/metar-clouds.json")
    if previous and previous.get("collectionMode") == "shared-hourly-bulk":
        checked = datetime.fromisoformat(previous["checkedAt"].replace("Z", "+00:00"))
        matching_target = target_hour is None or previous.get("hourlyTarget") == weather.iso(target_hour)
        if matching_target and checked.replace(minute=0, second=0, microsecond=0) == now.replace(minute=0, second=0, microsecond=0):
            return {"stations": len(previous["stations"]), "status": "already prepared for this hour"}
    data = collect(weather.download, now, previous, target_hour=target_hour) if target_hour else collect(weather.download, now, previous)
    # Publish all three views atomically through one canonical prepared object.
    store.write_json("live/metar-clouds.json", data)
    return {"stations": len(data["stations"]), "routineReports": len(data["observationReports"])}


def collect_observations(store, now):
    # Legacy/manual route shares the same collector, never a second source.
    return collect_metar_clouds(store, now)


def collect_forecast(store, now):
    weather._cache.pop("nws-forecast", None)
    data = weather.get_forecast(now)
    data["checkedAt"] = weather.iso(now)
    store.write_json("live/forecast.json", data)
    return {"periods": len(data["periods"])}


def collect_stations(store, now):
    from station_plots import collect
    import surface_analysis
    previous = store.read_json("live/station-plots.json")
    hour = now.replace(minute=0, second=0, microsecond=0)
    same_hour = (previous and previous.get("collectionMode") == "hourly-window"
                 and previous.get("hour") == weather.iso(hour) and previous.get("windowMinutes") == 25)
    if same_hour:
        if previous.get("analysisVersion") == surface_analysis.VERSION:
            return {"stations": len(previous["stations"]), "status": "already prepared for this hour"}
        # A palette-only migration uses the genuine saved readings and times.
        surface_analysis.prepare_history(previous, store)
        store.write_json("live/station-plots.json", previous)
        return {"stations": len(previous["stations"]), "status": "analysis style updated"}
    airport_failed = False
    try:
        # One scheduled route also prepares the cloud view and reuses its
        # official routine METARs. No second hourly airport download is needed.
        collect_metar_clouds(store, now, target_hour=hour)
    except Exception:
        app.logger.exception("Hourly airport collection delayed")
        airport_failed = True
    airport_data = store.read_json("live/metar-clouds.json") or {}
    airport_rows = [row for frame in airport_data.get("history", []) for row in frame.get("stations", [])]
    data = collect(weather.download, now, previous, airport_rows=airport_rows, airport_failed=airport_failed)
    surface_analysis.prepare_history(data, store)
    store.write_json("live/station-plots.json", data)
    return {"stations": len(data["stations"]), "failedStates": data["failedStates"]}


@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.post("/collect/<kind>")
def collect(kind):
    jobs = {"radar-KMPX": lambda store, now: collect_radar_site(store, now, "KMPX"),
            "satellite": collect_satellite,
            "observations": collect_observations, "forecast": collect_forecast,
            "metar-clouds": collect_metar_clouds, "stations": collect_stations}
    if kind not in jobs:
        return jsonify(error="Unknown collection"), 404
    lock_kind = "metar-clouds" if kind == "observations" else kind
    if not locks[lock_kind].acquire(blocking=False):
        return jsonify(status="already collecting"), 200
    try:
        store = get_store()
        if store is None:
            raise ValueError("WEATHER_DATA_BUCKET is required")
        return jsonify(status="prepared", result=jobs[kind](store, weather.utcnow()))
    except Exception:
        app.logger.exception("Background %s collection failed", kind)
        return jsonify(error="Collection failed; previous prepared data retained"), 502
    finally:
        locks[lock_kind].release()


logging.basicConfig(level=logging.INFO)
