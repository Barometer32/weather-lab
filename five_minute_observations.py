"""Three-airport average using only raw MADISHF five-minute METARs."""
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import StringIO
import math
import re
from statistics import mean
from urllib.parse import urlencode
import json
from zoneinfo import ZoneInfo

VERSION = "three-airport-rapid-main-c-v1"
KEY = "live/rapid-observations-v1.json"
STATIONS = ("KFCM", "KMSP", "KMIC")
MAX_AGE_SECONDS = 3600
DELAY_SECONDS = 900
UTC = timezone.utc


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def source_url(now):
    """Bulk archive, used only as a recovery source."""
    return "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" + urlencode({
        "network":"MN_ASOS", "station":[s[1:] for s in STATIONS], "data":"metar",
        "sts":(now-timedelta(seconds=MAX_AGE_SECONDS)).strftime("%Y-%m-%dT%H:%MZ"),
        "ets":(now+timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%MZ"),
        "tz":"Etc/UTC", "format":"onlycomma", "latlon":"no", "elev":"no",
        "missing":"M", "trace":"T", "direct":"no", "report_type":"1",
    }, doseq=True)


def live_urls(now):
    # The history service's date is local to each Minnesota station. Include
    # yesterday around midnight so the last complete batch survives day rollover.
    dates = sorted({(now-timedelta(seconds=seconds)).astimezone(ZoneInfo("America/Chicago")).date()
                    for seconds in (0, MAX_AGE_SECONDS)})
    return [(station, "https://mesonet.agron.iastate.edu/api/1/obhistory.json?"+urlencode({
        "network":"MN_ASOS", "station":station[1:], "date":day.isoformat(), "full":"true",
        # This API advertises a ten-minute HTTP cache lifetime. A minute bucket
        # prevents that cache from hiding newly ingested reports between polls.
        "_":int(now.timestamp())//60}))
        for station in STATIONS for day in dates]


def parse_live(payload, station, now):
    """Use literal raw METAR text; ignore the API's derived temperature fields."""
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("Invalid live five-minute history response")
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["station", "valid", "metar"])
    for row in data["data"]:
        if isinstance(row, dict):
            writer.writerow([station, row.get("utc_valid"), row.get("raw")])
    return parse_reports(out.getvalue().encode(), now)


def fetch_reports(now, download):
    def fetch(item):
        station, url = item
        try:
            return parse_live(download(url), station, now), None
        except Exception as error:
            return [], error
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(fetch, live_urls(now)))
    fresh = [report for reports, _ in results for report in reports]
    if not fresh or any(error is not None for _, error in results):
        try:
            # Append live records last: a same-time live correction wins.
            fresh = parse_reports(download(source_url(now)), now)+fresh
        except Exception:
            if not fresh:
                raise
    return fresh


def parse_reports(payload, now):
    rows = csv.DictReader(StringIO(payload.decode("utf-8-sig")))
    if not rows.fieldnames or not {"station", "valid", "metar"} <= set(rows.fieldnames):
        raise ValueError("Invalid five-minute raw METAR response")
    reports = []
    for row in rows:
        station = (row.get("station") or "").strip().upper()
        station = station if len(station)==4 else "K"+station
        if station not in STATIONS:
            continue
        raw = row.get("metar") or ""
        body, _, remarks = raw.partition(" RMK")
        if (not re.search(r"\bMADISHF\b", remarks)
                or not re.match(r"^(?:METAR\s+)?"+station+r"\s+", body)
                or re.search(r"\b(?:SPECI|NIL)\b", body)):
            continue
        try:
            observed = datetime.fromisoformat(row["valid"].replace("Z", "+00:00"))
            observed = observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed.astimezone(UTC)
        except (ValueError, TypeError):
            continue
        if (observed.minute%5 or observed.second or observed.microsecond
                or not 0 <= (now-observed).total_seconds() <= MAX_AGE_SECONDS):
            continue
        stamp = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", body)
        if not stamp or tuple(map(int,stamp.groups())) != (observed.day,observed.hour,observed.minute):
            continue
        # Whole Celsius comes exclusively from the main XX/XX group, never T remarks.
        group = re.search(r"(?:^|\s)(M?\d{2}|//)/(M?\d{2}|//)(?=\s|$)", body)
        def degrees(value):
            return None if value=="//" else int(value.replace("M", "-"))
        temp, dew = (degrees(group[1]),degrees(group[2])) if group else (None,None)
        if temp is not None and not -90 <= temp <= 65:
            temp = None
        if dew is not None and (not -100 <= dew <= 60 or temp is not None and dew > temp):
            dew = None
        wind = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G\d{2,3})?KT\b", body)
        knots = int(wind[2]) if wind else None
        speed = knots*1852/1609.344 if knots is not None and knots<=250 else None
        reports.append({"station":station,"time":iso(observed),"tempC":temp,"dewpointC":dew,
                        "windSpeedMph":speed,
                        "windDirection":int(wind[1])%360 if wind and wind[1]!="VRB" and int(wind[1])<=360 else None,
                        "windVariable":bool(wind and wind[1]=="VRB"),"rawOb":raw,"reportType":"HFMETAR",
                        "temperatureBasis":"main-XX/XX"})
    return reports


def recent(report, now):
    try:
        observed = datetime.fromisoformat(report["time"].replace("Z", "+00:00"))
        return (report.get("station") in STATIONS and report.get("reportType")=="HFMETAR"
                and report.get("temperatureBasis")=="main-XX/XX"
                and observed.minute%5==0 and observed.second==0 and observed.microsecond==0
                and 0 <= (now-observed).total_seconds() <= MAX_AGE_SECONDS)
    except (ValueError, KeyError, TypeError):
        return False


CARDINALS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def wind_direction(reports):
    speed = mean(r["windSpeedMph"] for r in reports)
    if speed==0:
        return None, "Calm"
    east, north = 0.0, 0.0
    for report in reports:
        if report["windSpeedMph"]==0:
            continue
        # Decode raw direction here too so old prepared snapshots remain usable.
        body = report.get("rawOb", "").partition(" RMK")[0]
        wind = re.search(r"\b(\d{3}|VRB)\d{2,3}(?:G\d{2,3})?KT\b", body)
        direction = int(wind[1]) if wind and wind[1]!="VRB" else None
        if direction is None or direction>360:
            return None, "Variable" if wind and wind[1]=="VRB" else "Unknown"
        east += report["windSpeedMph"]*math.sin(math.radians(direction))
        north += report["windSpeedMph"]*math.cos(math.radians(direction))
    # Opposing winds can cancel direction while the scalar mean speed stays nonzero.
    if math.hypot(east,north)<1e-6:
        return None, "Variable"
    direction = math.degrees(math.atan2(east,north))%360
    if abs(direction-360)<1e-8:
        direction = 0.0
    return direction, CARDINALS[int(math.floor((direction+22.5)/45))%8]


def average(reports, now):
    if (len(reports)!=3 or {r.get("station") for r in reports}!=set(STATIONS)
            or len({r.get("time") for r in reports})!=1 or not all(recent(r,now) for r in reports)):
        return None
    for r in reports:
        if (type(r.get("tempC")) is not int or type(r.get("dewpointC")) is not int
                or not -90 <= r["tempC"] <= 65 or not -100 <= r["dewpointC"] <= min(60,r["tempC"])
                or not isinstance(r.get("windSpeedMph"),(int,float))
                or not math.isfinite(r["windSpeedMph"]) or not 0 <= r["windSpeedMph"] <= 290):
            return None
    temp, dew = mean(r["tempC"] for r in reports), mean(r["dewpointC"] for r in reports)
    direction, cardinal = wind_direction(reports)
    return {"observedAt":reports[0]["time"],"temperatureC":temp,"dewpointC":dew,
            "temperatureF":temp*1.8+32,"dewpointF":dew*1.8+32,
            "windSpeedMph":mean(r["windSpeedMph"] for r in reports),
            "windDirection":direction,"windCardinal":cardinal,
            "stations":sorted(reports,key=lambda r:STATIONS.index(r["station"]))}


def collect(store, now, download=None):
    if download is None:
        from app import download
    previous = store.read_json(KEY) or {}
    if previous.get("version")!=VERSION:
        previous = {}
    pool = {(r["station"],r["time"]):r for r in previous.get("reports",[]) if recent(r,now)}
    fresh = fetch_reports(now, download)
    if not fresh:
        raise ValueError("No five-minute reports returned; prior snapshot retained")
    # Reissued reports replace the entire record, including newly missing fields.
    pool.update({(r["station"],r["time"]):r for r in fresh})
    times = [{t for s,t in pool if s==station} for station in STATIONS]
    common = set.intersection(*times)
    candidate = average([pool[(s,max(common))] for s in STATIONS],now) if common else None
    old = average((previous.get("current") or {}).get("stations",[]),now)
    if old and candidate and candidate["observedAt"] < old["observedAt"]:
        candidate = None
    if old and common and max(common)==old["observedAt"] and candidate is None:
        old = None  # A same-time correction invalidates the previously complete record.
    current = candidate or old
    snapshot = {"version":VERSION,"checkedAt":iso(now),"current":current,
                "reports":sorted(pool.values(),key=lambda r:(r["time"],r["station"]))}
    store.write_json(KEY,snapshot)
    return {"available":current is not None,"observedAt":current["observedAt"] if current else None,
            "reports":len(pool)}


def present(snapshot, now):
    if not snapshot or snapshot.get("version")!=VERSION:
        raise ValueError("Three-airport five-minute observations have not been prepared")
    current = average((snapshot.get("current") or {}).get("stations",[]),now)
    reports = [r for r in snapshot.get("reports",[]) if recent(r,now)]
    latest = {s:max((r for r in reports if r["station"]==s),key=lambda r:r["time"],default=None) for s in STATIONS}
    newest = max((r["time"] for r in reports),default=None)
    checked = datetime.fromisoformat(snapshot["checkedAt"].replace("Z", "+00:00"))
    age = (now-datetime.fromisoformat(current["observedAt"].replace("Z", "+00:00"))).total_seconds() if current else None
    return {"version":VERSION,"current":current,"available":current is not None,
            "stations":current["stations"] if current else [r for r in latest.values() if r],
            "stationIds":list(STATIONS),"checkedAt":snapshot["checkedAt"],"serverTime":iso(now),
            "updateIntervalSeconds":300,"checkIntervalSeconds":60,"maxAgeSeconds":MAX_AGE_SECONDS,"ageSeconds":age,
            "stale":(now-checked).total_seconds()>600,"sourceDelayed":age is None or age>DELAY_SECONDS,
            "waiting":current is None or newest is not None and newest>current["observedAt"],
            "temperatureBasis":"main-XX/XX","reportType":"HFMETAR","source":"NOAA MADIS five-minute ASOS via Iowa Environmental Mesonet"}
