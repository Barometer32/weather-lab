"""Authenticated direct Hennepin West API; no browser/demo credentials.

Use a small time series so each plotted row contains measurements from one
actual report, rather than silently mixing Latest's per-variable timestamps.
"""
from datetime import datetime, timedelta, timezone
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen

STATIONS = ("HPN02", "HPN03", "HPN05", "HPN07", "HPN08", "HPN09", "HPN20",
            "HPN21", "HPN24", "HPN25", "HPN26", "HPN28", "HPN30", "HPN31",
            "HPN37", "HPN38", "HPN39", "HPN45", "HPN47")
ENDPOINT = "https://api.synopticdata.com/v2/stations/timeseries"


def fresh_complete(row, now):
    wind = row.get("wind") or {}
    return (row.get("tempF") is not None and row.get("dewpointF") is not None
            and wind.get("speedMph") is not None
            and (wind["speedMph"] < .5 or wind.get("direction") is not None)
            and 0 <= (now-datetime.fromisoformat(row["time"].replace("Z", "+00:00"))).total_seconds() <= 900)


def parse(data, now):
    from observation_stations import included_site, included_on_map, latest, iso
    if data.get("SUMMARY", {}).get("RESPONSE_CODE") != 1:
        # API error messages can echo a URL/token. Never persist or log them.
        raise ValueError("Synoptic request was not accepted; check API access and Hennepin coverage")
    units = data.get("UNITS", {})
    required = {"air_temp": "Fahrenheit", "dew_point_temperature": "Fahrenheit",
                "wind_speed": "Miles/hour", "wind_direction": "Degrees"}
    for key, expected in required.items():
        if key in units and units[key] != expected:
            raise ValueError("Unexpected Synoptic measurement units")
    rows = []
    for station in data.get("STATION", []):
        if station.get("STID") not in STATIONS or str(station.get("MNET_ID")) != "257":
            continue
        try:
            base = {"station": station["STID"], "name": station["NAME"], "network": "Hennepin West",
                    "lat": float(station["LATITUDE"]), "lon": float(station["LONGITUDE"])}
        except (KeyError, TypeError, ValueError):
            continue
        if not included_site(base) or not included_on_map(base):
            continue
        obs = station.get("OBSERVATIONS", {})
        def value(variable, index, low, high):
            # Prefer the primary measured sensor, then the primary derived one.
            for suffix in ("_set_1", "_set_1d"):
                values = obs.get(variable + suffix, [])
                v = values[index] if index < len(values) else None
                if (variable in units and isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) and low <= v <= high):
                    return v
            return None
        for i, text in enumerate(obs.get("date_time", [])):
            try:
                stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if stamp.tzinfo is None or not now-timedelta(hours=2) <= stamp <= now:
                    continue
            except (TypeError, ValueError):
                continue
            row = dict(base, time=iso(stamp), tempF=value("air_temp", i, -150, 160),
                       dewpointF=value("dew_point_temperature", i, -150, 120),
                       wind={"speedMph": value("wind_speed", i, 0, 250),
                             "direction": value("wind_direction", i, 0, 360)},
                       source="Synoptic direct")
            if any(row[k] is not None for k in ("tempF", "dewpointF")):
                rows.append(row)
    return latest(rows, now)


def fetch(token, now):
    query = urlencode({"token": token, "stid": ",".join(STATIONS), "network": "257", "recent": "120",
                       "vars": "air_temp,dew_point_temperature,wind_speed,wind_direction",
                       "units": "english,speed|mph", "obtimezone": "utc", "qc": "on",
                       "qc_remove_data": "on", "qc_flags": "off"})
    try:
        with urlopen(Request(ENDPOINT + "?" + query, headers={"User-Agent": "Weather Lab Hennepin map"}), timeout=25) as response:
            payload = response.read(4_000_001)
        if len(payload) > 4_000_000:
            raise ValueError("Response too large")
        return parse(json.loads(payload), now)
    except Exception:
        raise RuntimeError("Synoptic direct feed unavailable; check token, station access and service status") from None


if __name__ == "__main__":
    import os
    now = datetime.now(timezone.utc)
    rows = fetch(os.environ["WEATHER_SYNOPTIC_TOKEN"], now)
    fresh = [r for r in rows if fresh_complete(r, now)]
    print(f"Synoptic returned {len(rows)}/{len(STATIONS)} approved stations; {len(fresh)} reported within 15 minutes.")
    print("Newest actual report:", max((r["time"] for r in rows), default="none"))
    if len(fresh) != len(STATIONS):
        raise SystemExit("Direct access has not verified fresh coverage for all 19 approved stations. No Cloud configuration changed.")
