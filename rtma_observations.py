"""Three-point RTMA-RU trial; only the private collector downloads NOAA GRIBs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

UTC = timezone.utc
ROOT = "https://noaa-rtma-pds.s3.amazonaws.com"
KEY = "live/rtma-observations.json"
VERSION = "rtma-ru-three-point-v1"
# NOAA Aviation Weather Center station catalog, checked 2026-11-14.
STATIONS = (
    dict(station="KMIC", name="Crystal", lat=45.06230, lon=-93.35108),
    dict(station="KMSP", name="Minneapolis–St. Paul", lat=44.88523, lon=-93.23132),
    dict(station="KFCM", name="Flying Cloud", lat=44.83215, lon=-93.47049),
)
FIELDS = {"TMP": "2 m above ground", "DPT": "2 m above ground",
          "WIND": "10 m above ground", "WDIR": "10 m above ground"}
MPS_TO_MPH = 2.2369362920544


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch(url, start=None, end=None):
    headers = {"User-Agent": "Weather-Lab RTMA-RU trial (github.com/Barometer32/weather-lab)"}
    limit = 2_000_000
    if start is not None:
        if not 0 <= start <= end or end - start > 12_000_000:
            raise ValueError("Unexpected GRIB message size")
        headers["Range"] = f"bytes={start}-{end}"
        limit = end - start + 1
    with urlopen(Request(url, headers=headers), timeout=35) as response:
        if start is not None:
            content_range = response.headers.get("Content-Range", "")
            if response.status != 206 or not content_range.startswith(f"bytes {start}-{end}/"):
                raise ValueError("NOAA server did not honor the GRIB byte range")
        data = response.read(limit + 1)
        if len(data) > limit or (start is not None and len(data) != limit):
            raise ValueError("Incomplete or oversized NOAA response")
        return data


def available_cycles(now, previous=None, download=fetch):
    """Discover uploaded analyses, including yesterday when UTC crosses midnight."""
    found = []
    oldest = max(now - timedelta(hours=3), previous) if previous else now - timedelta(hours=3)
    for day in (now.date(), (now - timedelta(days=1)).date()):
        if day < oldest.date():
            continue
        prefix = f"rtma2p5_ru.{day:%Y%m%d}/"
        query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        token = None
        while True:
            if token:
                query["continuation-token"] = token
            tree = ET.fromstring(download(ROOT + "/?" + urlencode(query)))
            ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
            for item in tree.findall("s:Contents", ns):
                key = item.findtext("s:Key", namespaces=ns)
                match = re.fullmatch(re.escape(prefix) + r"rtma2p5_ru\.t(\d{2})(\d{2})z\.2dvaranl_ndfd\.grb2\.idx", key or "")
                if not match:
                    continue
                hour, minute = map(int, match.groups())
                if hour > 23 or minute not in (0, 15, 30, 45):
                    continue
                cycle = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
                if oldest <= cycle <= now and (previous is None or cycle > previous):
                    found.append((cycle, key[:-4], item.findtext("s:LastModified", namespaces=ns)))
            if tree.findtext("s:IsTruncated", namespaces=ns) != "true":
                break
            token = tree.findtext("s:NextContinuationToken", namespaces=ns)
            if not token:
                raise ValueError("Truncated NOAA listing has no continuation token")
        if found:
            break
    return sorted(found, reverse=True)


def message_ranges(index):
    rows = [line.split(":") for line in index.decode().splitlines() if line]
    if not rows or any(len(row) < 7 for row in rows):
        raise ValueError("Invalid NOAA GRIB inventory")
    offsets = [int(row[1]) for row in rows]
    if offsets != sorted(set(offsets)):
        raise ValueError("Invalid GRIB byte offsets")
    selected = {}
    for i, row in enumerate(rows):
        field = row[3]
        if field not in FIELDS or row[4] != FIELDS[field] or row[5] != "anl":
            continue
        if field in selected or i + 1 == len(rows):
            raise ValueError("Duplicate or unterminated RTMA field")
        selected[field] = (offsets[i], offsets[i + 1] - 1)
    if set(selected) != set(FIELDS):
        raise ValueError("The complete temperature, dewpoint and wind analysis is not ready")
    return selected


def decode(messages, cycle):
    # The PyPI wheel includes the native ecCodes library on Linux. Import only
    # inside the collector; the public web process never decodes national grids.
    import eccodes as ec
    grid_signature = None
    points = None
    readings = {}
    for field in FIELDS:
        data = messages[field]
        if not data.startswith(b"GRIB") or int.from_bytes(data[8:16], "big") != len(data) or not data.endswith(b"7777"):
            raise ValueError("Corrupt GRIB message")
        handle = ec.codes_new_from_message(data)
        try:
            stamp = f"{ec.codes_get(handle, 'validityDate'):08d}{ec.codes_get(handle, 'validityTime'):04d}"
            reference = f"{ec.codes_get(handle, 'dataDate'):08d}{ec.codes_get(handle, 'dataTime'):04d}"
            if stamp != cycle.strftime("%Y%m%d%H%M") or reference != stamp:
                raise ValueError("Mixed RTMA cycles or a forecast field")
            expected_units = "K" if field in ("TMP", "DPT") else "m s**-1" if field == "WIND" else "Degree true"
            if ec.codes_get(handle, "units") != expected_units:
                raise ValueError("Unexpected RTMA units")
            expected_name = {"TMP": "2t", "DPT": "2d", "WIND": "10si", "WDIR": "10wdir"}[field]
            if ec.codes_get(handle, "shortName") != expected_name:
                raise ValueError("Wrong RTMA variable or measurement height")
            keys = ("gridType", "Nx", "Ny", "latitudeOfFirstGridPointInDegrees",
                    "longitudeOfFirstGridPointInDegrees", "DxInMetres", "DyInMetres",
                    "LoVInDegrees", "Latin1InDegrees", "Latin2InDegrees", "radius",
                    "iScansNegatively", "jScansPositively", "jPointsAreConsecutive", "alternativeRowScanning")
            signature = tuple(ec.codes_get(handle, key) for key in keys)
            if grid_signature is None:
                grid_signature = signature
                points = [ec.codes_grib_find_nearest(handle, s["lat"], s["lon"] % 360)[0] for s in STATIONS]
                if any(p["distance"] > 5 for p in points):
                    raise ValueError("No nearby RTMA grid point")
            elif signature != grid_signature:
                raise ValueError("RTMA fields use different grids")
            readings[field] = list(ec.codes_get_elements(handle, "values", [p["index"] for p in points]))
        finally:
            ec.codes_release(handle)
    stations = []
    for i, station in enumerate(STATIONS):
        kelvin, dew_kelvin, speed, direction = (float(readings[k][i]) for k in FIELDS)
        if not all(map(math.isfinite, (kelvin, dew_kelvin, speed, direction))):
            raise ValueError("A station grid estimate is missing")
        if not (173.15 <= kelvin <= 333.15 and 173.15 <= dew_kelvin <= kelvin + .5
                and 0 <= speed <= 100 and 0 <= direction <= 360):
            raise ValueError("Implausible RTMA temperature, dewpoint or wind")
        point = points[i]
        stations.append({**station, "analysisTime": iso(cycle),
                         "tempC": kelvin - 273.15, "dewpointC": dew_kelvin - 273.15,
                         "tempF": (kelvin - 273.15) * 1.8 + 32,
                         "dewpointF": (dew_kelvin - 273.15) * 1.8 + 32,
                         "wind": {"speedMph": speed * MPS_TO_MPH, "direction": direction % 360},
                         "gridLat": point["lat"], "gridLon": (point["lon"] + 180) % 360 - 180,
                         "gridDistanceKm": point["distance"]})
    return stations


def average(stations):
    if [s["station"] for s in stations] != [s["station"] for s in STATIONS] or len({s["analysisTime"] for s in stations}) != 1:
        raise ValueError("All three locations must belong to the same analysis")
    temp_c = sum(s["tempC"] for s in stations) / 3
    dew_c = sum(s["dewpointC"] for s in stations) / 3
    speeds = [s["wind"]["speedMph"] for s in stations]
    east = sum(speed * math.sin(math.radians(s["wind"]["direction"])) for speed, s in zip(speeds, stations))
    north = sum(speed * math.cos(math.radians(s["wind"]["direction"])) for speed, s in zip(speeds, stations))
    direction = math.degrees(math.atan2(east, north)) % 360 if math.hypot(east, north) > max(1e-6, sum(speeds) * 1e-6) else None
    return {"tempF": temp_c * 1.8 + 32, "dewpointF": dew_c * 1.8 + 32,
            "wind": {"speedMph": sum(speeds) / 3, "direction": direction}}


def collect(store, now, download=fetch, decoder=decode):
    previous = store.read_json(KEY)
    if previous and previous.get("version") != VERSION:
        previous = None
    since = moment(previous["analysisTime"]) if previous else None
    cycles = available_cycles(now, since, download)
    if not cycles:
        if previous is None:
            raise ValueError("No published RTMA-RU analysis in the last three hours")
        store.write_json(KEY, {**previous, "checkedAt": iso(now)})
        return {"analysisTime": previous["analysisTime"], "newCycle": False}
    cycle, key, available_at = cycles[0]
    base = ROOT + "/" + key
    ranges = message_ranges(download(base + ".idx"))
    def get_field(item):
        field, (start, end) = item
        return field, download(base, start, end)
    with ThreadPoolExecutor(max_workers=2) as pool:
        messages = dict(pool.map(get_field, ranges.items()))
    stations = decoder(messages, cycle)
    mean = average(stations)
    prepared = {"version": VERSION, "source": "NOAA RTMA-RU", "sourceType": "gridded-analysis",
                "analysisTime": iso(cycle), "availableAt": available_at,
                "checkedAt": iso(now), "preparedAt": iso(datetime.now(UTC)),
                "sourceUrl": base, "stations": stations, "mean": mean,
                "analysisIntervalMinutes": 15, "checkIntervalSeconds": 60}
    store.write_json(KEY, prepared)
    return {"analysisTime": iso(cycle), "newCycle": True, "locations": 3}


def public_snapshot(data, now):
    if not data or data.get("version") != VERSION:
        raise ValueError("The first RTMA-RU analysis is being prepared")
    age = (now - moment(data["analysisTime"])).total_seconds()
    if age < -60:
        raise ValueError("RTMA analysis is in the future")
    average(data["stations"])
    return {**data, "serverTime": iso(now), "analysisAgeMinutes": max(0, age / 60),
            "sourceDelayed": age > 45 * 60,
            "collectionDelayed": (now - moment(data["checkedAt"])).total_seconds() > 5 * 60,
            "stale": age > 60 * 60 or (now - moment(data["checkedAt"])).total_seconds() > 5 * 60}


if __name__ == "__main__":
    from realtime import get_store
    store = get_store()
    if store is None:
        raise SystemExit("WEATHER_DATA_BUCKET is required")
    print(json.dumps(collect(store, datetime.now(UTC))))
