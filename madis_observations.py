"""Direct public NOAA MADIS five-minute ASOS data with conditional downloads."""
from datetime import timedelta
import gzip
from io import BytesIO
import math
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from scipy.io import netcdf_file

SOURCE = "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/hfmetar/netCDF/"
# NOAA MADIS surface QC results: master, validity, and comparison checks.
QC_MASTER = 1
QC_VALIDITY = 2
QC_WIND_COMPARISONS = 16 | 32 | 64  # temporal, statistical spatial, spatial
WIND_LIMITS = {"windDir": 360, "windSpeed": 200 * (1852 / 3600)}
_files = {}


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


def parse_file(payload, stations, now, *, high_frequency_only=False, allow_advisory_wind=False):
    with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
        content = stream.read(30_000_001)
    if len(content) > 30_000_000:
        raise ValueError("MADIS expanded file exceeds expected size")
    rows = []
    with netcdf_file(BytesIO(content), mmap=False) as dataset:
        variables = dataset.variables
        required = {"stationId", "observationTime", "temperature", "dewpoint", "windDir", "windSpeed"}
        if high_frequency_only:
            required.add("stationType")
        if not required <= variables.keys():
            raise ValueError("MADIS file missing required variables")
        expected_units = {"temperature": b"kelvin", "dewpoint": b"kelvin", "windDir": b"degree", "windSpeed": b"meter/sec"}
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
            scoped_wind = allow_advisory_wind and name in WIND_LIMITS
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
        for index, identifier in enumerate(variables["stationId"][:]):
            station = identifier.tobytes().decode("ascii").strip("\x00 ")
            if stations is not None and station not in stations:
                continue
            if high_frequency_only and variables["stationType"][index].tobytes().strip(b"\x00 ") != b"HF-METAR":
                continue
            lat = float(variables["latitude"][index]) if "latitude" in variables else None
            lon = float(variables["longitude"][index]) if "longitude" in variables else None
            if stations is None and (lat is None or lon is None or not 40 <= lat <= 50 or not -100 <= lon <= -85):
                continue
            stamp = float(variables["observationTime"][index])
            if not math.isfinite(stamp) or not now.timestamp()-3600 <= stamp <= now.timestamp():
                continue
            temperature, dewpoint = measurement("temperature", index), measurement("dewpoint", index)
            speed, direction = measurement("windSpeed", index), measurement("windDir", index)
            # MADIS stores temperatures in Kelvin. Decode to Celsius first;
            # Fahrenheit is never an input. Do not round the station average.
            layers = []
            cloud_status = variables.get("skyCovLayerBaseStatus")
            sky = variables.get("skyCvr")
            bases = variables.get("skyCovLayerBase")
            if bases is not None and getattr(bases, "units", None) != b"meter":
                raise ValueError("Unexpected MADIS cloud height units")
            if sky is not None and bases is not None and (cloud_status is None or int(cloud_status[index]) in (0, 16)):
                for cover_array, base_value in zip(sky[index], bases[index]):
                    cover = cover_array.tobytes().decode("ascii").strip("\x00 ")
                    if cover not in ("CLR", "SKC", "FEW", "SCT", "BKN", "OVC", "VV"):
                        continue
                    base = float(base_value)
                    height = round(base / 0.3048) if math.isfinite(base) and 0 <= base <= 18288 else None
                    if cover in ("CLR", "SKC"):
                        height = None
                    layers.append({"cover": cover, "baseFtAGL": height,
                                   "heightType": "verticalVisibility" if cover == "VV" else "cloudBase"})
            layers.sort(key=lambda layer: (layer["baseFtAGL"] is None, layer["baseFtAGL"] or 0))
            rows.append({"icaoId": station, "obsTime": stamp, "metarType": "HFMETAR",
                "name": variables["stationName"][index].tobytes().decode("ascii", errors="replace").strip("\x00 ") if "stationName" in variables else station,
                "temp": temperature - 273.15 if temperature is not None else None,
                "dewp": dewpoint - 273.15 if dewpoint is not None else None,
                "wspd": speed / (1852 / 3600) if speed is not None else None,
                "wdir": direction, "lat": lat, "lon": lon, "layers": layers,
                "cloudReportAvailable": bool(layers), "source": "NOAA MADIS ASOS"})
    return rows


def get_reports(stations, now, download=None):
    download = download or fetch_file
    hour = now.replace(minute=0, second=0, microsecond=0)
    rows, errors = [], []
    # The previous file supplies reports while a new UTC-hour file is filling.
    hours = [hour, hour-timedelta(hours=1)] if now.minute < 20 else [hour]
    for target in hours:
        try:
            rows.extend(parse_file(download(file_url(target)), stations, now))
        except (HTTPError, TimeoutError, OSError, ValueError) as error:
            errors.append(error)
    if not rows and errors:
        raise errors[0]
    return rows

