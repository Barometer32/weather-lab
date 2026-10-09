"""Small GRIB byte-range downloads, exact timestamps, equal station/model weights."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging
import math
import re
import time
from threading import Lock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

UTC = timezone.utc
SCHEMA_VERSION = 3
LOCATIONS = {"KFCM": (44.8272, -93.4571), "KMSP": (44.8831, -93.2289), "KMIC": (45.0621, -93.3539)}
BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com"
FIELDS = {
    "temperatureK": ("TMP", "2 m above ground"),
    "dewpointK": ("DPT", "2 m above ground"),
    "u10": ("UGRD", "10 m above ground"), "v10": ("VGRD", "10 m above ground"),
    "precipTotalMm": ("APCP", "surface"),
    "lowCloudPct": ("LCDC", "low cloud layer"),
    "midCloudPct": ("MCDC", "middle cloud layer"),
    "highCloudPct": ("HCDC", "high cloud layer"),
}
CORE = {"temperatureK", "dewpointK", "u10", "v10", "precipTotalMm"}
GRID_KEYS = ("gridType", "Nx", "Ny", "latitudeOfFirstGridPoint", "longitudeOfFirstGridPoint",
             "Dx", "Dy", "LoV", "LaD", "Latin1", "Latin2", "scanningMode", "numberOfPoints", "shapeOfTheEarth", "radius")
_grid_points = {}
_grid_lock = Lock()


class ModelUnavailable(RuntimeError):
    """A model cycle is not published with all required forecast hours yet."""


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def target_cycle(now):
    # At 13:45 UTC choose 12Z; at 00:45 choose the previous day's 23Z.
    return (now.astimezone(UTC) - timedelta(hours=1, minutes=45)).replace(minute=0, second=0, microsecond=0)


def fetch(url, start=None, end=None):
    headers = {"User-Agent": "Barometer32-weather-lab/1.0", "Accept-Encoding": "identity"}
    if start is not None:
        headers["Range"] = f"bytes={start}-{end if end is not None else ''}"
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=45) as response:
                if start is not None:
                    expected = f"bytes {start}-"
                    if response.status != 206 or not response.headers.get("Content-Range", "").startswith(expected):
                        raise ValueError("Upstream ignored byte range; refusing a full model download")
                limit = end - start + 1 if end is not None else 16_000_000
                data = response.read(limit + 1)
                if len(data) > limit or (end is not None and len(data) != limit):
                    raise ValueError("Unexpected model download size")
                return data
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def model_urls(model, cycle, hour):
    if model == "HRRR":
        return [f"{BASE}/hrrr/prod/hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf{hour:02}.grib2"]
    # Detect availability rather than assuming the operational transition date.
    return [f"{BASE}/rrfs/{feed}/rrfs.{cycle:%Y%m%d}/{cycle:%H}/rrfs.t{cycle:%H}z.2dfld.3km{kind}.f{hour:03}.conus.grib2"
            for feed in ("prod", "para") for kind in ("", ".subh")]


def parse_index(text):
    rows = []
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) >= 6 and parts[0].isdigit() and parts[1].isdigit():
            rows.append({"offset": int(parts[1]), "cycle": parts[2], "parameter": parts[3], "level": parts[4], "period": parts[5]})
    for i, row in enumerate(rows):
        row["end"] = rows[i + 1]["offset"] - 1 if i + 1 < len(rows) else None
    return rows


def selected_records(text, cycle, hour):
    output = {}
    for row in parse_index(text):
        if row["cycle"] != f"d={cycle:%Y%m%d%H}":
            continue
        for key, (parameter, level) in FIELDS.items():
            if row["parameter"] != parameter:
                continue
            if level == "entire atmosphere":
                if not row["level"].startswith(level):
                    continue
            elif row["level"] != level:
                continue
            # Subhourly RRFS contains :15/:30/:45 AND the full hour. Never mix them.
            expected = (f"0-{hour} hour acc fcst", f"0-{hour * 60} min acc fcst") if key == "precipTotalMm" else (f"{hour} hour fcst", f"{hour * 60} min fcst")
            if row["period"] in expected:
                output[key] = row
    missing = CORE - output.keys()
    if missing:
        raise ValueError(f"Missing exact-hour fields: {sorted(missing)}")
    return output


def locate(model, cycle):
    for url in model_urls(model, cycle, 18):
        try:
            index = fetch(url + ".idx").decode()
            selected_records(index, cycle, 18)
            return url, index
        except HTTPError as exc:
            if exc.code not in (403, 404):
                raise
        except ValueError:
            logging.warning("Incomplete or unsupported index at %s", url)
    raise ModelUnavailable(f"{model} {cycle:%Y-%m-%d %HZ} is not complete through forecast hour 18")


def lambert_rotation(longitude, orientation, latitude1, latitude2):
    """Meridian convergence in radians for the spherical Lambert model grids."""
    p1, p2 = math.radians(latitude1), math.radians(latitude2)
    if abs(p1 - p2) < 1e-10:
        cone = math.sin(p1)
    else:
        cone = math.log(math.cos(p1) / math.cos(p2)) / math.log(
            math.tan(math.pi / 4 + p2 / 2) / math.tan(math.pi / 4 + p1 / 2))
    if not math.isfinite(cone) or abs(cone) < 1e-10:
        raise ValueError("Unsupported Lambert standard parallels")
    delta = (longitude - orientation + 180) % 360 - 180
    return cone * math.radians(delta)


def earth_wind(u, v, angle):
    """Rotate grid x/y components to true east/north before any averaging."""
    return u * math.cos(angle) + v * math.sin(angle), -u * math.sin(angle) + v * math.cos(angle)


def decode_points(data, cycle, hour, key, wind_metadata=None):
    import eccodes as ec
    handle = ec.codes_new_from_message(data)
    if handle is None:
        raise ValueError("Missing GRIB message")
    try:
        valid = datetime.strptime(str(ec.codes_get(handle, "validityDate")) + f'{ec.codes_get(handle, "validityTime"):04}', "%Y%m%d%H%M").replace(tzinfo=UTC)
        if valid != cycle + timedelta(hours=hour):
            raise ValueError("GRIB valid time differs from requested hour")
        if int(ec.codes_get(handle, "dataDate")) != int(cycle.strftime("%Y%m%d")) or int(ec.codes_get(handle, "dataTime")) != cycle.hour * 100:
            raise ValueError("GRIB model cycle differs from index")
        if key == "precipTotalMm" and float(ec.codes_get(handle, "startStep")) != 0:
            raise ValueError("Precipitation must be cumulative from initialization")
        # These feeds use Lambert grids. Find station indices once per exact
        # grid geometry, then unpack only the selected values for each field.
        # Repeating nearest-point searches rebuilds millions of coordinates.
        geometry = tuple(ec.codes_get(handle, key) for key in GRID_KEYS)
        if geometry[0] != "lambert":
            raise ValueError("Unsupported model grid geometry")
        with _grid_lock:
            if geometry not in _grid_points:
                nearest = ec.codes_grib_find_nearest_multiple(handle, False,
                    [p[0] for p in LOCATIONS.values()], [p[1] % 360 for p in LOCATIONS.values()])
                if any(p["distance"] > 8 for p in nearest):
                    raise ValueError("Station is too far from a model grid point")
                _grid_points[geometry] = tuple((p["index"], p["lon"]) for p in nearest)
            nearest_points = _grid_points[geometry]
        indices = [p[0] for p in nearest_points]
        if key in ("u10", "v10"):
            if wind_metadata is None:
                raise ValueError("Wind components require grid orientation metadata")
            relative = int(ec.codes_get(handle, "uvRelativeToGrid"))
            if relative not in (0, 1):
                raise ValueError("Unknown wind component orientation")
            if relative and int(ec.codes_get(handle, "shapeOfTheEarth")) not in (0, 1, 6, 8):
                raise ValueError("Unsupported non-spherical Lambert wind grid")
            for station, (_, longitude) in zip(LOCATIONS, nearest_points):
                angle = lambert_rotation(longitude, ec.codes_get(handle, "LoVInDegrees"),
                    ec.codes_get(handle, "Latin1InDegrees"), ec.codes_get(handle, "Latin2InDegrees")) if relative else 0.0
                wind_metadata[station][key] = (geometry, angle)
        selected = ec.codes_get_elements(handle, "values", indices)
        values = {}
        for station, selected_value in zip(LOCATIONS, selected):
            value = float(selected_value)
            if not math.isfinite(value) or abs(value) >= 1e10:
                raise ValueError(f"Invalid model value for {station}")
            values[station] = value
        return values
    finally:
        ec.codes_release(handle)


def collect_hour(model, cycle, hour, final_url, final_index):
    url = re.sub(r'f(?:\d{2}|\d{3})(?=\.grib2|\.conus)', lambda _: f'f{hour:02}' if model == "HRRR" else f'f{hour:03}', final_url)
    records = selected_records(final_index if hour == 18 else fetch(url + ".idx").decode(), cycle, hour)
    points = {station: {} for station in LOCATIONS}
    wind_metadata = {station: {} for station in LOCATIONS}
    # Consolidate nearby fields to avoid hundreds of small HTTP round trips.
    # Fetching a few intervening messages is cheaper than separate long waits.
    groups = []
    for item in sorted(records.items(), key=lambda item: item[1]["offset"]):
        record = item[1]
        if (groups and groups[-1][-1][1]["end"] is not None and record["end"] is not None
                and record["offset"] - groups[-1][-1][1]["end"] <= 3_000_000
                and record["end"] - groups[-1][0][1]["offset"] < 32_000_000):
            groups[-1].append(item)
        else:
            groups.append([item])
    for group in groups:
        start, end = group[0][1]["offset"], group[-1][1]["end"]
        chunk = fetch(url, start, end)
        for key, record in group:
            message_end = record["end"] - start + 1 if record["end"] is not None else len(chunk)
            values = decode_points(chunk[record["offset"] - start:message_end], cycle, hour, key, wind_metadata)
            for station, value in values.items():
                points[station][key] = value
    for station, point in points.items():
        if wind_metadata[station]["u10"] != wind_metadata[station]["v10"]:
            raise ValueError("U/V components use different grids or orientations")
        angle = wind_metadata[station]["u10"][1]
        point["east10"], point["north10"] = earth_wind(point.pop("u10"), point.pop("v10"), angle)
    return hour, points


def collect_model(model, cycle, located):
    url, index = located
    with ThreadPoolExecutor(max_workers=2) as pool:
        pairs = list(pool.map(lambda h: collect_hour(model, cycle, h, url, index), range(1, 19)))
    return dict(pairs)


def checked_point(point):
    t, d, u, v = (point[key] for key in ("temperatureK", "dewpointK", "east10", "north10"))
    if not all(math.isfinite(x) for x in (t, d, u, v)) or not 183 <= d <= t + 0.5 or not 183 <= t <= 333 or math.hypot(u, v) > 100:
        raise ValueError("Model temperature/dewpoint/wind failed range QA")
    rain = point["precipTotalMm"]
    if not math.isfinite(rain) or not 0 <= rain <= 2000:
        raise ValueError("Model precipitation failed range QA")
    tc, dc = t - 273.15, d - 273.15
    result = {"tempF": tc * 1.8 + 32, "dewpointF": dc * 1.8 + 32,
              "east10": u, "north10": v}
    for key in ("lowCloudPct", "midCloudPct", "highCloudPct"):
        value = point.get(key)
        result[key] = min(100, max(0, value)) if value is not None and -0.01 <= value <= 100.01 else None
    return result


def blend(models, cycle, sources, now=None):
    hours = []
    for hour in range(1, 18):
        points = []
        for model in ("HRRR", "RRFS"):
            for station in LOCATIONS:
                raw = models[model][hour][station]
                values = checked_point(raw)
                following = models[model][hour + 1][station]
                checked_point(following)  # Validate the final interval endpoint as well.
                diff = following["precipTotalMm"] - raw["precipTotalMm"]
                if diff < -0.05:
                    raise ValueError("Cumulative model precipitation decreased")
                values["precipIn"] = max(0, diff) / 25.4
                points.append((model, values))
        row = {"time": iso(cycle + timedelta(hours=hour)), "precipEnd": iso(cycle + timedelta(hours=hour + 1)), "forecastHour": hour, "contributors": {}}
        for key in points[0][1]:
            if key in ("east10", "north10"):
                continue
            valid = [(model, p[key]) for model, p in points if p[key] is not None]
            row[key] = round(sum(v for _, v in valid) / len(valid), 3 if key == "precipIn" else 1) if valid else None
            row["contributors"][key] = sorted({m for m, _ in valid})
        east = sum(p["east10"] for _, p in points) / len(points)
        north = sum(p["north10"] for _, p in points) / len(points)
        speed = math.hypot(east, north) * 2.236936
        row["windMph"] = round(speed, 1)
        row["windDirection"] = round(math.degrees(math.atan2(-east, -north)) % 360, 1) % 360 if speed >= 0.5 else None
        row["contributors"]["windMph"] = row["contributors"]["windDirection"] = ["HRRR", "RRFS"]
        row["qa"] = "passed"  # All six core contributors required; optional fields have provenance.
        hours.append(row)
    return {"schemaVersion": SCHEMA_VERSION, "cycle": iso(cycle), "publishedAt": iso(now or datetime.now(UTC)),
            "windowStart": hours[0]["time"], "windowEnd": hours[-1]["precipEnd"], "durationHours": 17,
            "stations": list(LOCATIONS), "weights": {"HRRR": 0.5, "RRFS": 0.5},
            "sources": sources, "hours": hours,
            "precipTotalIn": round(sum(h["precipIn"] or 0 for h in hours), 3),
            "method": "Equal HRRR/RRFS and station weights. Nearest grid cell at each airport. No AI or observation correction. Wind uses averaged earth-relative east/north components; direction is FROM true north. Rain covers the following hour and is liquid-equivalent amount, not probability. Cloud fields with only one source are identified."}
