"""Conservative local surface analysis; original station readings stay intact.

These are neighborhood screens, not official instrument verification. Suspect
fields are excluded independently, and sparse areas remain transparent.
"""
import hashlib
import json
import io
import math
from collections import Counter

import contourpy
from metar_clouds import BOUNDS
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree, Delaunay, QhullError

VERSION = "metar-maps-v2"
FIELDS = ("tempF", "dewpointF", "wind")
# Colors sampled from the user's UCAR/RAP reference legends. Each entry is
# the lower bound of a five-degree band; the final entry closes the scale.
TEMPERATURE_COLORS = [
    "#ffffff", "#ffffff", "#ff00cc", "#ff00ff", "#cc00ff", "#9900ff", "#6600ff",
    "#0000ff", "#0066ff", "#0099ff", "#00ccff", "#00ffff", "#00ffcc", "#00ff99",
    "#00ff00", "#99ff00", "#ccff00", "#ffff00", "#ffcc00", "#ff9900", "#ff6600",
    "#ff0000", "#ff0066", "#ff0099", "#ff9999", "#ff99ff", "#ffccff", "#ffffff",
]
# The same Fahrenheit value has the same color in both scalar fields.
SCALAR_PALETTE = [[-30+5*i, color] for i, color in enumerate(TEMPERATURE_COLORS)] + [[110, TEMPERATURE_COLORS[-1]]]
PALETTES = {
    "tempF": SCALAR_PALETTE,
    "dewpointF": SCALAR_PALETTE,
    # Distinct five-mph speed bands, including explicit 25/35/45/50/55 bins.
    "wind": [[0,"#f0f3ed"],[5,"#c7e4d1"],[10,"#80c8b9"],[15,"#4aa6b6"],
             [20,"#487ab0"],[25,"#6367ab"],[30,"#8159a7"],[35,"#a05299"],
             [40,"#ba5085"],[45,"#cd4d69"],[50,"#dc4b4b"],[55,"#bd3232"],[60,"#bd3232"]],
}


def coordinates(rows):
    return np.array([[(r["lon"]+93)*111.2*math.cos(math.radians(45)), (r["lat"]-45)*111.2] for r in rows])


def value(row, field):
    if field != "wind":
        v = row.get(field)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
    wind = row.get("wind") or {}
    speed, direction = wind.get("speedMph"), wind.get("direction")
    if speed is None and wind.get("speedKnots") is not None:
        speed = wind["speedKnots"]*1.150779448
    if speed is None or not math.isfinite(speed) or speed < 0:
        return None
    if speed < .5:
        return np.array([0., 0.])
    if direction is None or wind.get("variable"):
        return None
    angle = math.radians(direction)
    return np.array([-speed*math.sin(angle), -speed*math.cos(angle)])


def screen(rows):
    """Per-field spatial median/MAD screen, with independent neighbor locations."""
    if not rows:
        return
    xy = coordinates(rows)
    tree = cKDTree(xy)
    for i, row in enumerate(rows):
        checks = {}
        neighbors = tree.query_ball_point(xy[i], 100)
        neighbors.sort(key=lambda j: float(np.linalg.norm(xy[j]-xy[i])))
        for field in FIELDS:
            own = value(row, field)
            if own is None:
                checks[field] = {"status": "missing", "reason": "Missing value or no usable wind direction"}
                continue
            # One buddy per 12 km cell; co-located sensors cannot vote repeatedly.
            cells, buddies = set(), []
            for j in neighbors:
                if j == i or np.linalg.norm(xy[j]-xy[i]) < 3:
                    continue
                cell = tuple(np.floor(xy[j]/12).astype(int))
                other = value(rows[j], field)
                if cell in cells or other is None:
                    continue
                cells.add(cell)
                buddies.append(other)
            if len(buddies) < 4:
                checks[field] = {"status": "unverified", "neighbors": len(buddies), "reason": "Fewer than four independent neighbors within 100 km"}
                continue
            median = np.median(buddies, axis=0)
            residuals = np.linalg.norm(np.array(buddies)-median, axis=1) if field == "wind" else np.abs(np.array(buddies)-median)
            residual = float(np.linalg.norm(own-median)) if field == "wind" else float(abs(own-median))
            tolerance = max({"tempF": 8, "dewpointF": 10, "wind": 15}[field], 4*1.4826*float(np.median(residuals)))
            # A sharp front can leave a valid station in the minority. Retain it
            # when at least two independently located buddies corroborate it.
            agreement = np.linalg.norm(np.array(buddies)-own, axis=1) if field == "wind" else np.abs(np.array(buddies)-own)
            corroborated = int(np.sum(agreement <= {"tempF": 5, "dewpointF": 6, "wind": 8}[field])) >= 2
            suspect = residual > tolerance and not corroborated
            checks[field] = {"status": "suspect" if suspect else "screened", "neighbors": len(buddies),
                             "difference": round(residual, 1), "tolerance": round(tolerance, 1),
                             "reason": "Large disagreement with nearby stations; excluded from this contour field" if suspect else "Corroborated by independent neighbors" if corroborated else "Within conservative neighborhood tolerance"}
        row["analysisQc"] = checks


def capped_weights(raw, cap=.4):
    """Nonnegative weights sum to one; no individual site exceeds 40%."""
    low = np.zeros((len(raw), 1))
    high = 1 / np.maximum(np.min(np.where(raw > 0, raw, np.inf), axis=1, keepdims=True), 1e-100)
    for _ in range(40):
        middle = (low+high)/2
        total = np.minimum(raw*middle, cap).sum(axis=1, keepdims=True)
        low = np.where(total < 1, middle, low)
        high = np.where(total >= 1, middle, high)
    return np.minimum(raw*(low+high)/2, cap)


def grid(rows, field, nx=449, ny=193):
    # Uniform Mercator y keeps image overlays aligned with Leaflet's map.
    lons = np.linspace(BOUNDS[0][1], BOUNDS[1][1], nx)
    merc = np.linspace(np.arcsinh(np.tan(np.radians(BOUNDS[0][0]))), np.arcsinh(np.tan(np.radians(BOUNDS[1][0]))), ny)
    lats = np.degrees(np.arctan(np.sinh(merc)))
    z = np.full((ny, nx), np.nan)
    u = z.copy(); v = z.copy()
    candidates, cells = [], set()
    # Five-km de-clustering prevents highway clusters dominating the grid.
    ordered = sorted(rows, key=lambda r: (r.get("analysisQc", {}).get(field, {}).get("status") != "screened", not (r.get("network", "").endswith("_ASOS") or r.get("network") == "AWC_METAR"), r["stationKey"]))
    for row in ordered:
        if row.get("analysisQc", {}).get(field, {}).get("status") == "suspect" or value(row, field) is None:
            continue
        cell = tuple(np.floor(coordinates([row])[0]/5).astype(int))
        if cell in cells:
            continue
        cells.add(cell); candidates.append(row)
    if len(candidates) < 3:
        return lons, lats, z, u, v, len(candidates)
    xy = coordinates(candidates)
    xx, yy = np.meshgrid(lons, lats)
    points = np.column_stack(((xx.ravel()+93)*111.2*math.cos(math.radians(45)), (yy.ravel()-45)*111.2))
    distances, indices = cKDTree(xy).query(points, k=min(12, len(xy)))
    try:
        inside = Delaunay(xy).find_simplex(points) >= 0
    except QhullError:
        return lons, lats, z, u, v, len(candidates)
    supported = inside & (distances[:, 0] <= 65) & (distances[:, 2] <= 110)
    # Require three neighbors within 120 km; no extrapolation outside the hull.
    raw = np.exp(-.5*(distances[supported]/60)**2)/(distances[supported]**2+20**2)
    raw[distances[supported] > 120] = 0
    weights = capped_weights(raw)
    values = np.array([value(row, field) for row in candidates])
    if field == "wind":
        vectors = (values[indices[supported]]*weights[:, :, None]).sum(axis=1)
        u.ravel()[supported] = vectors[:, 0]; v.ravel()[supported] = vectors[:, 1]
        z.ravel()[supported] = np.linalg.norm(vectors, axis=1)
    else:
        z.ravel()[supported] = (values[indices[supported]]*weights).sum(axis=1)
    return lons, lats, z, u, v, len(candidates)


def image(z, palette, banded=False):
    from PIL import ImageColor
    colors = np.array([ImageColor.getrgb(color) for _, color in palette], dtype=np.uint8)
    stops = np.array([level for level, _ in palette])
    valid = np.isfinite(z)
    if banded:
        # Refine the scalar field first, then classify its values. Resizing a
        # colored raster would blend bands into colors absent from the legend.
        size = (z.shape[1]*4, z.shape[0]*4)
        numerator = np.array(Image.fromarray(np.where(valid, z, 0).astype(np.float32)).resize(size, Image.Resampling.BILINEAR))
        denominator = np.array(Image.fromarray(valid.astype(np.float32)).resize(size, Image.Resampling.BILINEAR))
        refined = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)
        valid = np.array(Image.fromarray(valid.astype(np.uint8)).resize(size, Image.Resampling.NEAREST)).astype(bool)
        indexes = np.clip(np.searchsorted(stops, refined, side="right")-1, 0, len(colors)-2)
        rgba = np.zeros((*refined.shape, 4), dtype=np.uint8)
        rgba[:, :, :3] = colors[indexes]
        rgba[:, :, 3] = np.where(valid, 255, 0)
    else:
        rgba = np.zeros((*z.shape, 4), dtype=np.uint8)
        for channel in range(3):
            rgba[:, :, channel] = np.interp(np.nan_to_num(z), stops, colors[:, channel]).astype(np.uint8)
        rgba[:, :, 3] = np.where(valid, 200, 0)
    output = io.BytesIO()
    Image.fromarray(rgba[::-1]).save(output, format="PNG")
    return output.getvalue()


def lines(lons, lats, z, step):
    if not np.isfinite(z).any():
        return []
    generator = contourpy.contour_generator(x=lons, y=lats, z=np.ma.masked_invalid(z))
    start = math.ceil(float(np.nanmin(z))/step)*step
    result = []
    for level in np.arange(start, float(np.nanmax(z))+.001, step):
        for line in generator.lines(float(level)):
            if len(line) >= 3:
                result.append({"type": "Feature", "properties": {"value": float(level)},
                               "geometry": {"type": "LineString", "coordinates": np.round(line, 4).tolist()}})
    return result


def artifact_prefix(hour, rows):
    readings = [{k: v for k, v in row.items() if k != "analysisQc"}
                for row in sorted(rows, key=lambda row: row["stationKey"])]
    digest = hashlib.sha256(json.dumps(readings, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()[:16]
    label = hour.replace("-", "").replace(":", "")[:13].replace("T", "")
    return "analysis/"+VERSION+"/"+label+"/"+digest


def prepare(data, store):
    """Prepare only the newest hour; past immutable analysis links are retained."""
    rows = data["stations"]
    screen(rows)
    for frame in data["history"]:
        if frame["hour"] == data["hour"]:
            frame["stations"] = rows
    prefix = artifact_prefix(data["hour"], rows)
    result = {"version": VERSION, "hour": data["hour"], "bounds": BOUNDS, "fields": {},
              "method": "Local weighted analysis, 40% maximum station influence, no extrapolation; neighborhood screening is not official instrument QC."}
    for field in FIELDS:
        lons, lats, z, u, v, used = grid(rows, field)
        key = prefix+"/"+field+".png"
        store.write(key, image(z, PALETTES[field], banded=True), "image/png")
        counts = Counter(r["analysisQc"][field]["status"] for r in rows)
        arrows = []
        if field == "wind":
            for iy in range(4, len(lats), 8):
                for ix in range(4, len(lons), 8):
                    if np.isfinite(z[iy, ix]) and z[iy, ix] >= .5:
                        arrows.append({"lat": round(float(lats[iy]), 4), "lon": round(float(lons[ix]), 4),
                                       "speed": round(float(z[iy, ix]), 1),
                                       "direction": round(float(np.degrees(np.arctan2(-u[iy, ix], -v[iy, ix])) % 360), 1)})
        result["fields"][field] = {"imageUrl": "/api/prepared/"+key, "palette": PALETTES[field], "paletteMode": "discrete", "interval": 5,
              "contours": {"type": "FeatureCollection", "features": lines(lons, lats, z, 5)},
              "arrows": arrows, "qc": dict(counts), "used": used, "supportedCells": int(np.isfinite(z).sum())}
    key = prefix+"/manifest.json"
    store.write_json(key, result)
    for frame in data["history"]:
        if frame["hour"] == data["hour"]:
            frame["analysisUrl"] = "/api/prepared/"+key
    data["analysisVersion"] = VERSION
    return result


def prepare_history(data, store):
    """Refresh saved hours on a style migration without refetching observations."""
    for frame in data["history"]:
        if not frame.get("stations") or frame.get("analysisUrl", "").startswith("/api/prepared/"+artifact_prefix(frame["hour"], frame["stations"])+"/"):
            continue
        historical = {"hour": frame["hour"], "stations": frame["stations"], "history": [frame]}
        prepare(historical, store)
    # The current hour may be empty only in an invalid/incomplete source object.
    # Ordinary hourly collection supplies at least one station.
    latest = next((frame for frame in data["history"] if frame["hour"] == data["hour"]), None)
    if latest and latest.get("analysisUrl") and ("/"+VERSION+"/") in latest["analysisUrl"]:
        data["stations"] = latest["stations"]
        data["analysisVersion"] = VERSION
    else:
        prepare(data, store)


def prepare_maps(data, store):
    """Derive immutable map assets from saved reports without changing observations."""
    from copy import deepcopy
    previous = store.read_json("live/maps.json") or {}
    signature = hashlib.sha256(json.dumps(
        [(f["hour"], artifact_prefix(f["hour"], f["stations"])) for f in data["history"]],
        separators=(",", ":")).encode()).hexdigest()
    if previous.get("version") == VERSION and previous.get("signature") == signature:
        return {"status": "already prepared", "hours": len(previous["history"])}
    work = deepcopy(data)
    old = {f["hour"]: f for f in previous.get("history", [])} if previous.get("version") == VERSION else {}
    for frame in work["history"]:
        frame.pop("analysisUrl", None)
        if frame["stations"] and frame["hour"] in old:
            frame["analysisUrl"] = old[frame["hour"]].get("analysisUrl", "")
    prepare_history(work, store)
    result = {"version": VERSION, "signature": signature, "hour": data["hour"],
              "checkedAt": data["checkedAt"], "bounds": data["bounds"],
              "source": "Official airport METARs · NOAA Aviation Weather Center",
              "windowMinutes": 10, "history": [
                  {"hour": f["hour"], "stationCount": len(f["stations"]),
                   **({"analysisUrl": f["analysisUrl"]} if f.get("analysisUrl") else {})}
                  for f in work["history"]]}
    # Publish the index only after every immutable asset is safely saved.
    store.write_json("live/maps.json", result)
    return {"status": "prepared", "hours": sum(bool(f.get("analysisUrl")) for f in result["history"])}
