"""Conservative local surface analysis; original station readings stay intact.

These are neighborhood screens, not official NOAA MADIS verification. Suspect
fields are excluded independently, and sparse areas remain transparent.
"""
import io
import math
from collections import Counter

import contourpy
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree, Delaunay, QhullError

VERSION = "surface-v1"
FIELDS = ("tempF", "dewpointF", "wind")
PALETTES = {
    "tempF": [[-20,"#693b94"],[0,"#5358b2"],[20,"#4595cc"],[32,"#69c5d0"],[40,"#83cf91"],[50,"#d3e59a"],[60,"#f6e87b"],[70,"#f6ba5b"],[80,"#e66d43"],[90,"#c43742"],[110,"#8c2763"]],
    "dewpointF": [[-20,"#9c7958"],[10,"#d5b78b"],[30,"#eee0b9"],[40,"#d3e5a0"],[50,"#83c98b"],[60,"#42a88b"],[65,"#309baf"],[70,"#4076b9"],[80,"#7854a2"]],
    "wind": [[0,"#f0f3ed"],[5,"#c7e4d1"],[10,"#80c8b9"],[15,"#4aa6b6"],[20,"#487ab0"],[30,"#8159a7"],[40,"#ba5085"],[60,"#dc4b4b"]],
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


def grid(rows, field, nx=241, ny=161):
    # Uniform Mercator y keeps image overlays aligned with Leaflet's map.
    lons = np.linspace(-100, -85, nx)
    merc = np.linspace(np.arcsinh(np.tan(np.radians(40))), np.arcsinh(np.tan(np.radians(50))), ny)
    lats = np.degrees(np.arctan(np.sinh(merc)))
    z = np.full((ny, nx), np.nan)
    u = z.copy(); v = z.copy()
    candidates, cells = [], set()
    # Five-km de-clustering prevents highway clusters dominating the grid.
    ordered = sorted(rows, key=lambda r: (r.get("analysisQc", {}).get(field, {}).get("status") != "screened", not r.get("network", "").endswith("_ASOS"), r["stationKey"]))
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


def image(z, palette):
    from PIL import ImageColor
    colors = np.array([ImageColor.getrgb(color) for _, color in palette])
    stops = np.array([level for level, _ in palette])
    rgba = np.zeros((*z.shape, 4), dtype=np.uint8)
    for channel in range(3):
        rgba[:, :, channel] = np.interp(np.nan_to_num(z), stops, colors[:, channel]).astype(np.uint8)
    rgba[:, :, 3] = np.where(np.isfinite(z), 200, 0)
    output = io.BytesIO()
    # Bilinear display smooths grid pixels; the underlying support mask remains.
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


def prepare(data, store):
    """Prepare only the newest hour; past immutable analysis links are retained."""
    rows = data["stations"]
    screen(rows)
    for frame in data["history"]:
        if frame["hour"] == data["hour"]:
            frame["stations"] = rows
    prefix = "analysis/" + VERSION + "/" + data["hour"].replace("-", "").replace(":", "")[:13].replace("T", "")
    result = {"version": VERSION, "hour": data["hour"], "bounds": [[40, -100], [50, -85]], "fields": {},
              "method": "Local weighted analysis, 40% maximum station influence, no extrapolation; neighborhood screening is not official MADIS QC."}
    for field in FIELDS:
        lons, lats, z, u, v, used = grid(rows, field)
        key = prefix+"/"+field+".png"
        store.write(key, image(z, PALETTES[field]), "image/png")
        counts = Counter(r["analysisQc"][field]["status"] for r in rows)
        arrows = []
        if field == "wind":
            for iy in range(4, len(lats), 8):
                for ix in range(4, len(lons), 8):
                    if np.isfinite(z[iy, ix]) and z[iy, ix] >= .5:
                        arrows.append({"lat": round(float(lats[iy]), 4), "lon": round(float(lons[ix]), 4),
                                       "speed": round(float(z[iy, ix]), 1),
                                       "direction": round(float(np.degrees(np.arctan2(-u[iy, ix], -v[iy, ix])) % 360), 1)})
        result["fields"][field] = {"imageUrl": "/api/prepared/"+key, "palette": PALETTES[field],
              "contours": {"type": "FeatureCollection", "features": lines(lons, lats, z, 5 if field == "wind" else 2)},
              "arrows": arrows, "qc": dict(counts), "used": used, "supportedCells": int(np.isfinite(z).sum())}
    key = prefix+"/manifest.json"
    store.write_json(key, result)
    for frame in data["history"]:
        if frame["hour"] == data["hour"]:
            frame["analysisUrl"] = "/api/prepared/"+key
    data["analysisVersion"] = VERSION
    return result
