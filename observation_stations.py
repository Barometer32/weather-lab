"""Latest public Hennepin West stations in Hennepin County; no averaging."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
from urllib.error import HTTPError

VERSION = "hennepin-west-station-list-v1"
KEY = "live/observation-stations.json"
UTC = timezone.utc


def iso(moment):
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def county_geometry():
    return json.loads((Path(__file__).parent / "static/hennepin-county.geojson").read_text())["features"][0]["geometry"]


def inside_ring(lon, lat, ring):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]+ring[:1]):
        cross = (lon-x1)*(y2-y1)-(lat-y1)*(x2-x1)
        if abs(cross) < 1e-10 and min(x1,x2)-1e-10 <= lon <= max(x1,x2)+1e-10 and min(y1,y2)-1e-10 <= lat <= max(y1,y2)+1e-10:
            return True
        if (y1 > lat) != (y2 > lat) and lon < x1+(lat-y1)*(x2-x1)/(y2-y1):
            inside = not inside
    return inside


def in_county(lat, lon):
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lat,lon)):
        return False
    geometry = county_geometry()
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return any(inside_ring(lon,lat,polygon[0]) and not any(inside_ring(lon,lat,hole) for hole in polygon[1:]) for polygon in polygons)


def bounds():
    geometry = county_geometry()
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    points = [point for polygon in polygons for ring in polygon for point in ring]
    return min(p[1] for p in points),min(p[0] for p in points),max(p[1] for p in points),max(p[0] for p in points)


def latest(rows, now):
    from local_current import place
    selected = {}
    for source in rows:
        row = dict(source)
        if row.get("network") != "Hennepin West" or not row.get("station") or not in_county(row.get("lat"),row.get("lon")):
            continue
        try:
            stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            if not now-timedelta(hours=24) <= stamp <= now:
                continue
        except (ValueError,KeyError,TypeError):
            continue
        row["displayName"] = place(row)
        old = selected.get(row["station"])
        # The refreshed copy wins at equal observation times (including QC corrections).
        if old is None or row["time"] >= old["time"]:
            selected[row["station"]] = row
    return sorted(selected.values(),key=lambda row:(row.get("network", ""),row["displayName"],row["station"]))


def present(saved, now):
    compatible = bool(saved and saved.get("version") == VERSION)
    saved = saved if compatible else {}
    stations = latest(saved.get("stations",[]),now)
    for row in stations:
        stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        row["ageMinutes"] = round((now-stamp).total_seconds()/60,1)
    checked = saved.get("checkedAt")
    return {"version":VERSION,"region":"Hennepin County","stations":stations,
            "networks":sorted({row.get("network") or "Other" for row in stations}),
            "checkedAt":checked,"serverTime":iso(now),"sourceFailures":saved.get("sourceFailures",[]),
            "collectorDelayed":not checked or (now-datetime.fromisoformat(checked.replace("Z", "+00:00"))).total_seconds()>360,
            "average":None}


def collect(store, now, download=None):
    import regional_madis
    download = download or regional_madis.fetch
    previous = store.read_json(KEY) or {}
    if previous.get("version") != VERSION:
        previous = {}
    hour = now.replace(minute=0,second=0,microsecond=0)
    files, errors, rows = {}, [], list(previous.get("stations",[]))
    for offset in (0,1):
        filename = (hour-timedelta(hours=offset)).strftime("%Y%m%d_%H00.gz")
        key = "mesonet/"+filename
        old = previous.get("files",{}).get(key,{})
        try:
            payload, meta = download(regional_madis.SOURCE+filename,old.get("metadata"))
            if payload is None:
                fresh = old.get("stations",[])
            else:
                parsed = regional_madis.parse_file(payload,now,window_start=now-timedelta(hours=2),
                    window_end=now+timedelta(microseconds=1),bounds=bounds(),include_invalid=True,excluded_stations=())
                fresh = latest(parsed,now)
            files[key] = {"metadata":meta,"stations":fresh}
            rows.extend(fresh)
        except Exception as error:
            # A current-hour file may not exist until its first batch arrives.
            if not (isinstance(error,HTTPError) and error.code == 404 and offset == 0):
                errors.append({"file":key,"error":str(error)[:160]})
            if old:
                files[key] = old
                rows.extend(old.get("stations",[]))
    saved = {"version":VERSION,"stations":latest(rows,now),"files":files,"checkedAt":iso(now),"sourceFailures":errors}
    if not saved["stations"]:
        raise ValueError("No public Hennepin West observations are available; previous inventory retained")
    store.write_json(KEY,saved)
    return present(saved,now)


if __name__ == "__main__":
    from realtime import get_store
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET is required")
    result = collect(store,datetime.now(UTC))
    print(len(result["stations"]),"public Hennepin County stations; average not selected",flush=True)
