"""Latest airport METAR/5-minute Celsius groups with a durable three-site hold."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode

from rapid_observations import parse_reports, recent_metars

VERSION = "latest-three-airports-celsius-v1"
MAX_AGE_SECONDS = 15*60
UTC = timezone.utc


def latest_reports(rows, now):
    from app import STATIONS, valid_number
    latest = {}
    for row in rows:
        station, stamp = row.get("icaoId"), row.get("obsTime")
        if station in STATIONS and valid_number(stamp, now.timestamp()-3600, now.timestamp()):
            if station not in latest or stamp >= latest[station]["obsTime"]:
                latest[station] = row
    return [latest[s] for s in STATIONS if s in latest]


def candidate(rows, now):
    from app import STATIONS, summarize, iso
    rows = latest_reports(rows, now)
    stamps = [r["obsTime"] for r in rows]
    averaged = datetime.fromtimestamp(sum(stamps)/len(stamps), UTC) if stamps else now
    result = summarize(rows, averaged)
    by_station = {r["icaoId"]: r for r in rows}
    for station in result["stations"]:
        raw = by_station.get(station["code"], {})
        station.update(tempC=raw.get("temp"), dewpointC=raw.get("dewp"))
    stale = [r["icaoId"] for r in rows if now.timestamp()-r["obsTime"] > MAX_AGE_SECONDS]
    missing = [s for s in STATIONS if s not in {r["icaoId"] for r in rows}]
    spread = max(stamps)-min(stamps) if stamps else None
    invalid = []
    for row in rows:
        if not summarize([row], averaged)["qa"]["stationsUsed"]:
            invalid.append(row["icaoId"])
    result.update(observedAt=iso(averaged) if stamps else None,
                  available=result["qa"]["allStationsUsed"] and not stale and spread <= MAX_AGE_SECONDS,
                  missingStations=missing, staleStations=stale, invalidStations=invalid,
                  timestampSpreadSeconds=spread, maxAgeSeconds=MAX_AGE_SECONDS)
    if result["wind"].get("variable"):
        result["wind"]["direction"] = None
    return result


def present(saved, now):
    """Recheck age on every read, even if scheduled collection stopped."""
    from app import iso
    if not saved or saved.get("version") != VERSION:
        return {"version": VERSION, "current": None, "held": False, "available": False,
                "candidate": candidate([], now), "checkedAt": None, "serverTime": iso(now),
                "sourceFailures": [], "collectorDelayed": True}
    current_candidate = candidate(saved.get("reports", []), now)
    delayed = (now-datetime.fromisoformat(saved["checkedAt"].replace("Z", "+00:00"))).total_seconds() > 300
    held = not current_candidate["available"] or delayed or saved.get("allSourcesFailed", False)
    current = saved.get("lastGood") if held else current_candidate
    return {"version": VERSION, "current": current, "candidate": current_candidate,
            "available": current is not None, "held": held and current is not None,
            "checkedAt": saved["checkedAt"], "serverTime": iso(now), "collectorDelayed": delayed,
            "sourceFailures": saved.get("sourceFailures", []), "maxAgeSeconds": MAX_AGE_SECONDS}


def collect(store, now, download):
    from app import STATIONS, iso
    previous = store.read_json("live/current.json") or {}
    params = [("station", s[1:]) for s in STATIONS] + [
        ("data", "metar"), ("sts", (now-timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ")),
        ("ets", now.strftime("%Y-%m-%dT%H:%MZ")), ("tz", "Etc/UTC"),
        ("format", "onlycomma"), ("report_type", "1,3,4")]
    sources = {
        "IEM airport METAR/5-minute archive": ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"+urlencode(params),
            lambda payload: parse_reports(payload, STATIONS, now)),
        "NOAA Aviation Weather Center": ("https://aviationweather.gov/api/data/metar?"+urlencode(
            {"ids": ",".join(STATIONS), "format": "json", "hours": 1}),
            lambda payload: recent_metars(json.loads(payload), STATIONS, now))}
    reports = list(previous.get("reports", [])) if previous.get("version") == VERSION else []
    failures = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = {name: pool.submit(lambda u=url, p=parse: p(download(u))) for name, (url, parse) in sources.items()}
        # Prefer AWC corrections when observation timestamps tie.
        for name, task in tasks.items():
            try:
                fresh = task.result()
                if not fresh:
                    raise ValueError("No recent airport reports in source response")
                reports.extend(fresh)
            except Exception:
                failures.append(name)
    reports = latest_reports(reports, now)
    state = candidate(reports, now)
    good = previous.get("lastGood") if previous.get("version") == VERSION else None
    if state["available"] and len(failures) < len(sources):
        good = state
    data = {"version": VERSION, "reports": reports, "lastGood": good, "checkedAt": iso(now),
            "sourceFailures": failures, "allSourcesFailed": len(failures) == len(sources)}
    store.write_json("live/current.json", data)
    return present(data, now)
