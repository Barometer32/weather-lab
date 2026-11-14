"""Background-only, public MN/WI observations. No location or paid credentials.

Poll original public sources, preserve observation times, and publish a compact
regional inventory. The browser selects local stations; device coordinates never
need to reach this service. This is not a validated meteorological analysis.
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
from urllib.error import HTTPError

import regional_madis
from observation_stations import inside_ring

VERSION = "public-mn-wi-conditions-v1"
KEY = "live/public-conditions.json"
WISCONET = "https://api.wisconet.wisc.edu/api/v1/"
BOUNDS = (40.4, -97.3, 49.5, -86.2)
UTC = timezone.utc


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def valid(value, low, high):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


@lru_cache(maxsize=1)
def boundaries():
    return json.loads((Path(__file__).parent / "static/mn-wi-states.geojson").read_text())["features"]


def state_at(lat, lon):
    if not valid(lat, BOUNDS[0], BOUNDS[2]) or not valid(lon, BOUNDS[1], BOUNDS[3]):
        return None
    for feature in boundaries():
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        if any(inside_ring(lon, lat, polygon[0]) and not any(inside_ring(lon, lat, ring) for ring in polygon[1:]) for polygon in polygons):
            return {"27": "MN", "55": "WI"}[feature["properties"]["STATE"]]
    return None


def normalize(row, now):
    state = state_at(row.get("lat"), row.get("lon"))
    if not state or not row.get("station"):
        return None
    try:
        stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        age = (now-stamp).total_seconds()
    except (ValueError, TypeError, KeyError):
        return None
    if not 0 <= age <= 86400:
        return None
    row = dict(row, state=state)
    row["tempF"] = row.get("tempF") if valid(row.get("tempF"), -130, 140) else None
    dew = row.get("dewpointF")
    row["dewpointF"] = dew if valid(dew, -148, 140) and (row["tempF"] is None or dew <= row["tempF"]+1) else None
    wind = row.get("wind") or {}
    speed = wind.get("speedMph")
    row["wind"] = {"speedMph": speed if valid(speed, 0, 200) else None,
                   "direction": wind.get("direction") if valid(wind.get("direction"), 0, 360) else None}
    # Do not infer quality from a station's temperature or its name alone.
    known = {"Hennepin West", "MnDOT", "ASOS/AWOS", "Wisconet", "Road weather", "RAWS"}
    row["kind"] = row.get("kind", "community" if row.get("network") == "CWOP" else "reference" if row.get("network") in known else "other")
    allowed = ("station", "name", "lat", "lon", "state", "time", "source", "network", "kind", "tempF", "dewpointF", "wind", "aliases")
    return {key: row[key] for key in allowed if key in row}


def latest(rows, now):
    selected = {}
    for original in rows:
        row = normalize(original, now)
        if row is None:
            continue
        # Keep the fastest delivery of each timestamp, never count duplicate feeds.
        key = row["station"]
        old = selected.get(key)
        if old is None or row["time"] >= old["time"]:
            selected[key] = row
    # Wisconet supplies its MADIS identifier. Merge these exact aliases first.
    aliases = {alias: row["station"] for row in selected.values() for alias in row.get("aliases", [])}
    for alias, canonical in aliases.items():
        if alias == canonical or alias not in selected:
            continue
        other = selected.pop(alias)
        if other["time"] > selected[canonical]["time"]:
            selected[canonical] = dict(other, station=canonical, aliases=[alias], network="Wisconet", kind="reference")
    return sorted(selected.values(), key=lambda row: row["station"])


def wisconet_rows(stations, summaries, now):
    if not isinstance(stations, list) or not isinstance(summaries, list):
        raise ValueError("Invalid Wisconet inventory")
    meta = {row["station_id"]: row for row in stations if isinstance(row, dict) and row.get("station_id")}
    fields = {"5min_air_temp_f_avg": "tempF", "5min_dew_point_f_avg": "dewpointF",
              "5min_wind_speed_mph_avg": "speedMph", "5min_wind_dir_deg_avg": "direction"}
    rows = {}
    for station in summaries:
        for entry in station.get("current", []):
            name, identifier, stamp = entry.get("standard_name"), entry.get("station_id"), entry.get("collection_time")
            if name not in fields or identifier not in meta or not valid(stamp, 0, now.timestamp()):
                continue
            key = identifier, stamp
            if key not in rows:
                site = meta[identifier]
                rows[key] = {"station": "WISC:"+identifier, "aliases": [site["madis_id"]] if site.get("madis_id") else [],
                             "name": site.get("station_name", identifier), "lat": site.get("latitude"), "lon": site.get("longitude"),
                             "time": iso(datetime.fromtimestamp(stamp, UTC)), "source": "Wisconet direct API",
                             "network": "Wisconet", "kind": "reference", "wind": {}}
            target = rows[key]["wind"] if fields[name] in ("speedMph", "direction") else rows[key]
            target[fields[name]] = entry.get("value")
    return [row for row in rows.values() if row.get("tempF") is not None]


def awc_rows(payload, now):
    from app import metar_precision
    from metar_clouds import parse_reports
    result = []
    for raw in parse_reports(payload, now, hours=2):
        row = metar_precision(raw)
        result.append({"station": row["station"], "name": row["station"], "lat": row["lat"], "lon": row["lon"], "time": row["time"],
                       "tempF": row["temp"]*1.8+32 if row.get("temp") is not None else None,
                       "dewpointF": row["dewp"]*1.8+32 if row.get("dewp") is not None else None,
                       "wind": {"speedMph": row["wspd"]*1.150779 if row.get("wspd") is not None else None,
                                "direction": row.get("wdir")}, "kind": "reference", "network": "ASOS/AWOS",
                       "source": "NOAA Aviation Weather Center"})
    return result


def collect(store, now, download=None):
    """Bounded sequential national downloads avoid concurrent expanded netCDFs."""
    download = download or regional_madis.fetch
    previous = store.read_json(KEY) or {}
    if previous.get("version") != VERSION:
        previous = {}
    files, sources, errors = {}, {}, []
    rows = list(previous.get("stations", []))
    hour = now.replace(minute=0, second=0, microsecond=0)
    feeds = {"mesonet": regional_madis.SOURCE,
             "rapid-asos": "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/hfmetar/netCDF/",
             "rwis": "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/rwis/netCDF/"}
    for feed, base in feeds.items():
        feed_rows, ok = [], False
        for offset in (0, 1):
            filename = (hour-timedelta(hours=offset)).strftime("%Y%m%d_%H00.gz")
            key = feed+"/"+filename
            old = previous.get("files", {}).get(key, {})
            try:
                payload, metadata = download(base+filename, old.get("metadata"))
                if payload is None:
                    fresh = old.get("stations", [])
                else:
                    fresh = regional_madis.parse_file(payload, now, window_start=now-timedelta(hours=2), window_end=now+timedelta(microseconds=1),
                              bounds=BOUNDS, derive_dewpoint=True, sensor_status_checks=True, include_invalid=True, excluded_stations=())
                    if feed == "rapid-asos":
                        # Public access does not imply one-minute entitlement. Keep
                        # only the five-minute subset, even if other stamps appear.
                        fresh = [r for r in fresh if datetime.fromisoformat(r["time"].replace("Z", "+00:00")).minute % 5 == 0]
                        for row in fresh:
                            row.update(network="ASOS/AWOS", source="NOAA MADIS public five-minute ASOS", kind="reference")
                    elif feed == "rwis":
                        for row in fresh:
                            row.update(network="Road weather", kind="reference")
                    fresh = latest(fresh, now)
                files[key] = {"metadata": metadata, "stations": fresh}
                feed_rows.extend(fresh)
                ok = True
            except Exception as error:
                if not (isinstance(error, HTTPError) and error.code == 404 and offset == 0):
                    errors.append({"source": key, "error": str(error)[:150]})
                if old:
                    files[key] = old
                    feed_rows.extend(old.get("stations", []))
        # Refreshed QC can remove a previously usable value. A successful full
        # source scan replaces that feed's old copies, rather than resurrecting it.
        if ok:
            touched = {r["station"] for r in feed_rows}
            rows = [r for r in rows if r["station"] not in touched]
            sources[feed] = {"checkedAt": iso(now), "stationCount": len(latest(feed_rows, now))}
        rows.extend(feed_rows)
    for name in ("awc", "wisconet"):
        try:
            if name == "awc":
                from metar_clouds import SOURCE_URL
                payload, _ = download(SOURCE_URL)
                fresh = awc_rows(payload, now)
            else:
                old_meta = previous.get("wisconetStations", [])
                meta_time = previous.get("wisconetInventoryAt")
                if not old_meta or not meta_time or (now-datetime.fromisoformat(meta_time.replace("Z", "+00:00"))).total_seconds() > 86400:
                    payload, _ = download(WISCONET+"stations/")
                    old_meta, meta_time = json.loads(payload), iso(now)
                payload, _ = download(WISCONET+"stations/current_summaries")
                fresh = wisconet_rows(old_meta, json.loads(payload), now)
                previous.update(wisconetStations=old_meta, wisconetInventoryAt=meta_time)
            fresh = latest(fresh, now)
            if not fresh:
                raise ValueError("Source returned no recent temperatures")
            rows.extend(fresh)
            sources[name] = {"checkedAt": iso(now), "stationCount": len(fresh)}
        except Exception as error:
            errors.append({"source": name, "error": str(error)[:150]})
    if not sources:
        raise ValueError("All public feeds failed; retained prior prepared inventory")
    selected = latest(rows, now)
    if not any(row.get("tempF") is not None for row in selected):
        raise ValueError("No usable public temperature observations")
    sources = {**previous.get("sources", {}), **sources}
    saved = {"version": VERSION, "checkedAt": iso(now), "stations": selected, "files": files,
             "sources": sources, "sourceFailures": errors,
             "wisconetStations": previous.get("wisconetStations", []), "wisconetInventoryAt": previous.get("wisconetInventoryAt")}
    store.write_json(KEY, saved)
    return {"stationCount": len(selected), "sources": sources, "sourceFailures": errors}


def present(saved, now):
    if not saved or saved.get("version") != VERSION:
        raise ValueError("Public conditions are being prepared")
    return {key: value for key, value in saved.items() if key in ("version", "checkedAt", "stations", "sources", "sourceFailures")} | {
        "serverTime": iso(now), "pollSeconds": 120,
        "collectorDelayed": (now-datetime.fromisoformat(saved["checkedAt"].replace("Z", "+00:00"))).total_seconds() > 360}


if __name__ == "__main__":
    from realtime import get_store
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET is required")
    print(json.dumps(collect(store, datetime.now(UTC))))
