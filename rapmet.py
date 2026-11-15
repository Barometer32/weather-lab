"""Direct NOAA five-minute HF-ASOS plots, with a strict raw HF fallback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

KEY="live/rapmet-v1.json"
VERSION="five-state-direct-hf-celsius-v2"
STATES=frozenset({"ND","SD","IA","MN","WI"})
EXCLUDED=frozenset({"KSTP","KCFE"})
MAX_AGE=3600
UTC=timezone.utc


def iso(t):
    return t.astimezone(UTC).isoformat().replace("+00:00","Z")


@lru_cache(maxsize=1)
def inventory():
    return json.loads((Path(__file__).parent/"static/rapmet-stations.json").read_text())["stations"]


def eligible(row,now):
    try:
        stamp=datetime.fromisoformat(row["time"].replace("Z","+00:00"))
        return (row["station"] in inventory() and row["station"] not in EXCLUDED
                and row.get("state")==inventory()[row["station"]]["state"] and row["state"] in STATES
                and row.get("reportType")=="HFMETAR" and row.get("temperatureBasis") in ("decoded-HF-ASOS-Celsius","main-XX/XX")
                and stamp.minute%5==0 and stamp.second==0 and stamp.microsecond==0
                and 0<=(now-stamp).total_seconds()<=MAX_AGE)
    except (KeyError,TypeError,ValueError):return False


def complete(row):
    return (all(type(row.get(k)) in (int,float) and math.isfinite(row[k]) for k in ("tempC","dewpointC"))
            and -90<=row["tempC"]<=65 and -100<=row["dewpointC"]<=min(row["tempC"],60))


def latest_rows(rows,now):
    latest={}
    for r in rows:
        if eligible(r,now) and r["time"]>=latest.get(r["station"],{}).get("time",""):latest[r["station"]]=r
    return sorted(latest.values(),key=lambda r:r["station"])


def selected(rows,now):
    return [r for r in latest_rows(rows,now) if complete(r)]


def parse_reports(payload,now,*,latest_only=True):
    from five_minute_observations import parse_reports as parse_raw
    rows=[]
    for r in parse_raw(payload,now,stations=set(inventory())):
        station=r["station"];site=inventory()[station]
        rows.append({"station":station,"state":site["state"],"name":site["name"],"lat":site["lat"],"lon":site["lon"],
                     "time":r["time"],"reportType":"HFMETAR","tempC":r["tempC"],"dewpointC":r["dewpointC"],
                     "wind":{"speedMph":r["windSpeedMph"],"direction":r["windDirection"],"variable":r["windVariable"]},
                     "source":"NOAA MADIS five-minute ASOS via Iowa Environmental Mesonet",
                     "temperatureBasis":"main-XX/XX","rawOb":r["rawOb"]})
    return latest_rows(rows,now) if latest_only else [r for r in rows if eligible(r,now)]


def from_madis(payload,now,*,latest_only=True):
    from madis_observations import parse_file
    rows=[]
    for r in parse_file(payload,set(inventory()),now,high_frequency_only=True,allow_advisory_wind=True):
        station=r["icaoId"]
        if station not in inventory() or station in EXCLUDED or r.get("metarType")!="HFMETAR" or r["obsTime"]%300:continue
        site=inventory()[station]
        # parse_file validates Kelvin units and QC, then subtracts 273.15.
        # Two decimal places remove netCDF float noise, not add precision.
        rows.append({"station":station,"state":site["state"],"name":site["name"],"lat":site["lat"],"lon":site["lon"],
                     "time":iso(datetime.fromtimestamp(r["obsTime"],UTC)),"reportType":"HFMETAR",
                     "tempC":round(r["temp"],2) if r["temp"] is not None else None,
                     "dewpointC":round(r["dewp"],2) if r["dewp"] is not None else None,
                     "wind":{"speedMph":r["wspd"]*1852/1609.344 if r.get("wspd") is not None else None,
                             "direction":r.get("wdir"),"variable":False},
                     "source":"NOAA MADIS direct five-minute HF-ASOS","temperatureBasis":"decoded-HF-ASOS-Celsius"})
    return latest_rows(rows,now) if latest_only else [r for r in rows if eligible(r,now)]


def metro_history(previous,fresh,now):
    # A small shared pool allows the average to select the latest exact
    # five-minute time reported by all three, without another NOAA download.
    merged={}
    for r in previous.get("metroReports",previous.get("stations",[]))+fresh:
        if r.get("station") in ("KMSP","KFCM","KMIC") and eligible(r,now):
            merged[r["station"],r["time"]]=r
    return sorted(merged.values(),key=lambda r:(r["time"],r["station"]))


def source_urls(now):
    from five_minute_observations import live_urls
    urls=[]
    for state in sorted(STATES):
        ids=[s["iemId"] for s in inventory().values() if s["state"]==state]
        for start in range(0,len(ids),25):
            urls.append((f"state {state} batch {start//25+1}","https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"+urlencode({
                "network":state+"_ASOS","station":ids[start:start+25],"data":"metar","sts":(now-timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ"),
                "ets":(now+timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%MZ"),"tz":"Etc/UTC","format":"onlycomma",
                "latlon":"no","elev":"no","missing":"M","trace":"T","report_type":"1"},doseq=True),None))
    # The preferred airports also use the smaller live history API. Compare
    # actual report timestamps and retain whichever raw report arrives first.
    urls.extend((station,url,station) for station,url in live_urls(now))
    return urls


def collect(store,now,download=None,raw_download=None):
    from madis_observations import fetch_file,file_url
    download=download or fetch_file
    previous=store.read_json(KEY) or {}
    old=previous.get("stations",[]) if previous.get("version")==VERSION else []
    hour=now.replace(minute=0,second=0,microsecond=0)
    def direct(target):
        try:return from_madis(download(file_url(target)),now,latest_only=False),None
        except HTTPError as e:return [],None if e.code==404 and target==hour else "NOAA HF-ASOS file unavailable"
        except Exception:return [],"NOAA HF-ASOS file unavailable"
    with ThreadPoolExecutor(max_workers=2) as pool:direct_batches=list(pool.map(direct,[hour-timedelta(hours=1),hour]))
    direct_rows=[r for batch,_ in direct_batches for r in batch]
    if direct_rows:
        rows=latest_rows(old+direct_rows,now)
        saved={"version":VERSION,"stations":rows,"checkedAt":iso(now),"sourceFailures":[e for _,e in direct_batches if e],
               "feed":"NOAA direct HF-ASOS","retryAfter":previous.get("retryAfter",0),"metroReports":metro_history(previous,direct_rows,now)}
        store.write_json(KEY,saved)
        return {"stations":len(selected(rows,now)),"newestObservationAt":max(r["time"] for r in rows),"feed":saved["feed"]}
    from app import download as default_download
    download=raw_download or default_download
    retry_until=previous.get("retryAfter",0)
    if retry_until>now.timestamp():
        return {"status":"raw source rate limited","retryAfter":retry_until,"stations":len(selected(old,now))}
    use_pacing=download is default_download
    gate=threading.Lock();pace={"next":0.0,"retryAfter":0}
    def request(url):
        # Avoid bursts against IEM's public service. A 429 stops all remaining
        # requests in this poll and persists its cooldown across scheduled runs.
        with gate:
            if pace["retryAfter"]:raise RuntimeError("Raw source cooling down")
            if use_pacing:
                wait=pace["next"]-time.monotonic()
                if wait>0:time.sleep(wait)
                pace["next"]=time.monotonic()+1.1
        try:return download(url)
        except HTTPError as error:
            if error.code==429:
                value=error.headers.get("Retry-After","") if error.headers else ""
                try:delay=float(value)
                except ValueError:
                    try:delay=parsedate_to_datetime(value).timestamp()-now.timestamp()
                    except (ValueError,TypeError,OverflowError):delay=300
                with gate:pace["retryAfter"]=now.timestamp()+max(300,delay)
            raise
    def read(item):
        label,url,station=item
        try:
            try:payload=request(url)
            except HTTPError as error:
                if error.code not in (500,502,503,504):raise
                payload=request(url)
            except (TimeoutError,URLError):payload=request(url)
            if station:
                # Reuse the strict raw parser via its CSV shape, not the API's
                # numeric/derived temperature fields.
                import csv
                from io import StringIO
                source=json.loads(payload)
                if not isinstance(source.get("data"),list):raise ValueError("Invalid live history")
                stream=StringIO();writer=csv.writer(stream);writer.writerow(["station","valid","metar"])
                for r in source["data"]:writer.writerow([station,r.get("utc_valid"),r.get("raw")])
                payload=stream.getvalue().encode()
            return parse_reports(payload,now,latest_only=False),None
        except Exception:return [],label+" raw feed unavailable"
    with ThreadPoolExecutor(max_workers=4) as pool:batches=list(pool.map(read,source_urls(now)))
    fresh=[r for batch,_ in batches for r in batch]
    rows=latest_rows(old+fresh,now)
    saved={"version":VERSION,"stations":rows,"checkedAt":iso(now),"sourceFailures":[e for _,e in direct_batches+batches if e],
           "retryAfter":pace["retryAfter"],"feed":"raw HF-ASOS fallback","metroReports":metro_history(previous,fresh,now)}
    store.write_json(KEY,saved)
    if not rows:raise ValueError("No five-minute airport reports are available")
    return {"stations":len(selected(rows,now)),"newestObservationAt":max(r["time"] for r in rows),"sourceFailures":saved["sourceFailures"]}


def present(saved,now):
    if not saved or saved.get("version")!=VERSION:raise ValueError("RAPMET is not prepared")
    rows=selected(saved.get("stations",[]),now)
    for r in rows:r["ageMinutes"]=round((now-datetime.fromisoformat(r["time"].replace("Z","+00:00"))).total_seconds()/60,1)
    checked=saved.get("checkedAt")
    delayed=not checked or (now-datetime.fromisoformat(checked.replace("Z","+00:00"))).total_seconds()>600
    return {"version":VERSION,"stations":rows,"states":sorted(STATES),"excludedStations":sorted(EXCLUDED),
            "checkedAt":checked,"serverTime":iso(now),"stale":delayed,"sourceDelayed":any(r["ageMinutes"]>15 for r in rows),
            "newestObservationAt":max((r["time"] for r in rows),default=None),"updateIntervalSeconds":300,
            "temperatureUnit":"C","windUnit":"mph","temperatureBasis":"HF-ASOS-Celsius","feed":saved.get("feed"),
            "sourceFailures":saved.get("sourceFailures",[])}
