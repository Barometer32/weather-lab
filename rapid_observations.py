"""Recent ASOS reports: decode Celsius from raw reports, never Fahrenheit."""
import csv
from datetime import datetime, timezone
from io import StringIO
import re
MAX_SPREAD_SECONDS = 1800  # Warning threshold, not a reason to drop a contributor.
MAX_AGE_SECONDS = 3600  # Match the rolling source/collector retention window.


def parse_reports(payload, stations, now):
    rows = csv.DictReader(StringIO(payload.decode("utf-8")))
    if not rows.fieldnames or not {"station", "valid", "metar"} <= set(rows.fieldnames):
        raise ValueError("Invalid recent ASOS response")
    result = []
    for row in rows:
        station = row["station"]
        station = station if station in stations else "K" + station
        if station not in stations:
            continue
        raw = row["metar"] or ""
        # Ignore remarks, including Fahrenheit fields and higher precision T
        # groups. Use the same main Celsius group for rapid/routine/SPECI reports.
        body = raw.split(" RMK")[0]
        if not re.search(r"\b" + re.escape(station) + r"\b", body) or re.search(r"\bNIL\b", body):
            continue
        try:
            observed = datetime.fromisoformat(row["valid"].replace("Z", "+00:00"))
            observed = observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if not 0 <= (now - observed).total_seconds() <= 3600:
            continue
        stamp = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", body)
        if not stamp or tuple(map(int, stamp.groups())) != (observed.day, observed.hour, observed.minute):
            continue
        temperature = re.search(r"(?:^|\s)(M?\d{2}|//)/(M?\d{2}|//)(?=\s|$)", body)
        def degrees(group):
            return None if group == "//" else int(group.replace("M", "-"))
        wind = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G\d{2,3})?KT\b", body)
        altimeter = re.search(r"\bA(\d{4})\b", body)
        result.append({"icaoId": station, "obsTime": observed.timestamp(),
            "metarType": "HFMETAR" if "MADISHF" in raw else "SPECI" if raw.startswith("SPECI") else "METAR",
            "temp": degrees(temperature[1]) if temperature else None,
            "dewp": degrees(temperature[2]) if temperature else None,
            "wdir": ("VRB" if wind[1] == "VRB" else int(wind[1])) if wind else None,
            "wspd": int(wind[2]) if wind else None,
            "altim": int(altimeter[1]) / 100 * 33.8638866667 if altimeter else None,
            "rawOb": raw})
    return result


def current_snapshot(reports, now):
    from app import STATIONS, valid_number, summarize, iso
    latest = {}
    for report in reports:
        station, stamp = report.get("icaoId"), report.get("obsTime")
        if station in STATIONS and valid_number(stamp, now.timestamp()-MAX_AGE_SECONDS, now.timestamp()):
            previous = latest.get(station)
            if previous is None or stamp >= previous["obsTime"]:
                latest[station] = report
    anchor = max((r["obsTime"] for r in latest.values()), default=None)
    age = now.timestamp() - anchor if anchor is not None else None
    chosen = list(latest.values())
    oldest = min((r["obsTime"] for r in chosen), default=None)
    spread = anchor-oldest if anchor is not None else None
    lagging = [station for station in STATIONS if station in latest
               and anchor-latest[station]["obsTime"] > MAX_SPREAD_SECONDS]
    mean_stamp = sum(r["obsTime"] for r in chosen) / len(chosen) if chosen else None
    result = summarize(chosen, datetime.fromtimestamp(mean_stamp, timezone.utc) if mean_stamp is not None else now)
    available = result["qa"]["allStationsUsed"]
    result.update(available=available, observedAt=iso(datetime.fromtimestamp(mean_stamp, timezone.utc)) if available else None,
                  newestObservedAt=iso(datetime.fromtimestamp(anchor, timezone.utc)) if anchor is not None else None,
                  oldestObservedAt=iso(datetime.fromtimestamp(min(r["obsTime"] for r in chosen), timezone.utc)) if chosen else None,
                  ageSeconds=age, maxSpreadSeconds=MAX_SPREAD_SECONDS, maxAgeSeconds=MAX_AGE_SECONDS,
                  timestampSpreadSeconds=spread, timeSpreadWarning=bool(lagging), outOfSyncStations=lagging,
                  missingStations=[station for station in STATIONS if station not in latest])
    if not result["available"]:
        result.update(tempF=None, tempC=None, dewpointF=None, dewpointC=None, pressureHpa=None,
                      wind={"speedMph": None, "direction": None, "speedCount": 0, "directionCount": 0})
    return result


def recent_metars(reports, stations, now):
    """Reuse already-fetched AWC routine/SPECI reports when they arrive sooner."""
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["station", "valid", "metar"])
    for report in reports:
        stamp = report.get("obsTime")
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
            continue
        if not now.timestamp() - 3600 <= stamp <= now.timestamp():
            continue
        writer.writerow([report.get("icaoId", ""), datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                         report.get("rawOb", "")])
    return parse_reports(stream.getvalue().encode(), stations, now)
