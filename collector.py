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
locks = {name: threading.Lock() for name in ("radar-KMPX", "radar-KEVX", "satellite", "observations", "forecast")}


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
    from native_radar import SITES, collect_site
    palette = [{"dbz": value, "color": color} for value, color in weather.PALETTE]
    results = {}
    # Run sites sequentially to bound decoder memory, with a separate time
    # budget so heavy weather or a failed feed cannot starve the other site.
    for site in SITES:
        try:
            results[site] = collect_site(store, now, site, palette)
        except Exception:
            app.logger.exception("Native radar collection failed: %s", site)
            results[site] = {"error": "Collection failed; previous data retained"}
    if all("error" in value for value in results.values()):
        raise ValueError("Both native radar feeds failed")
    return results


def collect_radar_site(store, now, site):
    from native_radar import collect_site
    palette = [{"dbz": value, "color": color} for value, color in weather.PALETTE]
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


def collect_observations(store, now):
    weather._cache.pop("metar", None)
    reports = weather.get_reports()
    if not isinstance(reports, list) or not reports:
        raise ValueError("Empty observation feed; previous reports retained")
    store.write_json("live/observations.json", {"reports": reports, "checkedAt": weather.iso(now)})
    return {"reports": len(reports)}


def collect_forecast(store, now):
    weather._cache.pop("nws-forecast", None)
    data = weather.get_forecast(now)
    data["checkedAt"] = weather.iso(now)
    store.write_json("live/forecast.json", data)
    return {"periods": len(data["periods"])}


@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.post("/collect/<kind>")
def collect(kind):
    jobs = {"radar-KMPX": lambda store, now: collect_radar_site(store, now, "KMPX"),
            "radar-KEVX": lambda store, now: collect_radar_site(store, now, "KEVX"), "satellite": collect_satellite,
            "observations": collect_observations, "forecast": collect_forecast}
    if kind not in jobs:
        return jsonify(error="Unknown collection"), 404
    if not locks[kind].acquire(blocking=False):
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
        locks[kind].release()


logging.basicConfig(level=logging.INFO)
