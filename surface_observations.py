"""Hourly public mesonet/RWIS observations, separate from routine METARs.

MADIS QC descriptors and result bitmaps are preserved per variable. Airports
reuse the existing :00 snapshot. Road fallbacks have local checks only and are
never presented as MADIS-verified. No private/restricted endpoints are used.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import json
import logging
import math
import re
import tempfile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from scipy.io import netcdf_file

VERSION = 1
BOUNDS = [[40, -104.5], [49.5, -84]]
MADIS_URL = "https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/mesonet/netCDF/"
RWIS_URL = "https://mesonet.agron.iastate.edu/api/1/rwis.json"
WISCONET_URL = "https://wisconet.wisc.edu/api/v2/stations/map"
WISCONET_FIELDS = {
    "5min_air_temp_f_avg":("tempF","ud:degF",-76,131),
    "5min_dew_point_f_avg":("dewpointF","ud:degF",-94,104),
    "5min_relative_humidity_pct_avg":("rh","wn:pct",0,100),
    "5min_wind_speed_mph_avg":("windMph","wn:mph",0,287),
    "5min_wind_dir_deg_avg":("direction","ud:degree",0,360),
    "5min_wind_gust_mph_max":("gustMph","wn:mph",0,330),
}
EXCLUDED = {"KCFE", "KFCE", "KSGS"}
FIELDS = {
    "temperature": ("tempF", "kelvin", -60, 55),
    "dewpoint": ("dewpointF", "kelvin", -70, 40),
    "relHumidity": ("rh", "percent", 0, 100),
    "windSpeed": ("windMph", "meter/sec", 0, 130),
    "windDir": ("direction", "degree", 0, 360),
    "windGust": ("gustMph", "meter/sec", 0, 160),
}


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def number(value, low, high):
    try:
        result = float(value)
        return result if math.isfinite(result) and low <= result <= high else None
    except (TypeError, ValueError):
        return None


def in_region(lat, lon):
    return number(lat, 40, 49.5) is not None and number(lon, -104.5, -84) is not None


def text(value):
    return value.tobytes().decode("ascii", errors="replace").split("\x00")[0].strip()


def read_madis(path, hour, road_sites=None):
    """Read only regional rows from a mapped classic NetCDF file.

    Mapping the temporary file avoids a second full in-memory data copy. The
    production collector has 2 GiB because Cloud Run temporary files use RAM.
    """
    road_sites = road_sites or {}
    rows = {}
    with netcdf_file(path, mmap=True) as ds:
        v, field = None, None
        try:
            v = ds.variables
            needed = {"stationId", "latitude", "longitude", "observationTime", "temperature"}
            if not needed <= v.keys():
                raise ValueError("MADIS mesonet file missing station metadata")
            for name, (_, units, _, _) in FIELDS.items():
                if name in v and getattr(v[name], "units", b"").decode() != units:
                    raise ValueError("Unexpected MADIS units: " + name)
            # Copy these small columns only; don't hold mmap-backed views on close.
            lats = v["latitude"][:].copy()
            lons = v["longitude"][:].copy()
            stamps = v["observationTime"][:].copy()
            candidates = np.flatnonzero((lats >= 40) & (lats <= 49.5) &
                (lons >= -104.5) & (lons <= -84) &
                (stamps >= hour.timestamp()-1800) & (stamps <= hour.timestamp()))
            field = None
            for i in candidates:
                station = text(v["stationId"][i])
                if station in EXCLUDED or not re.fullmatch(r"[A-Za-z0-9_.-]{1,24}", station):
                    continue
                # The public endpoint normally strips restricted records. Enforce
                # that restriction again if the field is present in a source file.
                if "restrictedDataLevel" in v:
                    restriction = int(v["restrictedDataLevel"][i])
                    if restriction >= 2:
                        continue
                provider = text(v["dataProvider"][i]) if "dataProvider" in v else "MADIS"
                name = text(v["stationName"][i]) if "stationName" in v else station
                road = road_sites.get(station)
                if road and (abs(road["lat"]-float(lats[i])) > .01 or abs(road["lon"]-float(lons[i])) > .01):
                    road = None
                kind = "road" if road or "DOT" in name.upper() or re.fullmatch(r"MN\d{3}", station) else "mesonet"
                if station.startswith("K") and "AWOS" in provider.upper():
                    kind = "airport"
                stamp = datetime.fromtimestamp(float(stamps[i]), timezone.utc)
                if kind == "airport" and not 50 <= stamp.minute <= 59:
                    continue
                network = road["network"] if road else "MN_RWIS" if re.fullmatch(r"MN\d{3}", station) else provider
                row = {"id": f"{network}:{station}", "station": station, "name": road["name"] if road else name,
                       "network": network, "provider": provider, "kind": kind,
                       "lat": float(lats[i]), "lon": float(lons[i]),
                       "time": iso(stamp),
                       "qc": {}, "derived": []}
                for source, (target, units, low, high) in FIELDS.items():
                    row[target] = None
                    if source not in v:
                        continue
                    field = v[source]
                    raw = float(field[i])
                    descriptor = text(v[source+"DD"][i]) if source+"DD" in v else "Z"
                    qca = int(v[source+"QCA"][i]) if source+"QCA" in v else 0
                    qcr = int(v[source+"QCR"][i]) if source+"QCR" in v else None
                    icr = int(v[source+"ICR"][i]) if source+"ICR" in v else 0
                    row["qc"][target] = {"descriptor": descriptor, "applied": qca, "failed": qcr,
                        "accepted": descriptor in {"C", "S", "V"} and qca > 0 and qcr == 0 and icr == 0}
                    if raw in (getattr(field, "_FillValue", None), getattr(field, "missing_value", None)):
                        row["qc"][target]["accepted"] = False
                        continue
                    value = raw-273.15 if units == "kelvin" else raw
                    value = number(value, low, high)
                    if value is None or not row["qc"][target]["accepted"]:
                        row["qc"][target]["accepted"] = False
                        continue
                    row[target] = round(value*9/5+32 if units == "kelvin" else value*2.2369362921 if units == "meter/sec" else value, 3)
                finish(row)
                key = row["id"]
                rank = (abs((stamp-(hour-timedelta(minutes=7))).total_seconds()),-field_count(row)) if kind == "airport" else (-stamp.timestamp(),-field_count(row))
                old = rows.get(key)
                old_stamp = datetime.fromisoformat(old["time"].replace("Z", "+00:00")) if old else None
                old_rank = (abs((old_stamp-(hour-timedelta(minutes=7))).total_seconds()),-field_count(old)) if old and kind == "airport" else (-old_stamp.timestamp(),-field_count(old)) if old else None
                if old_rank is None or rank < old_rank:
                    rows[key] = row
        finally:
            del v, field
    return list(rows.values())


def finish(row):
    t, d, rh = row.get("tempF"), row.get("dewpointF"), row.get("rh")
    invalid_dew = False
    if t is not None and d is not None and d > t+.9:
        invalid_dew = True
        row["dewpointF"] = d = None
        row["qc"]["dewpointF"]["accepted"] = False
        row["qc"]["dewpointF"]["reason"] = "Dew point exceeds air temperature"
    if not invalid_dew and d is None and t is not None and rh is not None and 0 < rh <= 100 and row["qc"].get("dewpointF", {}).get("descriptor", "Z") in {"Z", "LOCAL", "METAR"}:
        c = (t-32)*5/9
        gamma = math.log(rh/100)+17.625*c/(243.04+c)
        d = (243.04*gamma/(17.625-gamma))*9/5+32
        row["dewpointF"] = round(d, 3)
        row["derived"].append("dewpointF")
        row["qc"]["dewpointF"] = combined_qc(row, "tempF", "rh")
    if rh is None and t is not None and d is not None and row["qc"].get("rh", {}).get("descriptor", "Z") in {"Z", "LOCAL", "METAR"}:
        c, dc = (t-32)*5/9, (d-32)*5/9
        row["rh"] = round(min(100,100*math.exp(17.625*dc/(243.04+dc)-17.625*c/(243.04+c))), 3)
        row["derived"].append("rh")
        row["qc"]["rh"] = combined_qc(row, "tempF", "dewpointF")
    row["spreadF"] = round(max(0,t-d),3) if t is not None and d is not None else None
    if row["spreadF"] is not None:
        row["qc"]["spreadF"] = combined_qc(row,"tempF","dewpointF")
    speed, direction = row.get("windMph"), row.get("direction")
    if speed is not None and speed < .5:
        row["uMph"], row["vMph"] = 0., 0.
        row["qc"]["vector"] = row["qc"].get("windMph", {})
    elif speed is not None and direction is not None:
        row["uMph"] = round(-speed*math.sin(math.radians(direction)), 4)
        row["vMph"] = round(-speed*math.cos(math.radians(direction)), 4)
        row["qc"]["vector"] = combined_qc(row,"windMph","direction")
    else:
        row["uMph"], row["vMph"] = None, None
    return row


def combined_qc(row, *keys):
    entries = [row["qc"].get(k, {}) for k in keys]
    order = {"LOCAL":0,"METAR":1,"C":2,"S":3,"V":4}
    desc = min((q.get("descriptor", "Z") for q in entries), key=lambda d:order.get(d,-1))
    return {"descriptor":desc,"accepted":all(q.get("accepted",False) for q in entries),"derived":True}


def field_count(row):
    return sum(row.get(k) is not None for k in ("tempF","dewpointF","rh","windMph","gustMph"))


def road_rows(document, hour):
    rows, metadata = [], {}
    for item in document.get("data", []):
        station, network = item.get("station", ""), item.get("network", "")
        if not network.endswith("_RWIS") or not in_region(item.get("lat"), item.get("lon")):
            continue
        metadata[station] = {"network":network,"name":item.get("name",station),"lat":item["lat"],"lon":item["lon"]}
        try:
            stamp = datetime.fromisoformat(item["utc_valid"].replace("Z", "+00:00"))
            if stamp.tzinfo is None or not hour-timedelta(minutes=30) <= stamp <= hour:
                continue
        except (KeyError, ValueError):
            continue
        row = {"id":f"{network}:{station}","station":station,"name":item.get("name",station),
               "network":network,"provider":"IEM RWIS","kind":"road","lat":item["lat"],"lon":item["lon"],
               "time":iso(stamp),"qc":{},"derived":[]}
        for key, source, low, high, factor in (("tempF","tmpf",-76,131,1),("dewpointF","dwpf",-94,104,1),
                ("rh","relh",0,100,1),("windMph","sknt",0,250,1.150779448),
                ("direction","drct",0,360,1),("gustMph","gust",0,287,1.150779448)):
            value = number(item.get(source), low, high)
            row[key] = round(value*factor,3) if value is not None else None
            row["qc"][key] = {"descriptor":"LOCAL","accepted":value is not None,
                "reason":"Range/consistency checked here; upstream MADIS QC flags unavailable in IEM fallback"}
        finish(row)
        if field_count(row):
            rows.append(row)
    return rows, metadata


def airport_rows(snapshot, hour):
    frame = next((h for h in (snapshot or {}).get("history", []) if h["hour"] == iso(hour)), {})
    rows = []
    for item in frame.get("stations", []):
        if item["station"] in EXCLUDED:
            continue
        wind = item.get("wind", {})
        row = {"id":"METAR:"+item["station"],"station":item["station"],"name":item["station"],
               "kind":"airport","network":"METAR","provider":"NOAA AWC routine METAR",
               "lat":item["lat"],"lon":item["lon"],"time":item["time"],"qc":{},"derived":[],
               "tempF":number(item.get("tempF"),-76,131),"dewpointF":number(item.get("dewpointF"),-94,104),
               "windMph":number(wind.get("speedMph"),0,287),"direction":number(wind.get("direction"),0,360),
               "gustMph":None,"rh":None,"variable":bool(wind.get("variable"))}
        for key in ("tempF","dewpointF","windMph","direction","gustMph","rh"):
            row["qc"][key] = {"descriptor":"METAR","accepted":row[key] is not None,
                              "reason":"Official routine METAR; local range/consistency checks, not MADIS verified"}
        finish(row)
        rows.append(row)
    return rows


def wisconet_rows(document, hour):
    if document.get("type") != "FeatureCollection":
        raise ValueError("Unexpected Wisconet response")
    rows = []
    for feature in document.get("features", []):
        properties = feature.get("properties", {})
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if len(coordinates) < 2 or not in_region(coordinates[1],coordinates[0]):
            continue
        station = properties.get("station_id", "")
        if not re.fullmatch(r"[A-Z0-9]{1,12}",station):
            continue
        timed = {}
        for source, (key, unit, low, high) in WISCONET_FIELDS.items():
            field = properties.get(source, {})
            if field.get("unitCode") != unit:
                continue
            for observation in field.get("observations", []):
                try:
                    stamp = datetime.fromisoformat(observation["timestamp"].replace("Z","+00:00"))
                    if stamp.tzinfo is None or not hour-timedelta(minutes=30) <= stamp <= hour:
                        continue
                except (KeyError, ValueError):
                    continue
                label = iso(stamp.astimezone(timezone.utc))
                row = timed.setdefault(label,{"id":"WISCONET:"+station,"station":station,
                    "name":properties.get("station_name",station),"network":"WISCONET","provider":"University of Wisconsin Wisconet",
                    "madisId":properties.get("madis_id"),"kind":"mesonet","lat":coordinates[1],"lon":coordinates[0],
                    "time":label,"qc":{},"derived":[],**{k[0]:None for k in WISCONET_FIELDS.values()}})
                flag = observation.get("qualityControl")
                accepted = flag in (None,"Z","C","S","V","G")
                value = number(observation.get("value"),low,high) if accepted else None
                row[key] = value
                row["qc"][key] = {"descriptor":"LOCAL" if accepted else "Q","accepted":value is not None,
                    "upstream":flag,"reason":"Wisconet source flag plus local checks; not MADIS verified"}
                if key == "dewpointF" and value is not None:
                    row["derived"].append(key)
        if timed:
            row = finish(timed[max(timed)])
            if field_count(row):
                rows.append(row)
    return rows


def merge(madis, roads, airports, extra=None):
    # IEM is a fallback for a physical road site, not a second vote. Keep
    # MADIS records even when a variable failed; don't silently refill that
    # failed variable with its unflagged IEM copy.
    rows = {row["id"]:row for row in roads}
    rows.update({row["id"]:row for row in madis})
    airport_ids = {row["station"] for row in airports}
    for key, row in list(rows.items()):
        if row["station"] in airport_ids:
            del rows[key]
    rows.update({row["id"]:row for row in airports})
    for row in extra or []:
        # Wisconet publishes its MADIS ID, allowing a real identity match.
        # Prefer the flagged MADIS record, including its rejected variables.
        aliases = {row["station"],row.get("madisId")}-{None}
        if any(r["station"] in aliases and abs(r["lat"]-row["lat"])<.01 and abs(r["lon"]-row["lon"])<.01 for r in rows.values()):
            continue
        rows[row["id"]] = row
    # Same provider/site can appear through an aggregator with a second ID.
    # Identical coordinates within the same network collapse, not distinct
    # nearby stations or fronts. Airport identity remains authoritative.
    unique = {}
    for row in sorted(rows.values(),key=lambda r:(r["kind"] != "airport",-field_count(r),r["id"])):
        if row["station"] in EXCLUDED or not in_region(row["lat"],row["lon"]):
            continue
        key = (row["network"],round(row["lat"],4),round(row["lon"],4))
        unique.setdefault(key,row)
    return sorted(unique.values(), key=lambda r:r["id"])


def download_madis(hour, road_sites):
    url = MADIS_URL+(hour-timedelta(hours=1)).strftime("%Y%m%d_%H00.gz")
    req = Request(url,headers={"User-Agent":"Weather-Lab (https://github.com/Barometer32/weather-lab)"})
    with urlopen(req,timeout=45) as response, gzip.GzipFile(fileobj=response) as stream, tempfile.NamedTemporaryFile() as file:
        expanded = 0
        while True:
            chunk = stream.read(1024*1024)
            if not chunk:
                break
            expanded += len(chunk)
            if expanded > 700_000_000:
                raise ValueError("MADIS mesonet file exceeds expected size")
            file.write(chunk)
        file.flush()
        return read_madis(file.name,hour,road_sites)


def collect(store, now, download, madis_loader=None):
    hour = now.replace(minute=0,second=0,microsecond=0)
    previous = store.read_json("live/surface.json") or {}
    if previous.get("version") == VERSION and previous.get("completedHour") == iso(hour):
        return {"status":"already prepared for this hour"}
    errors, roads, metadata, madis, wisconet = [], [], {}, [], []
    try:
        roads, metadata = road_rows(json.loads(download(RWIS_URL+"?"+urlencode({"valid":iso(hour)}))),hour)
    except Exception:
        logging.getLogger(__name__).exception("IEM RWIS collection failed")
        errors.append("IEM RWIS unavailable")
    try:
        madis = (madis_loader or download_madis)(hour,metadata)
    except Exception:
        logging.getLogger(__name__).exception("MADIS surface collection failed")
        errors.append("Public MADIS mesonet unavailable")
    try:
        url = WISCONET_URL+"?"+urlencode({"date":iso(hour),"fieldlist":",".join(WISCONET_FIELDS)})
        wisconet = wisconet_rows(json.loads(download(url)),hour)
    except Exception:
        logging.getLogger(__name__).exception("Wisconet surface collection failed")
        errors.append("Wisconet unavailable")
    airports = airport_rows(store.read_json("live/metar-clouds.json"),hour)
    stations = merge(madis,roads,airports,wisconet)
    if not any(field_count(row) for row in stations):
        raise ValueError("No usable surface reports; previous prepared data retained")
    counts = dict(Counter(row["kind"] for row in stations))
    fields = {key:sum(row.get(key) is not None for row in stations)
              for key in ("tempF","dewpointF","rh","windMph","gustMph","spreadF")}
    payload = {"version":VERSION,"hour":iso(hour),"checkedAt":iso(now),"bounds":BOUNDS,
               "stations":stations,"counts":counts,"fieldCounts":fields,"sourceErrors":errors,
               "networks":dict(Counter(row["network"] for row in stations)),
               "windowMinutes":30,"sources":["NOAA public MADIS mesonet","IEM RWIS","Wisconet public API","Saved routine AWC METARs"]}
    encoded = json.dumps(payload,separators=(",",":"),allow_nan=False).encode()
    key = "surface/v1/"+hour.strftime("%Y%m%d%H")+"-"+sha256(encoded).hexdigest()[:12]+".json"
    store.write(key,encoded,"application/json")
    frame = {"hour":iso(hour),"url":"/api/prepared/"+key,"counts":counts,"fieldCounts":fields,"sourceErrors":errors}
    retained = {f["hour"]:f for f in previous.get("history",[]) if f.get("url")}
    retained[iso(hour)] = frame
    history = [retained.get(iso(hour-timedelta(hours=i)),{"hour":iso(hour-timedelta(hours=i)),"url":None})
               for i in reversed(range(12))]
    manifest = {"version":VERSION,"checkedAt":iso(now),"bounds":BOUNDS,"history":history,
                "completedHour":iso(hour) if not errors else None,"sourceErrors":errors,
                "scheduleMinute":10,"windowMinutes":30}
    store.write_json("live/surface.json",manifest)
    return {"stations":len(stations),"counts":counts,"fieldCounts":fields,"sourceErrors":errors}
