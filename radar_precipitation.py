"""NOAA Level III DTA/172 storm-total precipitation, separate from reflectivity."""
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
import logging
import time

import numpy as np
from native_radar import UTC, VERSION, SITES, iso, fetch, objects, packet

ARCHIVE = "https://unidata-nexrad-level3.s3.amazonaws.com/"
PALETTE = [{"value": value, "color": color} for value, color in (
    (.01, "#c6efff"), (.1, "#4d9de0"), (.25, "#2663aa"), (.5, "#24b35a"),
    (1, "#f2e747"), (2, "#f49c26"), (4, "#e34236"), (8, "#b32b94"), (16, "#702480"))]


def decode_precipitation(raw, site):
    from metpy.io import Level3File
    product = Level3File(BytesIO(raw))
    if product.siteID != site[1:] or product.header.code != 172:
        raise ValueError("Wrong storm-total radar product")
    fields = [field for layer in getattr(product, "sym_block", []) for field in layer
              if "start_az" in field and "data" in field]
    null = bool(product.metadata.get("null_product"))
    if not fields and not null:
        raise ValueError("Storm-total polar grid missing")
    if fields:
        field = fields[0]
        codes = np.asarray(field["data"], dtype=np.uint8)
        azimuths = (np.asarray(field["start_az"]) +
                    (np.asarray(field["end_az"])-np.asarray(field["start_az"])) / 2) % 360
        gate_width = field["gate_scale"] * 1000
        first = field["first"] * gate_width + gate_width / 2
    else:
        codes = np.zeros((360, 920), dtype=np.uint8)
        azimuths = np.arange(360) + .5
        gate_width, first = 250, 125
    if codes.ndim != 2 or not 350 <= len(codes) <= 1440 or not 1 <= codes.shape[1] <= 2000:
        raise ValueError("Invalid storm-total dimensions")
    if null:
        codes = np.zeros_like(codes)
    # ICD DTA/172 physical scale is hundredths of inches. Preserve the source
    # 8-bit codes and its per-product scale/offset instead of quantizing again.
    mapped = product.map_data(np.arange(256)) / 100
    code_values = [float(v) if np.isfinite(v) and v >= 0 else None for v in mapped]
    stamp = product.metadata["rainfall_end"].replace(tzinfo=UTC)
    begin = product.metadata["rainfall_begin"].replace(tzinfo=UTC)
    scan = product.metadata["vol_time"].replace(tzinfo=UTC)
    meta = {"site": site, "id": scan.strftime("%Y%m%d%H%M%S") + "-" + sha256(raw).hexdigest()[:16],
            "time": iso(stamp), "endTime": iso(stamp), "accumulationStart": iso(begin),
            "latitude": product.lat, "longitude": product.lon, "nominalElevation": 0,
            "groundRange": True, "gates": codes.shape[1], "firstGateMeters": first,
            "gateWidthMeters": gate_width, "azimuthSpacing": 1, "azimuths": sorted(azimuths.tolist()),
            "codeValues": code_values, "units": "inches", "nullProduct": null}
    return meta, packet(meta, codes[np.argsort(azimuths)])


def collect(store, now, site="KMPX", budget=20):
    key = f"live/radar-storm-total-{site}.json"
    previous = store.read_json(key) or {}
    frames = {f["sourceKey"]: f for f in previous.get("frames", [])
              if now-timedelta(hours=2) <= datetime.fromisoformat(f["time"].replace("Z", "+00:00")) <= now}
    deadline = time.monotonic() + budget
    rows = []
    for date in sorted({now.date(), (now-timedelta(hours=2, minutes=15)).date()}):
        rows.extend(objects(ARCHIVE, f"{site[1:]}_DTA_{date:%Y_%m_%d}"))
    recent = []
    for row in rows:
        stamp = datetime.strptime(row["key"], f"{site[1:]}_DTA_%Y_%m_%d_%H_%M_%S").replace(tzinfo=UTC)
        if now-timedelta(hours=2, minutes=15) <= stamp <= now:
            recent.append(row)
    errors = 0
    for row in reversed(sorted(recent, key=lambda row: row["key"])):
        if row["key"] in frames or time.monotonic() >= deadline:
            continue
        try:
            meta, data = decode_precipitation(fetch(ARCHIVE+row["key"]), site)
            if not now-timedelta(hours=2) <= datetime.fromisoformat(meta["time"].replace("Z", "+00:00")) <= now:
                continue
            asset = f"radar/storm-total-v1/{site}/{meta['id']}.bin"
            store.write(asset, data, "application/octet-stream")
            frames[row["key"]] = {k: meta[k] for k in ("id", "time", "endTime", "accumulationStart", "nullProduct")}
            frames[row["key"]].update(url="/api/prepared/"+asset, sourceKey=row["key"])
        except Exception:
            logging.getLogger(__name__).exception("Storm-total collection failed for %s", row["key"])
            errors += 1
    if not frames:
        raise ValueError("No recent storm-total precipitation product; previous data retained")
    data = {"site": site, "siteName": SITES[site]["name"], "renderVersion": VERSION,
            "center": SITES[site]["center"], "zoom": SITES[site]["zoom"],
            "frames": sorted(frames.values(), key=lambda f: f["time"]),
            "product": "Storm-total precipitation", "units": "inches", "palette": PALETTE,
            "checkedAt": iso(now), "windowStart": iso(now-timedelta(hours=2)), "windowEnd": iso(now),
            "collectionErrors": errors, "source": "NOAA/NWS dual-polarization DTA/172 via NSF Unidata"}
    store.write_json(key, data)
    return {"frames": len(frames), "errors": errors}
