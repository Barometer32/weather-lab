"""Rolling Fahrenheit averages for the user's retained 19-site Mesonet roster."""
from datetime import datetime, timezone
import math
from statistics import mean

import observation_stations as inventory

VERSION = "hennepin-west-average-v1"
KEY = "live/hennepin-observations-v1.json"
POLICY = "approved-hennepin-west-19-v1"
# Restored verbatim from the approved roster in aa4fc5a, not rediscovered from
# whichever sites happen to report today. New or previously removed sites cannot
# enter the average automatically.
STATIONS = {
    "HPN02":"Maple Grove", "HPN03":"Chanhassen", "HPN05":"Medina",
    "HPN07":"MSP Airport", "HPN08":"Orono", "HPN09":"Plymouth",
    "HPN20":"Hopkins", "HPN21":"Fridley", "HPN24":"Edina",
    "HPN25":"Minnetonka", "HPN26":"Bloomington", "HPN28":"Corcoran",
    "HPN30":"Falcon Heights", "HPN31":"Blaine", "HPN37":"Long Lake",
    "HPN38":"Eden Prairie", "HPN39":"Minneapolis",
    "HPN45":"Science Museum of Minnesota", "HPN47":"Golden Valley",
}
MAX_AGE_SECONDS = 1800  # Same 30-minute live window as the approved prior average.
UTC = timezone.utc
DIRECTIONS = ("N","NE","E","SE","S","SW","W","NW")


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def finite(value, low, high):
    return type(value) in (int,float) and math.isfinite(value) and low <= value <= high


def select(rows, now):
    latest = {}
    for row in rows:
        if row.get("station") not in STATIONS or not inventory.included_site(row) or not inventory.included_on_map(row):
            continue
        try:
            stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            age = (now-stamp).total_seconds()
        except (KeyError,ValueError,TypeError):
            continue
        if not 0 <= age <= MAX_AGE_SECONDS:
            continue
        wind = row.get("wind") or {}
        temp = row.get("tempF") if finite(row.get("tempF"),-130,140) else None
        dew = row.get("dewpointF") if finite(row.get("dewpointF"),-148,140) else None
        if temp is not None and dew is not None and dew > temp+3.6:
            dew = None
        speed = wind.get("speedMph") if finite(wind.get("speedMph"),0,231) else None
        direction = wind.get("direction") if finite(wind.get("direction"),0,360) else None
        report = {"station":row["station"],"displayName":STATIONS[row["station"]],
                  "network":"Hennepin West","lat":row["lat"],"lon":row["lon"],"time":iso(stamp),
                  "tempF":temp,"dewpointF":dew,"windSpeedMph":speed,
                  "windDirection":direction%360 if direction is not None else None,
                  "windVariable":bool(wind.get("variable")),"reportType":"MESONET"}
        old = latest.get(report["station"])
        if old is None or report["time"]>=old["time"]:
            latest[report["station"]] = report
    return sorted(latest.values(),key=lambda row:(row["displayName"],row["station"]))


def average(reports):
    useful = [r for r in reports if any(r.get(k) is not None for k in ("tempF","dewpointF","windSpeedMph"))]
    if not useful:
        return None
    values = {key:[r[key] for r in useful if r[key] is not None] for key in ("tempF","dewpointF","windSpeedMph")}
    winds = [r for r in useful if r["windSpeedMph"] is not None]
    vectors = [r for r in winds if r["windSpeedMph"]>0 and r["windDirection"] is not None and not r["windVariable"]]
    speed = mean(values["windSpeedMph"]) if winds else None
    east = math.fsum(r["windSpeedMph"]*math.sin(math.radians(r["windDirection"])) for r in vectors)
    north = math.fsum(r["windSpeedMph"]*math.cos(math.radians(r["windDirection"])) for r in vectors)
    direction = math.degrees(math.atan2(east,north))%360 if math.hypot(east,north)>1e-6 else None
    if direction is not None and abs(direction-360)<1e-8:
        direction = 0.0
    cardinal = ("Calm" if speed==0 else DIRECTIONS[int((direction+22.5)//45)%8]
                if direction is not None else "Variable" if vectors or any(r["windVariable"] for r in winds) else "Unknown")
    return {"observedAt":max(r["time"] for r in useful),"oldestObservedAt":min(r["time"] for r in useful),
            "temperatureF":mean(values["tempF"]) if values["tempF"] else None,
            "dewpointF":mean(values["dewpointF"]) if values["dewpointF"] else None,
            "windSpeedMph":speed,"windDirection":direction,"windCardinal":cardinal,
            "stationCount":len(useful),"sampleCounts":{"temperature":len(values["tempF"]),
                "dewpoint":len(values["dewpointF"]),"windSpeed":len(winds),"windDirection":len(vectors)},
            "stations":useful}


def present(saved, now):
    if not saved or saved.get("version")!=VERSION or saved.get("stationPolicy")!=POLICY:
        raise ValueError("Approved Hennepin West observations have not been prepared")
    # Reapply roster, age and measurement checks on every response. Even a saved
    # snapshot cannot silently include an excluded station or expired reading.
    reports = select(saved.get("reports",[]),now)
    current = average(reports)
    checked = datetime.fromisoformat(saved["checkedAt"].replace("Z", "+00:00"))
    failures = saved.get("sourceFailures",[])
    age = (now-datetime.fromisoformat(current["oldestObservedAt"].replace("Z", "+00:00"))).total_seconds() if current else None
    return {"version":VERSION,"stationPolicy":POLICY,"temperatureBasis":"reported-Fahrenheit",
            "current":current,"available":current is not None,"stations":reports,
            "stationIds":sorted(STATIONS),"expectedStationCount":len(STATIONS),
            "checkedAt":saved["checkedAt"],"serverTime":iso(now),"updateIntervalSeconds":300,"checkIntervalSeconds":300,
            "maxAgeSeconds":MAX_AGE_SECONDS,"ageSeconds":age,"stale":(now-checked).total_seconds()>660 or bool(failures),
            "sourceDelayed":age is None or age>900,"sourceFailures":failures,
            "source":"NOAA MADIS · Hennepin West Mesonet"}


def collect(store, now, download=None):
    # Inventory uses conditional downloads of the current and previous hourly
    # MADIS files. They contain rolling station readings, not hourly averages.
    inventory.collect(store,now,download=download)
    source = store.read_json(inventory.KEY)
    snapshot = {"version":VERSION,"stationPolicy":POLICY,"checkedAt":source["checkedAt"],
                "reports":[r for r in source.get("stations",[]) if r.get("station") in STATIONS],"sourceFailures":source.get("sourceFailures",[])}
    # Keep the source-style per-station records so future responses can reapply
    # QC/expiry without rounding, inventing timestamps, or importing airport data.
    result = present(snapshot,now)
    if not result["available"]:
        raise ValueError("No recent approved Hennepin West measurements; previous snapshot retained")
    store.write_json(KEY,snapshot)
    return {"available":True,"stations":result["current"]["stationCount"],
            "expectedStations":len(STATIONS),"oldestObservedAt":result["current"]["oldestObservedAt"],
            "observedAt":result["current"]["observedAt"],"sourceFailures":result["sourceFailures"]}
