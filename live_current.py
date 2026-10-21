"""Direct MADIS five-minute airport observations with a durable three-site hold."""
from datetime import datetime, timezone
import math

VERSION = "madis-five-minute-three-airports-v3"
SOURCE_NAME = "NOAA MADIS five-minute ASOS"
MAX_SPREAD_SECONDS = 15*60
UTC = timezone.utc


def direct_asos(stations, now, download):
    """Read public high-frequency airport ASOS directly, without an archive hop.

    This is the binary ASOS feed, not a routine text METAR. Its Kelvin fields
    are decoded by the MADIS reader, then normalized to whole Celsius degrees
    before the three-airport spatial average is calculated.
    """
    from madis_observations import get_reports
    rows = get_reports(stations, now, download)
    for row in rows:
        for field in ("temp", "dewp"):
            if row.get(field) is not None:
                row[field] = math.floor(row[field]+.5)
        row["source"] = SOURCE_NAME
    return rows


def latest_reports(rows, now):
    from app import STATIONS, valid_number
    latest = {}
    for row in rows:
        station, stamp = row.get("icaoId"), row.get("obsTime")
        if (station in STATIONS and row.get("source") == SOURCE_NAME
                and row.get("metarType") == "HFMETAR"
                and valid_number(stamp, 0, now.timestamp()) and stamp % 300 == 0):
            if station not in latest or stamp >= latest[station]["obsTime"]:
                latest[station] = row
    return [latest[s] for s in STATIONS if s in latest]


def candidate(rows, now):
    from app import STATIONS, summarize, iso, wind_mean
    rows = latest_reports(rows, now)
    stamps = [r["obsTime"] for r in rows]
    averaged = datetime.fromtimestamp(sum(stamps)/len(stamps), UTC) if stamps else now
    result = summarize(rows, averaged)
    by_station = {r["icaoId"]: r for r in rows}
    for station in result["stations"]:
        raw = by_station.get(station["code"], {})
        station.update(tempC=raw.get("temp"), dewpointC=raw.get("dewp"),
                       source=raw.get("source"), wind=wind_mean([raw]))
    missing = [s for s in STATIONS if s not in {r["icaoId"] for r in rows}]
    spread = max(stamps)-min(stamps) if stamps else None
    out_of_sync = [r["icaoId"] for r in rows if max(stamps)-r["obsTime"] > MAX_SPREAD_SECONDS]
    invalid = []
    for row in rows:
        if not summarize([row], averaged)["qa"]["stationsUsed"]:
            invalid.append(row["icaoId"])
    result.update(observedAt=iso(averaged) if stamps else None,
                  available=result["qa"]["allStationsUsed"] and spread <= MAX_SPREAD_SECONDS,
                  missingStations=missing, outOfSyncStations=out_of_sync, invalidStations=invalid,
                  timeSpreadExceeded=spread is not None and spread > MAX_SPREAD_SECONDS,
                  timestampSpreadSeconds=spread, maxSpreadSeconds=MAX_SPREAD_SECONDS)
    if result["wind"].get("variable"):
        result["wind"]["direction"] = None
    return result


def present(saved, now):
    """Station coherence uses report-to-report spread, never report age."""
    from app import iso
    if not saved or saved.get("version") != VERSION:
        return {"version": VERSION, "current": None, "held": False, "available": False,
                "candidate": candidate([], now), "checkedAt": None, "serverTime": iso(now),
                "sourceFailures": [], "collectorDelayed": True}
    current_candidate = candidate(saved.get("reports", []), now)
    delayed = (now-datetime.fromisoformat(saved["checkedAt"].replace("Z", "+00:00"))).total_seconds() > 300
    held = not current_candidate["available"]
    current = saved.get("lastGood") if held else current_candidate
    return {"version": VERSION, "current": current, "candidate": current_candidate,
            "available": current is not None, "held": held and current is not None,
            "checkedAt": saved["checkedAt"], "serverTime": iso(now), "collectorDelayed": delayed,
            "sourceFailures": saved.get("sourceFailures", []), "maxSpreadSeconds": MAX_SPREAD_SECONDS}


def collect(store, now, download=None):
    """Read only direct MADIS five-minute ASOS; no text-METAR fallback."""
    from app import STATIONS, iso
    from madis_observations import fetch_file
    previous = store.read_json("live/current.json") or {}
    # Earlier versions mixed feeds. Start clean rather than carrying any of
    # those reports or their lastGood average into this MADIS-only product.
    compatible = previous.get("version") == VERSION
    reports = list(previous.get("reports", [])) if compatible else []
    failures = []
    try:
        fresh = direct_asos(STATIONS, now, download or fetch_file)
        if not latest_reports(fresh, now):
            raise ValueError("No five-minute MADIS airport reports in response")
        reports.extend(fresh)
    except Exception:
        failures.append(SOURCE_NAME)
    reports = latest_reports(reports, now)
    state = candidate(reports, now)
    good = previous.get("lastGood") if compatible else None
    if state["available"]:
        good = state
    data = {"version": VERSION, "reports": reports, "lastGood": good, "checkedAt": iso(now),
            "sourceFailures": failures, "allSourcesFailed": bool(failures)}
    store.write_json("live/current.json", data)
    return present(data, now)
