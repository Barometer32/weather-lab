"""The Observations page's twelve official three-airport METAR hours."""
from datetime import timedelta
import json
from urllib.parse import urlencode

import app as weather

KEY = "live/hourly-airport-observations-v1.json"
SOURCE = "NOAA Aviation Weather Center"
HISTORY_HOURS = 12


def select_reports(reports, now):
    target = now.replace(minute=0, second=0, microsecond=0)
    start = target - timedelta(hours=HISTORY_HOURS - 1)
    chosen = {}
    for report in reports:
        station = report.get("icaoId")
        raw = report.get("rawOb") or ""
        if station not in weather.STATIONS or not raw or "NIL" in raw.partition(" RMK")[0].split():
            continue
        hour = weather.routine_hour(report, now, first_minute=50)
        if hour is None or not start <= hour <= target:
            continue
        key = hour, station
        rank = weather.routine_report_rank(report, hour)
        if key not in chosen or rank <= chosen[key][0]:
            chosen[key] = rank, report
    return chosen


def present(saved, now):
    saved = saved or {}
    target = now.replace(minute=0, second=0, microsecond=0)
    selected = select_reports(saved.get("reports", []), now)
    history = []
    for offset in range(HISTORY_HOURS):
        hour = target - timedelta(hours=offset)
        reports = [weather.metar_precision(selected[hour, station][1], fallback=False)
                   for station in weather.STATIONS if (hour, station) in selected]
        row = weather.summarize(reports, hour, mean_digits=0)
        wind = row["wind"]
        complete = all(count == len(weather.STATIONS) for count in
                       (row["tempCount"], row["dewpointCount"], wind["speedCount"]))
        history.append({
            "hour": row["hour"], "count": row["count"], "stations": row["stations"], "complete": complete,
            "tempF": row["tempF"] if row["tempCount"] == len(weather.STATIONS) else None,
            "dewpointF": row["dewpointF"] if row["dewpointCount"] == len(weather.STATIONS) else None,
            "wind": {
                "speedMph": wind["speedMph"] if wind["speedCount"] == len(weather.STATIONS) else None,
                "direction": wind["direction"],
                "variable": wind["direction"] is None and
                (wind["variable"] or wind["directionCount"] == len(weather.STATIONS)),
            },
        })
    current = next((row for row in history[:2] if row["complete"]), None)
    return {"current": current, "history": history, "checkedAt": saved.get("checkedAt"),
            "serverTime": weather.iso(now), "source": SOURCE, "stationCount": len(weather.STATIONS)}


def collect(store, now):
    from metar_history import ARCHIVE_URL

    saved = store.read_json(KEY) or {}
    target = now.replace(minute=0, second=0, microsecond=0)
    # Skip follow-up checks once all three fields have twelve complete hours.
    # If a station is late, the same archive repairs gaps.
    if all(None not in (row["tempF"], row["dewpointF"], row["wind"]["speedMph"])
           for row in present(saved, now)["history"]):
        return {"status": "already prepared", "checkedAt": saved["checkedAt"]}

    params = {"ids": ",".join(weather.STATIONS), "format": "json",
              "hours": HISTORY_HOURS + 1, "date": weather.iso(target)}
    payload = weather.download(ARCHIVE_URL + "?" + urlencode(params))
    fresh = json.loads(payload) if payload else []
    if not isinstance(fresh, list) or not select_reports(fresh, now):
        raise ValueError("NOAA returned no eligible hourly airport reports")
    selected = select_reports([*saved.get("reports", []), *fresh], now)
    data = {"checkedAt": weather.iso(now), "reports": [report for _, report in selected.values()]}
    store.write_json(KEY, data)
    return {"reports": len(selected), "checkedAt": data["checkedAt"]}
