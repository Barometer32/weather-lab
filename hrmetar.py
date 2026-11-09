"""Prepared latest-observation map for five-state MADIS HFMETAR stations."""
from datetime import datetime, timezone
import math

from hrmetar_stations import STATION_STATES

KEY = "live/hrmetar-upper-midwest-c-v2.json"
WINDOW_SECONDS = 30 * 60


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")


def eligible(stamp, now):
    return isinstance(stamp, (int, float)) and math.isfinite(stamp) and now - WINDOW_SECONDS <= stamp <= now


def whole_celsius(c):
    # The HF-ASOS fields are native integer Celsius encoded in Kelvin.
    # Allow float conversion noise only; never promote a tenths value.
    if c is not None and -90 <= c <= 65 and abs(c - round(c)) < .001:
        return round(c)
    return None


def present(snapshot, now):
    stamp = now.timestamp()
    return {"stations": [row for row in snapshot.get("stations", []) if eligible(row["observedEpoch"], stamp)],
            "checkedAt": snapshot["checkedAt"], "serverTime": iso(stamp),
            "source": "NOAA MADIS · Upper Midwest five-minute ASOS", "temperatureUnit": "C",
            "windowMinutes": 30, "stale": stamp - snapshot["checkedEpoch"] > 8 * 60}


def prepare(store, now, payloads):
    from madis_observations import parse_file

    stamp = now.timestamp()
    previous = store.read_json(KEY) or {}
    latest = {r["station"]: r for r in previous.get("stations", []) if eligible(r["observedEpoch"], stamp)}
    successful_files = 0
    errors = []
    for payload in payloads:
        try:
            rows = parse_file(payload, STATION_STATES.keys() - {"KCFE"}, now, high_frequency_only=True)
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
            if not 40 <= lat <= 50 or not -105 <= lon <= -86:
                continue
            old = latest.get(station)
            if old and old["observedEpoch"] > t:
                continue
            speed = row["wspd"]
            direction = row["wdir"]
            temp, dew = row["temp"], row["dewp"]
            latest[station] = {
                "station": station, "name": row["name"], "state": STATION_STATES[station], "lat": lat, "lon": lon,
                "time": iso(t), "observedEpoch": t,
                "tempC": whole_celsius(temp), "dewpointC": whole_celsius(dew),
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
