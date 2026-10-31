"""Rolling public non-airport MADIS plots; collect the latest 25 minutes every 15 min."""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.error import HTTPError


SOURCE = "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/mesonet/netCDF/"
KEY = "live/madis-map.json"
VERSION = "public-madis-map-v2"
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
        if not start <= observed <= end:
            continue
        old = chosen.get(row["station"])
        if old is None or observed >= stamp(old["time"]):
            chosen[row["station"]] = row
    # Select the latest record before checking usability: never substitute an
    # older value when a newer record is explicitly rejected by NOAA QC.
    return sorted((row for row in chosen.values() if row.get("tempF") is not None
                   or row.get("dewpointF") is not None or (row.get("wind") or {}).get("speedMph") is not None),
                  key=lambda r: r["station"])


def snapshot(rows, now, airports=(), checked_at=None, errors=()):
    start = now-timedelta(minutes=25)
    return {"version": VERSION, "stationPolicy": POLICY,
            "stations": latest(rows, start, now, airports),
            "checkedAt": checked_at or iso(now), "windowStart": iso(start), "windowEnd": iso(now),
            "source": "NOAA MADIS public Integrated Mesonet", "sourceUrl": SOURCE,
            "errors": list(errors), "checkMinutes": [0, 15, 30, 45], "windowMinutes": 25}


def collect(store, now, download=None, parse=None):
    # Only the source file(s) intersecting the 25-minute observation window.
    # Keep per-file latest rows for HTTP 304 reuse and replace on QC reissues.
    import regional_madis
    previous = store.read_json(KEY) or {}
    if previous.get("version") != VERSION:
        previous = {}
    airports = {row["station"] for frame in (store.read_json("live/metar-clouds.json") or {}).get("history", [])
                for row in frame.get("stations", [])}
    download, parse = download or regional_madis.fetch, parse or regional_madis.parse_file
    first = (now-timedelta(minutes=25)).replace(minute=0, second=0, microsecond=0)
    last = now.replace(minute=0, second=0, microsecond=0)
    files, errors, successful = {}, [], 0
    current = first
    while current <= last:
        name = current.strftime("%Y%m%d_%H00.gz")
        old = previous.get("files", {}).get(name, {})
        try:
            payload, info = download(SOURCE+name, old.get("validators"))
            if payload is not None:
                rows = parse(payload, now, window_start=current,
                             window_end=min(current+timedelta(hours=1), now+timedelta(microseconds=1)),
                             include_invalid=True, excluded_stations=())
                # Preserve rejected newest records here so they suppress older
                # measurements from a different file at an hour boundary.
                by_site = {}
                for row in rows:
                    if not allowed(row, airports):
                        continue
                    observed = stamp(row["time"])
                    if current <= observed < current+timedelta(hours=1) and observed <= now:
                        prior = by_site.get(row["station"])
                        if prior is None or observed >= stamp(prior["time"]):
                            by_site[row["station"]] = row
                files[name] = {"validators": info, "stations": list(by_site.values())}
            elif "stations" in old:
                files[name] = old
            else:
                raise ValueError("Unchanged source file has no saved observations")
            successful += 1
        except (HTTPError, TimeoutError, OSError, ValueError) as error:
            # A new current-hour file often does not exist yet at :00.
            # Absence is expected; other errors remain visible in the API.
            if not isinstance(error, HTTPError) or error.code != 404:
                errors.append({"file": name, "error": str(error)[:180]})
            if old:
                files[name] = old
        current += timedelta(hours=1)
    if not successful:
        raise ValueError("MADIS collection unavailable; the previous snapshot was retained")
    data = snapshot([row for file in files.values() for row in file.get("stations", [])], now, airports, errors=errors)
    data["files"] = files
    store.write_json(KEY, data)
    return {"latestStations": len(data["stations"]), "windowStart": data["windowStart"],
            "windowEnd": data["windowEnd"], "errors": errors}


def present(saved, now):
    # This is a snapshot as of the last collection, not a moving browser-time
    # cutoff. Its timestamp stays explicit until the next quarterly-hour run.
    checked = saved["checkedAt"]
    data = snapshot(saved.get("stations", []), stamp(checked), checked_at=checked, errors=saved.get("errors", []))
    data["stale"] = now-stamp(checked) > timedelta(minutes=35)
    data["serverTime"] = iso(now)
    keep = ("station", "name", "lat", "lon", "time", "tempF", "dewpointF", "wind", "network", "provider", "source")
    data["stations"] = [{k: row[k] for k in keep if k in row} for row in data["stations"]]
    return data


if __name__ == "__main__":
    from realtime import get_store
    store = get_store()
    if store is None:
        raise SystemExit("WEATHER_DATA_BUCKET is required")
    print("Preparing the latest 25-minute public mesonet snapshot (no airport/NWS plots).", flush=True)
    print(json.dumps(collect(store, datetime.now(UTC))), flush=True)
