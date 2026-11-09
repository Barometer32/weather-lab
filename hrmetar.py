"""Prepared latest-observation map for Minnesota's MADIS HFMETAR stations."""
from datetime import datetime, timezone
import math

KEY = "live/hrmetar-mn-v1.json"
WINDOW_SECONDS = 30 * 60


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")


def eligible(stamp, now):
    return isinstance(stamp, (int, float)) and math.isfinite(stamp) and now - WINDOW_SECONDS <= stamp <= now


def present(snapshot, now):
    stamp = now.timestamp()
    return {"stations": [row for row in snapshot.get("stations", []) if eligible(row["observedEpoch"], stamp)],
            "checkedAt": snapshot["checkedAt"], "serverTime": iso(stamp),
            "source": "NOAA MADIS · Minnesota five-minute ASOS",
            "windowMinutes": 30, "stale": stamp - snapshot["checkedEpoch"] > 8 * 60}


def prepare(store, now, payloads):
    from madis_observations import parse_file
    from mn_asos_audit import STATIONS

    stamp = now.timestamp()
    previous = store.read_json(KEY) or {}
    latest = {r["station"]: r for r in previous.get("stations", []) if eligible(r["observedEpoch"], stamp)}
    successful_files = 0
    errors = []
    for payload in payloads:
        try:
            rows = parse_file(payload, STATIONS - {"KCFE"}, now)
        except (ValueError, OSError, KeyError) as error:
            errors.append(str(error)[:160])
            continue
        successful_files += 1
        for row in rows:
            t = row["obsTime"]
            if row["metarType"] != "HFMETAR" or not eligible(t, stamp):
                continue
            station, lat, lon = row["icaoId"], row["lat"], row["lon"]
            if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (lat, lon)):
                continue
            if not 43 <= lat <= 50 or not -98 <= lon <= -89:
                continue
            old = latest.get(station)
            if old and old["observedEpoch"] > t:
                continue
            speed = row["wspd"]
            direction = row["wdir"]
            temp, dew = row["temp"], row["dewp"]
            def fahrenheit(c):
                return round(c * 1.8 + 32, 1) if c is not None and -90 <= c <= 65 else None
            latest[station] = {
                "station": station, "name": row["name"], "lat": lat, "lon": lon,
                "time": iso(t), "observedEpoch": t,
                "tempF": fahrenheit(temp), "dewpointF": fahrenheit(dew),
                "wind": {"speedMph": round(speed * 1.150779, 1) if speed is not None and 0 <= speed <= 250 else None,
                         "direction": direction if direction is not None and 0 <= direction <= 360 else None},
                "layers": row["layers"],
            }
    if not successful_files:
        raise ValueError("No readable MADIS reports for the HRMETAR map: " + "; ".join(errors))
    snapshot = {"checkedAt": iso(stamp), "checkedEpoch": stamp,
                "stations": [latest[k] for k in sorted(latest)]}
    store.write_json(KEY, snapshot)
    return len(latest)
