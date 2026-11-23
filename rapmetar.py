"""Prepare five-minute ASOS reports from the public NOAA MADIS HF-METAR feed."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import gzip
from io import BytesIO
import json
import math
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scipy.io import netcdf_file

SOURCE = "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/hfmetar/netCDF/"
# NOAA MADIS surface QC results: master, validity, and comparison checks.
QC_MASTER = 1
QC_VALIDITY = 2
QC_WIND_COMPARISONS = 16 | 32 | 64  # temporal, statistical spatial, spatial
WIND_LIMITS = {"windDir": 360, "windSpeed": 200 * (1852 / 3600)}
KEY = "live/rapmetar-v1.json"
VERSION = "noaa-hfmetar-celsius-v1"
STATES = {"ND", "SD", "IA", "MN", "WI"}
EXCLUDED = {"KSTP", "KCFE"}
MAX_AGE = 3600
_files = {}


@lru_cache(maxsize=1)
def inventory():
    path = Path(__file__).with_name("rapmetar-stations.json")
    return json.loads(path.read_text())["stations"]


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def file_url(hour):
    return SOURCE + hour.strftime("%Y%m%d_%H00.gz")


def fetch_file(url):
    previous = _files.get(url)
    headers = {"User-Agent": "Weather-Lab (https://github.com/Barometer32/weather-lab)"}
    if previous:
        if previous[1]:
            headers["If-None-Match"] = previous[1]
        elif previous[2]:
            headers["If-Modified-Since"] = previous[2]
    try:
        with urlopen(Request(url, headers=headers), timeout=20) as response:
            payload = response.read(8_000_001)
            if len(payload) > 8_000_000:
                raise ValueError("MADIS compressed file exceeds expected size")
            _files[url] = (payload, response.headers.get("ETag"), response.headers.get("Last-Modified"))
    except HTTPError as error:
        if error.code != 304 or previous is None:
            raise
        return previous[0]
    while len(_files) > 3:
        del _files[next(iter(_files))]
    return payload


def parse_file(payload, now):
    with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
        content = stream.read(30_000_001)
    if len(content) > 30_000_000:
        raise ValueError("MADIS expanded file exceeds expected size")
    rows = []
    with netcdf_file(BytesIO(content), mmap=False) as dataset:
        variables = dataset.variables
        expected_units = {"temperature": b"kelvin", "dewpoint": b"kelvin", "windDir": b"degree", "windSpeed": b"meter/sec"}
        required = {"stationId", "stationType", "observationTime", *expected_units}
        if not required <= variables.keys():
            raise ValueError("MADIS file missing required variables")
        if any(getattr(variables[key], "units", None) != unit for key, unit in expected_units.items()):
            raise ValueError("Unexpected MADIS measurement units")
        def measurement(name, index):
            field = variables[name]
            number = float(field[index])
            if not math.isfinite(number) or number in (getattr(field, "_FillValue", None), getattr(field, "missing_value", None)):
                return None
            descriptor = variables.get(name + "DD")
            dd = descriptor[index].tobytes().strip(b"\x00 ") if descriptor is not None else b""
            result = variables.get(name + "QCR")
            qcr = int(result[index]) if result is not None else 0
            internal = variables.get(name + "ICR")
            if internal is not None and int(internal[index]) != 0:
                return None
            scoped_wind = name in WIND_LIMITS
            if scoped_wind and (dd in (b"X", b"B") or not 0 <= number <= WIND_LIMITS[name]):
                return None
            if qcr:
                # Only waive comparison failures, and only when MADIS explicitly
                # ran and passed the validity check. Master is a summary bit.
                applied = variables.get(name + "QCA")
                if not (scoped_wind and dd == b"Q" and qcr & QC_WIND_COMPARISONS
                        and not qcr & ~(QC_MASTER | QC_WIND_COMPARISONS)
                        and applied is not None and int(applied[index]) & QC_VALIDITY):
                    return None
            status = variables.get(name + "Status")
            if scoped_wind and qcr and status is None:
                return None
            if status is not None and int(status[index]) not in (0, 16):
                # Reserved sensor-status codes do not establish a fault. Keep
                # them only with affirmative MADIS QC (V/S/G) and a clear QC
                # results word. Explicit sensor faults and missing/unknown
                # codes remain excluded, even if a numeric value is present.
                passed = dd in (b"V", b"S", b"G")
                reserved = int(status[index]) in (1, 4, 11, 13, 14, 15)
                if not (reserved and passed and result is not None and qcr == 0):
                    return None
            return number
        sites = inventory()
        for index, identifier in enumerate(variables["stationId"][:]):
            station = identifier.tobytes().decode("ascii", errors="replace").strip("\x00 ")
            if station not in sites or station in EXCLUDED or sites[station]["state"] not in STATES:
                continue
            if variables["stationType"][index].tobytes().strip(b"\x00 ") != b"HF-METAR":
                continue
            stamp = float(variables["observationTime"][index])
            if not math.isfinite(stamp) or stamp % 300 or not 0 <= now.timestamp() - stamp <= MAX_AGE:
                continue
            temperature, dewpoint = measurement("temperature", index), measurement("dewpoint", index)
            speed = measurement("windSpeed", index)
            rows.append({
                "station": station, **sites[station],
                "time": iso(datetime.fromtimestamp(stamp, timezone.utc)),
                "reportType": "HFMETAR",
                "tempC": round(temperature - 273.15, 2) if temperature is not None else None,
                "dewpointC": round(dewpoint - 273.15, 2) if dewpoint is not None else None,
                "wind": {"speedMph": speed * 3600 / 1609.344 if speed is not None else None,
                         "direction": measurement("windDir", index)},
            })
    return rows


def latest_reports(rows, now):
    latest = {}
    for row in rows:
        stamp = datetime.fromisoformat(row["time"])
        if not 0 <= (now - stamp).total_seconds() <= MAX_AGE:
            continue
        station = row["station"]
        if station not in latest or row["time"] >= latest[station]["time"]:
            latest[station] = row
    return sorted(latest.values(), key=lambda row: row["station"])


def collect(store, now, download=None):
    download = download or fetch_file
    hour = now.replace(minute=0, second=0, microsecond=0)
    fresh = []
    failure = None
    for target in (hour, hour - timedelta(hours=1)):
        try:
            fresh.extend(parse_file(download(file_url(target)), now))
        except HTTPError as error:
            if error.code == 429:
                raise
            # At the hour boundary NOAA may not have opened the new file yet.
            if error.code != 404:
                failure = error
        except (OSError, ValueError) as error:
            failure = error
    if not fresh:
        raise ValueError("No recent five-minute MADIS reports") from failure
    previous = store.read_json(KEY) or {}
    old = previous.get("stations", []) if previous.get("version") == VERSION else []
    saved = {"version": VERSION, "stations": latest_reports(old + fresh, now), "checkedAt": iso(now)}
    store.write_json(KEY, saved)
    return {"stations": len(present(saved, now)["stations"])}


def present(saved, now):
    if not saved or saved.get("version") != VERSION:
        raise ValueError("RAPMETAR observations are being prepared.")
    stations = []
    for row in latest_reports(saved["stations"], now):
        temp, dewpoint = row["tempC"], row["dewpointC"]
        if temp is None or dewpoint is None or not -100 <= dewpoint <= temp <= 65 or temp < -90:
            continue
        stations.append(row)
    newest = max((row["time"] for row in stations), default=None)
    return {"version": VERSION, "stations": stations, "temperatureUnit": "C", "windUnit": "mph", "updateIntervalSeconds": 300,
            "checkedAt": saved["checkedAt"], "newestObservationAt": newest, "serverTime": iso(now),
            "stale": (now - datetime.fromisoformat(saved["checkedAt"])).total_seconds() > 600}
