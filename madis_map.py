"""Separate public non-airport MADIS hourly plots; revisit late reports every 15 min."""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.error import HTTPError


SOURCE = "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/mesonet/netCDF/"
KEY = "live/madis-map.json"
VERSION = "public-madis-map-v1"
POLICY = "public-mesonet-no-airports-nws-v1"
UTC = timezone.utc


def stamp(text):
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("A station observation requires a timezone")
    return value.astimezone(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def allowed(row, airports=()):
    identifier = row.get("station", "")
    if not identifier or identifier in airports or re.fullmatch(r"[KC][A-Z0-9]{3}", identifier):
        return False
    labels = " ".join(str(row.get(k) or "") for k in ("name", "provider", "network", "reportType"))
    # Ownership is not a universal MADIS field. Filter explicit network/site
    # identifiers rather than treating all NOAA-distributed data as NWS-owned.
    return not re.search(r"\b(?:ASOS|AWOS|METAR|HFMETAR|NWS\w*|WFO|NATIONAL WEATHER SERVICE|WEATHER FORECAST OFFICE)\b", labels, re.I)


def latest(rows, start, end, airports=()):
    chosen = {}
    for row in rows:
        if not allowed(row, airports):
            continue
        try:
            observed = stamp(row["time"])
        except (KeyError, ValueError, TypeError):
            continue
        if not start <= observed < end:
            continue
        old = chosen.get(row["station"])
        if old is None or observed >= stamp(old["time"]):
            chosen[row["station"]] = row
    # Select the latest record before checking usability: never substitute an
    # older value when a newer record is explicitly rejected by NOAA QC.
    return sorted((row for row in chosen.values() if row.get("tempF") is not None
                   or row.get("dewpointF") is not None or (row.get("wind") or {}).get("speedMph") is not None or row.get("layers")),
                  key=lambda r: r["station"])


def snapshot(frames, now, airports=(), checked_at=None, errors=()):
    target = now.replace(minute=0, second=0, microsecond=0)
    by_hour = {frame["hour"]: frame for frame in frames}
    history = []
    for offset in reversed(range(12)):
        end = target-timedelta(hours=offset)
        rows = by_hour.get(iso(end), {}).get("stations", [])
        history.append({"hour": iso(end), "stations": latest(rows, end-timedelta(hours=1), end, airports)})
    return {"version": VERSION, "stationPolicy": POLICY, "history": history,
            "checkedAt": checked_at or iso(now), "source": "NOAA MADIS public Integrated Mesonet",
            "sourceUrl": SOURCE, "errors": list(errors), "checkMinutes": [0, 15, 30, 45],
            "frameIntervalMinutes": 60}


def collect(store, now, hours=2, download=None, parse=None):
    import regional_madis
    previous = store.read_json(KEY) or {}
    if previous.get("version") != VERSION:
        previous = {}
    airports = {row["station"] for frame in (store.read_json("live/metar-clouds.json") or {}).get("history", [])
                for row in frame.get("stations", [])}
    frames = {frame["hour"]: frame for frame in previous.get("history", [])}
    metadata = dict(previous.get("files", {}))
    download, parse = download or regional_madis.fetch, parse or regional_madis.parse_file
    target = now.replace(minute=0, second=0, microsecond=0)
    errors, successful = [], 0
    for offset in range(1, min(12, hours)+1):
        start = target-timedelta(hours=offset)
        name = start.strftime("%Y%m%d_%H00.gz")
        label = iso(start+timedelta(hours=1))
        try:
            payload, info = download(SOURCE+name, metadata.get(name))
            if payload is not None:
                rows = parse(payload, now, window_start=start, window_end=start+timedelta(hours=1),
                             include_invalid=True, excluded_stations=())
                frames[label] = {"hour": label, "stations": latest(rows, start, start+timedelta(hours=1), airports)}
                metadata[name] = info
            elif label not in frames:
                raise ValueError("Unchanged source file has no saved frame")
            successful += 1
            # Durable checkpoints make the initial twelve-file import resumable.
            data = snapshot(list(frames.values()), now, airports, errors=errors)
            data["files"] = metadata
            if any(f["stations"] for f in data["history"]):
                store.write_json(KEY, data)
        except (HTTPError, TimeoutError, OSError, ValueError) as error:
            errors.append({"file": name, "error": str(error)[:180]})
    if not successful:
        raise ValueError("MADIS collection unavailable; the previous map was retained")
    data = snapshot(list(frames.values()), now, airports, errors=errors)
    valid = {(target-timedelta(hours=i)).strftime("%Y%m%d_%H00.gz") for i in range(1, 13)}
    data["files"] = {name: value for name, value in metadata.items() if name in valid}
    if not any(frame["stations"] for frame in data["history"]) and not previous:
        raise ValueError("No usable public non-airport mesonet reports returned")
    store.write_json(KEY, data)
    return {"hours": sum(bool(frame["stations"]) for frame in data["history"]),
            "latestStations": len(data["history"][-1]["stations"]), "errors": errors}


def present(saved, now):
    data = snapshot(saved.get("history", []), now, checked_at=saved.get("checkedAt"), errors=saved.get("errors", []))
    checked = saved.get("checkedAt")
    data["stale"] = not checked or now-stamp(checked) > timedelta(minutes=35)
    data["serverTime"] = iso(now)
    # Public payload contains only plot/popup fields, not file validators or
    # repeated derived QC/cloud summaries for every hour.
    keep = ("station", "name", "lat", "lon", "time", "tempF", "dewpointF", "wind", "layers", "network", "provider", "source")
    for frame in data["history"]:
        frame["stations"] = [{k: row[k] for k in keep if k in row} for row in frame["stations"]]
    return data


if __name__ == "__main__":
    from realtime import get_store
    store = get_store()
    if store is None:
        raise SystemExit("WEATHER_DATA_BUCKET is required")
    print("Importing twelve hourly public mesonet frames (no airport/NWS plots).", flush=True)
    print(json.dumps(collect(store, datetime.now(UTC), hours=12)), flush=True)
