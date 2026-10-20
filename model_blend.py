"""Three-airport, equal-model HRRR/RRFS guidance from NOAA GRIB2 ranges.

Only completed common cycles are published. P01 is the native preceding
one-hour APCP bucket, never the since-initialization accumulation.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import logging
import math
import threading
import time
from http.client import IncompleteRead
from urllib.error import HTTPError
from urllib.request import Request, urlopen

VERSION = "hrrr-rrfs-three-airports-v1"
UTC = timezone.utc
HOURS = tuple(range(2, 18))
# NOAA Aviation Weather Center station catalog, checked 2026-10-20.
STATIONS = {"KFCM": (44.83215, -93.47049), "KMIC": (45.0623, -93.35108),
            "KMSP": (44.88523, -93.23132)}
ROOTS = {"HRRR": "https://noaa-hrrr-bdp-pds.s3.amazonaws.com",
         "RRFS": "https://noaa-rrfs-ops-pds.s3.amazonaws.com"}
log = logging.getLogger(__name__)


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def source_url(model, cycle, hour):
    if model == "HRRR":
        path = f"hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf{hour:02d}.grib2"
    else:
        path = f"rrfs.{cycle:%Y%m%d}/{cycle:%H}/rrfs.t{cycle:%H}z.2dfld.3km.f{hour:03d}.conus.grib2"
    return ROOTS[model] + "/" + path


def _fetch_once(url, byte_range=None):
    headers = {"User-Agent": "J-Weather/1.0 NOAA point guidance"}
    limit = 200000 if byte_range is None else 12000000
    if byte_range is not None:
        start, end = byte_range
        if end < start or end-start+1 > limit:
            raise ValueError("GRIB field exceeds the bounded download size")
        headers["Range"] = f"bytes={start}-{end}"
    with urlopen(Request(url, headers=headers), timeout=35) as response:
        if byte_range is not None:
            if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-{end}/"):
                raise ValueError("Source did not honor the exact GRIB byte range")
        payload = response.read(limit+1)
    if len(payload) > limit or (byte_range is not None and len(payload) != end-start+1):
        raise ValueError("Incomplete or oversized model response")
    return payload


def fetch(url, byte_range=None):
    for attempt in range(2):
        try:
            return _fetch_once(url, byte_range)
        except HTTPError as error:
            if error.code not in {408, 429, 500, 502, 503, 504} or attempt:
                raise
        except (OSError, IncompleteRead, ValueError):
            if attempt:
                raise
        time.sleep(.5)


def inventory(text, cycle, hour):
    lines = [line.split(":") for line in text.splitlines() if line.strip()]
    fields = {}
    expected = f"d={cycle:%Y%m%d%H}"
    for left, right in zip(lines, lines[1:]):
        if len(left) < 6 or left[2] != expected:
            continue
        variable, level, period = left[3:6]
        key = None
        if period == f"{hour} hour fcst":
            key = {("TMP", "2 m above ground"): "tempK",
                   ("DPT", "2 m above ground"): "dewK",
                   ("UGRD", "10 m above ground"): "u",
                   ("VGRD", "10 m above ground"): "v",
                   ("HGT", "surface"): "terrainM",
                   ("HGT", "cloud ceiling"): "ceilingM"}.get((variable, level))
            if variable == "TCDC" and level.startswith("entire atmosphere"):
                key = "cloudPct"
        elif variable == "APCP" and level == "surface" and period == f"{hour-1}-{hour} hour acc fcst":
            key = "precipMm"
        if key:
            start, end = int(left[1]), int(right[1])-1
            if key in fields or end < start:
                raise ValueError("Ambiguous or invalid model inventory")
            fields[key] = (start, end)
    missing = {"tempK", "dewK", "u", "v", "precipMm"} - fields.keys()
    if missing:
        raise ValueError("Model inventory missing hourly fields: " + ", ".join(sorted(missing)))
    return fields


def earth_wind(u, v, longitude, lov, latin1, latin2):
    """Inverse Lambert meridian convergence, grid-relative to east/north."""
    p1, p2 = math.radians(latin1), math.radians(latin2)
    cone = (math.sin(p1) if abs(p1-p2) < 1e-9 else
            math.log(math.cos(p1)/math.cos(p2)) /
            math.log(math.tan(math.pi/4+p2/2)/math.tan(math.pi/4+p1/2)))
    angle = math.radians((longitude-lov+180) % 360-180)*cone
    return u*math.cos(angle)+v*math.sin(angle), -u*math.sin(angle)+v*math.cos(angle)


class PointDecoder:
    """Cache nearest-cell indices by exact GRIB grid; serialize C decoding."""
    def __init__(self):
        self.grids = {}
        self.lock = threading.Lock()

    def decode(self, payload, cycle, hour, field):
        import eccodes as ec
        with self.lock:
            handle = ec.codes_new_from_message(payload)
            if handle is None:
                raise ValueError("Source is not a GRIB message")
            try:
                category, parameter, surfaces, level = {
                    "tempK": (0, 0, (103,), 2), "dewK": (0, 6, (103,), 2),
                    "u": (2, 2, (103,), 10), "v": (2, 3, (103,), 10),
                    "precipMm": (1, 8, (1,), None), "cloudPct": (6, 1, (10, 200), None),
                    "terrainM": (3, 5, (1,), None), "ceilingM": (3, 5, (215,), None)
                }[field]
                if (ec.codes_get(handle, "discipline") != 0
                        or ec.codes_get(handle, "parameterCategory") != category
                        or ec.codes_get(handle, "parameterNumber") != parameter
                        or ec.codes_get_long(handle, "typeOfFirstFixedSurface") not in surfaces
                        or (level is not None and ec.codes_get(handle, "level") != level)):
                    raise ValueError("GRIB parameter or level does not match the selected field")
                if (ec.codes_get(handle, "dataDate") != int(cycle.strftime("%Y%m%d"))
                        or ec.codes_get(handle, "dataTime") != cycle.hour*100
                        or ec.codes_get(handle, "stepUnits") != 1
                        or ec.codes_get(handle, "endStep") != hour):
                    raise ValueError("GRIB cycle or valid time does not match the selected run")
                start = ec.codes_get(handle, "startStep")
                if field == "precipMm":
                    if start != hour-1 or ec.codes_get(handle, "stepType") != "accum":
                        raise ValueError("Precipitation is not the exact preceding one-hour bucket")
                elif start != hour or ec.codes_get(handle, "stepType") != "instant":
                    raise ValueError("Expected an instantaneous model field")
                unit = ec.codes_get(handle, "units")
                allowed = {"tempK": ("K",), "dewK": ("K",), "u": ("m s**-1", "m s-1"),
                           "v": ("m s**-1", "m s-1"), "precipMm": ("kg m**-2", "kg m-2"),
                           "cloudPct": ("%",), "ceilingM": ("gpm", "m"), "terrainM": ("gpm", "m")}
                if unit not in allowed[field]:
                    raise ValueError(f"Unexpected {field} units: {unit}")
                grid = ec.codes_get(handle, "md5Section3")
                if grid not in self.grids:
                    cells = [ec.codes_grib_find_nearest(handle, lat, lon)[0]
                             for lat, lon in STATIONS.values()]
                    if any(cell["distance"] > 5 for cell in cells):
                        raise ValueError("Model cell is too far from an airport")
                    self.grids[grid] = cells
                cells = self.grids[grid]
                values = ec.codes_get_elements(handle, "values", [cell["index"] for cell in cells])
                missing = ec.codes_get(handle, "missingValue")
                result = {}
                for station, cell, value in zip(STATIONS, cells, values):
                    value = float(value)
                    if not math.isfinite(value) or value == missing:
                        value = None
                    result[station] = value
                rotation = None
                if field in ("u", "v") and ec.codes_get(handle, "uvRelativeToGrid"):
                    if ec.codes_get(handle, "gridType") != "lambert":
                        raise ValueError("Unsupported grid-relative wind projection")
                    rotation = {"lov": ec.codes_get(handle, "LoVInDegrees"),
                                "latin1": ec.codes_get(handle, "Latin1InDegrees"),
                                "latin2": ec.codes_get(handle, "Latin2InDegrees"),
                                "longitudes": dict(zip(STATIONS, [cell["lon"] for cell in cells]))}
                return result, rotation
            finally:
                ec.codes_release(handle)


def valid(value, low, high):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def cloud_category(percent):
    if percent is None:
        return None
    return next(label for limit, label in [(6.25, "CL"), (31.25, "FW"), (56.25, "SC"), (93.75, "BK"), (100, "OV")] if percent <= limit)


def mean(values):
    return sum(values)/len(values)


def blend_hour(cycle, hour, points):
    if set(points) != {"HRRR", "RRFS"} or any(set(rows) != set(STATIONS) for rows in points.values()):
        raise ValueError("Both models and all three airport points are required")
    samples = [point for model in points.values() for point in model.values()]
    for point in samples:
        if not all(valid(point.get(key), low, high) for key, low, high in
                   [("tempK", 180, 335), ("dewK", 150, 335), ("u", -150, 150), ("v", -150, 150), ("precipMm", 0, 600)]):
            raise ValueError("Missing or out-of-range required model value")
        if point["dewK"] > point["tempK"]+0.5:
            raise ValueError("Model dew point exceeds temperature")
    u, v = mean([p["u"] for p in samples]), mean([p["v"] for p in samples])
    speed = math.hypot(u, v)
    cloud = mean([p["cloudPct"] for p in samples]) if all(valid(p.get("cloudPct"), 0, 100) for p in samples) else None
    # Missing/no-ceiling is not zero. Do not average just the cloudy subset.
    ceilings = [p.get("ceilingFtAGL") for p in samples]
    ceiling = mean(ceilings) if all(valid(value, 0, 60000) for value in ceilings) else None
    return {"forecastHour": hour, "validTime": iso(cycle+timedelta(hours=hour)),
            "precipStart": iso(cycle+timedelta(hours=hour-1)),
            "precipEnd": iso(cycle+timedelta(hours=hour)),
            "tempF": (mean([p["tempK"] for p in samples])-273.15)*1.8+32,
            "dewpointF": (mean([p["dewK"] for p in samples])-273.15)*1.8+32,
            "wind": {"speedKt": speed*1.9438444924,
                     "direction": round(math.degrees(math.atan2(-u, -v)), 8) % 360 if speed >= 0.25 else None},
            "precipIn": mean([p["precipMm"] for p in samples])/25.4,
            "cloudPct": cloud, "cloudCategory": cloud_category(cloud), "ceilingFtAGL": ceiling}


def read_hour(model, cycle, hour, decoder, downloader=fetch, index=None):
    url = source_url(model, cycle, hour)
    index = index if index is not None else downloader(url+".idx").decode()
    ranges = inventory(index, cycle, hour)
    values, rotation = {}, {}
    for field, byte_range in ranges.items():
        try:
            values[field], rotation[field] = decoder.decode(downloader(url, byte_range), cycle, hour, field)
        except Exception:
            if field in {"tempK", "dewK", "u", "v", "precipMm"}:
                raise
            log.warning("Optional %s %s f%03d unavailable", model, field, hour, exc_info=True)
    if rotation.get("u") != rotation.get("v"):
        raise ValueError("Wind component grids/rotation do not agree")
    points = {station: {field: data[station] for field, data in values.items()} for station in STATIONS}
    for station, point in points.items():
        if rotation.get("u") and valid(point.get("u"), -150, 150) and valid(point.get("v"), -150, 150):
            rot = rotation["u"]
            point["u"], point["v"] = earth_wind(point["u"], point["v"], rot["longitudes"][station], rot["lov"], rot["latin1"], rot["latin2"])
        ceiling, ground = point.get("ceilingM"), point.get("terrainM")
        point["ceilingFtAGL"] = ((max(0, ceiling-ground))*3.280839895
            if valid(ceiling, -500, 20000) and valid(ground, -500, 6000) and ceiling >= ground-10 else None)
    return points


def collect(store, now, downloader=fetch, decoder=None):
    previous = store.read_json("live/models.json")
    status = {"state": "probing", "checkedAt": iso(now), "completed": 0, "total": 32}
    store.write_json("live/models-status.json", status)
    try:
        cycle = None
        # Probe endpoints only. Current runs often are not finished yet.
        for lag in range(1, 7):
            candidate = (now-timedelta(hours=lag)).replace(minute=0, second=0, microsecond=0)
            if previous and previous.get("modelVersion") == VERSION and previous.get("cycleTime") == iso(candidate):
                status.update(state="ready", cycleTime=iso(candidate), completed=32)
                store.write_json("live/models-status.json", status)
                return {"status": "unchanged", "cycleTime": iso(candidate)}
            probes = {}
            try:
                for model in ROOTS:
                    text = downloader(source_url(model, candidate, 17)+".idx").decode()
                    inventory(text, candidate, 17)
                    probes[model] = text
            except Exception:
                continue
            cycle = candidate
            break
        if cycle is None:
            raise ValueError("No complete common HRRR/RRFS cycle in the last six hours")
        status.update(state="collecting", cycleTime=iso(cycle))
        store.write_json("live/models-status.json", status)
        decoder = decoder or PointDecoder()
        results = {hour: {} for hour in HOURS}
        # Bounded concurrent I/O; GRIB decoding stays serialized on one CPU.
        with ThreadPoolExecutor(max_workers=6) as pool:
            tasks = {pool.submit(read_hour, model, cycle, hour, decoder, downloader,
                                 probes[model] if hour == 17 else None): (model, hour)
                     for hour in HOURS for model in ROOTS}
            for task in as_completed(tasks):
                model, hour = tasks[task]
                results[hour][model] = task.result()
                status["completed"] += 1
                store.write_json("live/models-status.json", status)
        rows = [blend_hour(cycle, hour, results[hour]) for hour in HOURS]
        finished = datetime.now(UTC)
        data = {"modelVersion": VERSION, "cycleTime": iso(cycle), "fetchedAt": iso(finished),
                "checkedAt": iso(now), "models": ["HRRR", "RRFS"], "weights": {"HRRR": .5, "RRFS": .5},
                "stations": list(STATIONS), "hours": rows,
                "rrfsSource": ROOTS["RRFS"], "hrrrSource": ROOTS["HRRR"],
                "precipitationPeriod": "preceding-one-hour", "windUnit": "kt"}
        # One canonical write: no partial model, mixed cycle, or incomplete horizon.
        store.write_json("live/models.json", data)
        status.update(state="ready", checkedAt=iso(finished))
        store.write_json("live/models-status.json", status)
        return {"status": "prepared", "cycleTime": iso(cycle), "hours": len(rows)}
    except Exception as error:
        status.update(state="error", message=str(error)[:300])
        store.write_json("live/models-status.json", status)
        raise
