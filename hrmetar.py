"""Free, public NOAA MADIS HF-ASOS observations on five-minute marks."""
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import math
from statistics import mean
from urllib.error import HTTPError

STATIONS = ("KMSP", "KFCM", "KMIC")
BASE_URL = "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/hfmetar/netCDF/"
SNAPSHOT_NAME = "hrmetar-five-minute"
SNAPSHOT_KEY = f"live/{SNAPSHOT_NAME}.json"
MAX_FILE_BYTES = 32_000_000
MAX_AGE = timedelta(minutes=30)


def variable(dataset, *names):
    for name in names:
        if name in dataset.variables:
            return dataset.variables[name].data
    raise ValueError(f"MADIS HF-ASOS field missing: {names[0]}")


def whole_celsius(value):
    celsius = float(value) - 273.15
    if not math.isfinite(celsius) or not -90 <= celsius <= 60:
        return None
    integer = round(celsius)
    return integer if abs(celsius - integer) < .02 else None


def station_rows(compressed, now):
    from scipy.io import netcdf_file

    with gzip.GzipFile(fileobj=BytesIO(compressed)) as stream:
        payload = stream.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError("MADIS HF-ASOS file exceeds the supported size")
    rows = {}
    with netcdf_file(BytesIO(payload), mmap=False) as dataset:
        ids = variable(dataset, "stationId", "stationName")
        times = variable(dataset, "observationTime", "timeObs")
        temperatures = variable(dataset, "temperature")
        dewpoints = variable(dataset, "dewpoint")
        speeds = variable(dataset, "windSpeed")
        directions = variable(dataset, "windDir", "windDirection")
        earliest = (now - MAX_AGE).timestamp()
        for index, code in enumerate(ids):
            station = bytes(code).decode("ascii", errors="replace").strip("\x00 ")
            if len(station) == 3:
                station = "K" + station
            if station not in STATIONS:
                continue
            stamp = float(times[index])
            if not earliest <= stamp <= now.timestamp() or stamp % 300:
                continue
            temperature = whole_celsius(temperatures[index])
            dewpoint = whole_celsius(dewpoints[index])
            speed = float(speeds[index])
            if temperature is None or dewpoint is None or dewpoint > temperature or not 0 <= speed <= 110:
                continue
            direction = float(directions[index])
            rows.setdefault(stamp, {})[station] = {
                "tempC": temperature, "dewpointC": dewpoint, "wspd": speed * 1.94384449,
                "wdir": direction if 0 <= direction <= 360 else "VRB",
            }
    return rows


def latest_average(rows):
    from app import iso, wind_mean

    complete = [stamp for stamp, entries in rows.items() if all(station in entries for station in STATIONS)]
    if not complete:
        return None
    stamp = max(complete)
    entries = [rows[stamp][station] for station in STATIONS]
    wind = wind_mean(entries, speed_digits=8)
    direction = wind["direction"]
    return {
        "observedAt": iso(datetime.fromtimestamp(stamp, timezone.utc)),
        "tempC": mean(row["tempC"] for row in entries),
        "dewpointC": mean(row["dewpointC"] for row in entries),
        "windMph": math.floor(wind["speedMph"] + .5),
        "windDirection": direction % 360 if direction is not None else None,
    }


def collect(store, download, now):
    from app import iso

    previous = store.read_json(SNAPSHOT_KEY) or {}
    current = previous.get("current")
    if current and current["observedAt"] < iso(now - MAX_AGE):
        current = None
    hour = now.replace(minute=0, second=0, microsecond=0)
    buckets = (hour, hour - timedelta(hours=1))
    for index, bucket in enumerate(buckets):
        newest_possible = iso(bucket + timedelta(minutes=55))
        if index and (now - MAX_AGE > bucket + timedelta(minutes=55)
                      or current and current["observedAt"] >= newest_possible):
            break
        try:
            rows = station_rows(download(f"{BASE_URL}{bucket:%Y%m%d_%H00}.gz"), now)
        except HTTPError as error:
            if error.code != 404:
                raise
            continue
        candidate = latest_average(rows)
        if candidate and (not current or candidate["observedAt"] >= current["observedAt"]):
            current = candidate
    snapshot = {"checkedAt": iso(now), "current": current}
    store.write_json(SNAPSHOT_KEY, snapshot)
    return snapshot
