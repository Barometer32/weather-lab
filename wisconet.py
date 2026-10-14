"""UW–Madison Wisconet hourly samples from its public CC BY 4.0 API."""
import json
from datetime import timedelta
from urllib.parse import urlencode

SOURCE = "https://api.wisconet.wisc.edu/api/v2/stations/map"
FIELDS = {
    "5min_air_temp_f_avg": ("tempF", "ud:degF", -130, 140),
    "5min_dew_point_f_avg": ("dewpointF", "ud:degF", -148, 140),
    "5min_wind_speed_mph_avg": ("speedMph", "wn:mph", 0, 230),
    "5min_wind_dir_deg_avg": ("direction", "ud:degree", 0, 360),
}
EXCLUDED = {"WNTEST1", "MITEST1"}


def url(hour):
    from station_plots import iso
    return SOURCE + "?" + urlencode({"fieldlist": ",".join(FIELDS), "date": iso(hour-timedelta(seconds=1))})


def parse(payload, hour):
    from station_plots import iso, timestamp, number, in_hour_window
    document = json.loads(payload)
    if not isinstance(document, dict) or not isinstance(document.get("features"), list):
        raise ValueError("Invalid Wisconet station response")
    rows = []
    for feature in document["features"]:
        if not isinstance(feature, dict):
            continue
        properties, geometry = feature.get("properties", {}), feature.get("geometry", {})
        if not isinstance(properties, dict) or not isinstance(geometry, dict) or geometry.get("type") != "Point":
            continue
        station = properties.get("station_id")
        if not isinstance(station, str) or not station.isalnum() or station in EXCLUDED:
            continue
        coords = geometry.get("coordinates", [])
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        lat, lon = number(coords[1], 40, 50), number(coords[0], -100, -85)
        if lat is None or lon is None:
            continue
        samples = {}
        for field, (name, unit, low, high) in FIELDS.items():
            measure = properties.get(field)
            if not isinstance(measure, dict):
                continue
            if measure.get("unitCode") != unit:
                raise ValueError("Unexpected Wisconet units for " + field)
            for observation in measure.get("observations", []):
                stamp = timestamp(observation.get("timestamp"))
                if stamp is None or not in_hour_window(stamp, hour):
                    continue
                # Z/blank means QC is unspecified, not a verified measurement.
                # Reject flagged suspect/bad values and unrecognized QC codes.
                qc = observation.get("qualityControl")
                if qc not in (None, "", "Z", "C", "S", "V", "G"):
                    continue
                value = number(observation.get("value"), low, high)
                sample = samples.setdefault(iso(stamp), {})
                sample[name] = value
                sample.setdefault("sourceQc", {})[name] = qc
        usable = [(stamp, sample) for stamp, sample in samples.items()
                  if any(sample.get(name) is not None for name in ("tempF", "dewpointF", "speedMph"))]
        if not usable:
            continue
        stamp, sample = max(usable, key=lambda item: item[0])
        temp, dew = sample.get("tempF"), sample.get("dewpointF")
        if temp is not None and dew is not None and dew > temp + 1:
            dew = None
        speed = sample.get("speedMph")
        rows.append({"station": station, "stationKey": "WISCONET:" + station,
                     "network": "WISCONET", "state": "WI", "name": properties.get("station_name", station),
                     "lat": lat, "lon": lon, "time": stamp, "tempF": temp, "dewpointF": dew,
                     "wind": {"speedMph": speed, "speedKnots": speed / 1.150779448 if speed is not None else None,
                              "direction": sample.get("direction"), "variable": False},
                     "source": "UW–Madison Wisconet", "sourceUrl": "https://wisconet.wisc.edu/",
                     "license": "CC BY 4.0", "sourceQc": sample["sourceQc"],
                     "measurementPeriod": "5-minute average", "quality": "range-age-source-flag-checked"})
    return rows
