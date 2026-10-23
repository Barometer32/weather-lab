"""Public MADIS surface mesonet observations for the existing regional map.

Keep source timestamps and field QC, choose the latest observation per station
in each completed hour, and revisit files to pick up delayed delivery.
No MADIS request is made by a page view or by the three-airport Current view.
"""
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import math
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from scipy.io import netcdf_file

SOURCE = "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/mesonet/netCDF/"
KEY = "live/madis-stations.json"
UTC = timezone.utc


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def fetch(url, previous=None):
    headers = {"User-Agent": "J-Weather (https://github.com/Barometer32/weather-lab)"}
    previous = previous or {}
    if previous.get("etag"):
        headers["If-None-Match"] = previous["etag"]
    elif previous.get("lastModified"):
        headers["If-Modified-Since"] = previous["lastModified"]
    try:
        with urlopen(Request(url, headers=headers), timeout=60) as response:
            payload = response.read(64_000_001)
            if len(payload) > 64_000_000:
                raise ValueError("MADIS compressed mesonet file exceeds expected size")
            return payload, {"etag": response.headers.get("ETag"),
                             "lastModified": response.headers.get("Last-Modified")}
    except HTTPError as error:
        if error.code == 304 and previous:
            return None, previous
        raise


def parse_dataset(dataset, now, *, window_start=None, window_end=None, bounds=None, include_invalid=False):
    """Return local usable measurements without copying the national arrays."""
    v = dataset.variables
    required = {"stationId", "observationTime", "latitude", "longitude"}
    if not required <= v.keys():
        raise ValueError("MADIS mesonet file lacks station metadata")
    expected = {"temperature": b"kelvin", "dewpoint": b"kelvin", "relHumidity": b"percent",
                "windSpeed": b"meter/sec", "windDir": b"degree"}
    for key, unit in expected.items():
        if key in v and getattr(v[key], "units", None) != unit:
            raise ValueError("Unexpected MADIS units for " + key)
    if "skyCovLayerBase" in v and getattr(v["skyCovLayerBase"], "units", None) != b"meter":
        raise ValueError("Unexpected MADIS cloud height units")

    def text(name, index):
        return v[name][index].tobytes().decode("ascii", errors="replace").strip("\x00 ") if name in v else ""

    def number(name, index, low, high, qc=True):
        if name not in v:
            return None
        field = v[name]
        value = float(field[index])
        if (not math.isfinite(value) or not low <= value <= high
                or value in (getattr(field, "_FillValue", None), getattr(field, "missing_value", None))):
            return None
        if qc:
            for suffix in ("QCR", "ICR"):
                check = v.get(name + suffix)
                if check is not None and int(check[index]) != 0:
                    return None
            if text(name + "DD", index) in ("Q", "B", "X"):
                return None
        return value

    lat, lon, stamp = v["latitude"][:], v["longitude"][:], v["observationTime"][:]
    target = now.replace(minute=0, second=0, microsecond=0)
    south, west, north, east = bounds or (40, -100, 50, -85)
    start = window_start.timestamp() if window_start else target.timestamp()-13*3600
    end = window_end.timestamp() if window_end else target.timestamp()
    indices = np.flatnonzero((lat >= south) & (lat <= north) & (lon >= west) & (lon <= east)
                             & (stamp >= start) & (stamp < end))
    rows = []
    for i in indices:
        station = text("stationId", i)
        if not station or station in ("KCFE", "KFCE", "KSGS", "KDEH"):
            continue
        observed = datetime.fromtimestamp(float(stamp[i]), UTC)
        # Public1 is the access boundary. Also reject explicit all-data
        # restrictions if a file happens to carry them; missing flags are common.
        restriction = number("restrictedDataLevel", i, 0, 6, qc=False)
        if restriction is not None and restriction >= 2:
            continue
        temp = number("temperature", i, 183.15, 333.15)
        dew = number("dewpoint", i, 173.15, 333.15)
        speed = number("windSpeed", i, 0, 103)
        direction = number("windDir", i, 0, 360)
        if temp is not None and dew is not None and dew > temp + 2:
            dew = None
        layers = []
        if "skyCvr" in v and "skyCovLayerBase" in v:
            for cover, base in zip(v["skyCvr"][i], v["skyCovLayerBase"][i]):
                code = cover.tobytes().decode("ascii", errors="replace").strip("\x00 ")
                if code not in ("CLR", "SKC", "FEW", "SCT", "BKN", "OVC", "VV"):
                    continue
                height = float(base)
                height = round(height/0.3048) if math.isfinite(height) and 0 <= height <= 18288 else None
                if code in ("CLR", "SKC"):
                    height = None
                layers.append({"cover": code, "baseFtAGL": height,
                               "heightType": "verticalVisibility" if code == "VV" else "cloudBase"})
        if all(value is None for value in (temp, dew, speed)) and not layers and not include_invalid:
            continue
        from cloud_conditions import summarize
        provider, name = text("dataProvider", i), text("stationName", i)
        network = ("Hennepin West" if "HENNEPIN" in name else
                   "MnDOT" if "MNDOT" in name or provider == "MNDOT" else
                   "CWOP" if provider == "APRSWXNET" else provider or "MADIS")
        rows.append({"station": station, "name": name, "lat": float(lat[i]), "lon": float(lon[i]),
                     "time": iso(observed), "source": "NOAA MADIS", "network": network,
                     "provider": provider, "reportType": "MESONET",
                     "tempF": round((temp-273.15)*1.8+32, 1) if temp is not None else None,
                     "dewpointF": round((dew-273.15)*1.8+32, 1) if dew is not None else None,
                     "wind": {"speedMph": round(speed*2.2369362921, 1) if speed is not None else None,
                              "direction": direction if speed is not None else None},
                     "layers": layers, **summarize({"layers": layers})})
    return rows


def parse_file(payload, now, **selection):
    # National files expand to hundreds of MB. Stream to disk and memory-map
    # only the fields needed for local stations, rather than loading all data.
    with tempfile.TemporaryDirectory(prefix="j-weather-madis-") as work:
        path = work + "/mesonet.nc"
        with gzip.GzipFile(fileobj=BytesIO(payload)) as source, open(path, "wb") as output:
            total = 0
            while chunk := source.read(1024*1024):
                total += len(chunk)
                if total > 800_000_000:
                    raise ValueError("MADIS expanded mesonet file exceeds expected size")
                output.write(chunk)
        dataset = netcdf_file(path, mmap=True)
        try:
            return parse_dataset(dataset, now, **selection)
        except Exception as error:
            # An exception traceback would retain mapped variables while the
            # file closes. Drop that frame before releasing the memory map.
            raise error.with_traceback(None)
        finally:
            dataset.close()


def snapshot(rows, now, checked_at=None):
    target = now.replace(minute=0, second=0, microsecond=0)
    chosen = {}
    for row in rows:
        observed = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if not target-timedelta(hours=12) <= observed < target:
            continue
        hour = observed.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        rank = -observed.timestamp()
        key = (iso(hour), row["station"])
        if key not in chosen or rank <= chosen[key][0]:
            chosen[key] = (rank, row)
    history = []
    for offset in reversed(range(12)):
        hour = iso(target-timedelta(hours=offset))
        stations = sorted((value[1] for (label, _), value in chosen.items() if label == hour), key=lambda row: row["station"])
        history.append({"hour": hour, "stations": stations})
    return {"version": "public-madis-mesonet-v1", "history": history,
            "checkedAt": checked_at or iso(now), "source": "NOAA MADIS public Integrated Mesonet",
            "sourceUrl": SOURCE}


def collect(store, now, hours=2, download=fetch):
    previous = store.read_json(KEY) or {}
    retained = [row for frame in previous.get("history", []) for row in frame.get("stations", [])]
    metadata = dict(previous.get("files", {}))
    results, errors, successful = [], [], 0
    target = now.replace(minute=0, second=0, microsecond=0)
    for offset in range(1, hours+1):
        name = (target-timedelta(hours=offset)).strftime("%Y%m%d_%H00.gz")
        try:
            payload, info = download(SOURCE+name, metadata.get(name))
            if payload is not None:
                parsed = parse_file(payload, now)
                seen = {(row["station"], row["time"]): row for row in retained}
                # A reissued file can revise QC. Replace its prior rows, so a
                # newly rejected reading cannot survive from an older download.
                retained = [row for row in retained if datetime.fromisoformat(row["time"].replace("Z", "+00:00")).strftime("%Y%m%d_%H00.gz") != name]
                for row in parsed:
                    old = seen.get((row["station"], row["time"]), {})
                    results.append({**row, "fetchedAt": iso(now),
                                    "firstSeenAt": old.get("firstSeenAt", iso(now)),
                                    "initialBackfill": old.get("initialBackfill", hours > 2)})
                metadata[name] = info
            successful += 1
        except (HTTPError, TimeoutError, OSError, ValueError) as error:
            errors.append({"file": name, "error": str(error)[:200]})
    if not successful:
        raise ValueError("MADIS collection failed; previous observations retained: " + str(errors))
    data = snapshot(retained+results, now)
    valid_files = {(target-timedelta(hours=i)).strftime("%Y%m%d_%H00.gz") for i in range(1, 14)}
    data.update(files={name: info for name, info in metadata.items() if name in valid_files}, errors=errors)
    if not any(frame["stations"] for frame in data["history"]):
        raise ValueError("MADIS returned no usable regional observations; previous data retained")
    store.write_json(KEY, data)
    return data


def merge(airports, madis, now):
    """Combine prepared hourly frames; official METAR wins duplicate IDs."""
    madis = madis or {}
    regional = snapshot([row for frame in madis.get("history", []) for row in frame.get("stations", [])], now)
    by_hour = {frame["hour"]: frame["stations"] for frame in regional["history"]}
    frames = []
    for frame in airports["history"]:
        rows = {row["station"]: {**row, "network": "Airport METAR", "source": "NOAA Aviation Weather Center"}
                for row in frame["stations"]}
        airport_count = len(rows)
        for row in by_hour.get(frame["hour"], []):
            rows.setdefault(row["station"], row)
        frames.append({**frame, "stations": sorted(rows.values(), key=lambda row: row["station"]),
                       "airportCount": airport_count, "madisCount": len(rows)-airport_count,
                       "hennepinCount": sum(row.get("network") == "Hennepin West" for row in rows.values())})
    checked = madis.get("checkedAt")
    delayed = not checked or (now-datetime.fromisoformat(checked.replace("Z", "+00:00"))).total_seconds() > 900
    return {**airports, "history": frames, "stations": frames[-1]["stations"],
            "madis": {"checkedAt": checked, "delayed": delayed, "errors": madis.get("errors", []),
                      "available": bool(checked), "sourceUrl": SOURCE}}


def main():
    from realtime import get_store
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET must be set")
    print("Importing twelve hours of public MADIS mesonet observations.", flush=True)
    data = collect(store, datetime.now(UTC), hours=12)
    for frame in data["history"]:
        print(frame["hour"], len(frame["stations"]), "MADIS stations", flush=True)


if __name__ == "__main__":
    main()
