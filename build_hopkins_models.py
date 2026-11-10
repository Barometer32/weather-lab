"""Build a single Hopkins model experiment with public NOAA GRIB data.

Requires eccodes and requests. No model downloads happen in the web app.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import lru_cache
import hashlib
import os
import json
import math
from pathlib import Path
import re
import tempfile
import threading
import time

import eccodes as ec
import requests

LAT, LON = 44.9244, -93.414
LEVELS = (1000, 975, 950, 925, 900, 875, 850, 800, 750, 700, 650,
          600, 550, 500, 450, 400, 350, 300, 250, 200, 150)
S3 = "https://noaa-rrfs-ops-pds.s3.amazonaws.com/"
MODELS = ("RAP", "HRRR", "RRFS")
LOCAL = threading.local()
GRIDS = {}


def request(url, *, params=None, byte_range=None, as_path=False):
    cache_dir = os.environ.get("HOPKINS_GRIB_CACHE")
    cache = None
    if cache_dir:
        name = hashlib.sha256(repr((url, params, byte_range)).encode()).hexdigest()
        cache = Path(cache_dir) / name
        if cache.is_file():
            return cache if as_path else cache.read_bytes()
    if not hasattr(LOCAL, "session"):
        LOCAL.session = requests.Session()
    for attempt in range(3):
        try:
            headers = {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"} if byte_range else {}
            with LOCAL.session.get(url, params=params, headers=headers, timeout=(12, 35), stream=True) as r:
                r.raise_for_status()
                if byte_range and (r.status_code != 206 or not r.headers.get("Content-Range", "").startswith(
                        f"bytes {byte_range[0]}-{byte_range[1]}/")):
                    raise ValueError("Server did not honor the GRIB byte range")
                body = r.content
                if cache and (body.startswith(b"GRIB") or url.endswith(".idx")):
                    cache.write_bytes(body)
                if as_path:
                    if cache is None or not body.startswith(b"GRIB"):
                        raise ValueError(f"Missing GRIB data from {url}")
                    return cache
                return body
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def nearest_messages(raw):
    if not raw.startswith(b"GRIB"):
        raise ValueError(f"Expected GRIB data: {raw[:160]!r}")
    # ecCodes' file interface requires a file descriptor. Each byte range holds
    # one or more whole GRIB messages, so decode from each message directly.
    cursor = 0
    while cursor < len(raw):
        if raw[cursor:cursor + 4] != b"GRIB":
            raise ValueError("Invalid GRIB message boundary")
        size = int.from_bytes(raw[cursor + 8:cursor + 16], "big")
        if size < 20 or cursor + size > len(raw):
            raise ValueError("Truncated GRIB message")
        g = ec.codes_new_from_message(raw[cursor:cursor + size])
        cursor += size
        try:
            get = lambda key: ec.codes_get(g, key)
            grid_id = get("md5GridSection")
            point = GRIDS.get(grid_id)
            if point is None:
                point = ec.codes_grib_find_nearest(g, LAT, LON % 360)[0]
                GRIDS[grid_id] = point
            value = float(ec.codes_get_values(g)[point["index"]])
            if not math.isfinite(value) or value == 9999 or value >= 1e10:
                continue
            short = get("shortName")
            angle = 0.0
            if short in ("10u", "10v") and get("uvRelativeToGrid"):
                angle = grid_angle(get("gridType"), get("LoVInDegrees"),
                                   get("Latin1InDegrees"), get("Latin2InDegrees"),
                                   point["lat"], point["lon"])
            yield (short, get("typeOfLevel"), get("level"), get("startStep"),
                   get("endStep"), value, angle)
        finally:
            ec.codes_release(g)


@lru_cache(maxsize=32)
def grid_angle(grid, lov, lat1, lat2, lat, lon):
    if grid != "lambert":
        raise ValueError(f"Unexpected grid-relative wind projection {grid}")
    a, b = map(math.radians, (lat1, lat2))
    cone = math.sin(a) if abs(a-b) < 1e-10 else (
        math.log(math.cos(a)/math.cos(b)) /
        math.log(math.tan(math.pi/4+b/2)/math.tan(math.pi/4+a/2)))
    delta = (lon-lov+180)%360-180
    return cone*math.radians(delta)


def base(cycle):
    return cycle.strftime("%Y%m%d"), cycle.strftime("%H")


def nomads_file(model, cycle, lead):
    day, h = base(cycle)
    common = dict(subregion="", leftlon=-93.75, rightlon=-93.1, toplat=45.2, bottomlat=44.65)
    surface = dict(var_TMP="on", var_DPT="on", var_UGRD="on", var_VGRD="on",
                   var_APCP="on", var_PRES="on", lev_surface="on",
                   lev_2_m_above_ground="on", lev_10_m_above_ground="on")
    profile = dict(var_TMP="on", var_RH="on", **{f"lev_{p}_mb": "on" for p in LEVELS})
    if model == "RAP":
        url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_rap.pl"
        args = dict(dir=f"/rap.{day}", file=f"rap.t{h}z.awp130pgrbf{lead:02d}.grib2")
        return request(url, params={**common, **surface, **profile, **args}, as_path=True)
    a = dict(dir=f"/hrrr.{day}/conus")
    url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_"
    return request(url + "2d.pl", params={**common, **surface, **a, "file": f"hrrr.t{h}z.wrfsfcf{lead:02d}.grib2"}, as_path=True)


@lru_cache(maxsize=80)
def file_index(model, cycle, lead, profile):
    day, h = base(cycle)
    if model == "HRRR":
        url = f"https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.{day}/conus/hrrr.t{h}z.wrfprsf{lead:02d}.grib2"
    else:
        product = "prslev.3km" if profile else "2dfld.3km.subh"
        url = f"{S3}rrfs.{day}/{h}/rrfs.t{h}z.{product}.f{lead:03d}.conus.grib2"
    rows = [x.split(":") for x in request(url + ".idx").decode().splitlines()]
    return url, [(int(x[1]), int(rows[i+1][1])-1 if i+1 < len(rows) else None, x[3], x[4], x[5])
                 for i,x in enumerate(rows)]


def grib_ranges(model, cycle, lead, profile):
    url, entries = file_index(model, cycle, lead, profile)
    groups = []
    for start, end, var, level, valid in entries:
        if profile:
            match = re.fullmatch(r"(\d+) mb", level)
            wanted = match and int(match[1]) in LEVELS and var in ("TMP", "RH")
        else:
            wanted = ((var in ("TMP", "DPT") and level == "2 m above ground") or
                      (var in ("UGRD", "VGRD") and level == "10 m above ground") or
                      (var in ("APCP", "PRES") and level == "surface"))
            wanted = wanted and (valid == f"{lead} hour fcst" or
                                 valid in (f"{lead-1}-{lead} hour acc fcst", f"0-{lead} hour acc fcst"))
        if wanted:
            if end is None:
                raise ValueError(f"Unbounded GRIB message in {url}")
            if groups and start == groups[-1][2] + 1:
                groups[-1] = (url, groups[-1][1], end)
            else:
                groups.append((url, start, end))
    return groups


def range_file(item):
    url, start, end = item
    return request(url, byte_range=(start, end), as_path=True)


def sat(t, ice=False):
    a, b = (22.46, 272.62) if ice else (17.62, 243.12)
    return 6.112 * math.exp(a*t/(b+t))


def cloud_bands(temps, rhs, pressure):
    bands = [[], [], []]
    for p in LEVELS:
        if p > pressure:
            continue
        if p not in temps or p not in rhs:
            continue
        t = temps[p] - 273.15
        # Mixed-phase saturation transitions gradually. Same rule for all models.
        weight = min(1, max(0, -t/38))
        eff = rhs[p]/100 * sat(t) / ((1-weight)*sat(t) + weight*sat(t, True))
        band = 0 if p >= 642 else 1 if p >= 350 else 2
        critical = (.82, .78, .75)[band]  # provisional, not calibrated locally
        cover = 1 - math.sqrt(max(0, 1-eff)/(1-critical))
        bands[band].append(max(0, min(1, cover)))
    if any(len(band) < 3 for band in bands):
        raise ValueError("Incomplete vertical temperature and humidity profile")
    return [max(band) for band in bands]


def point_surface(messages, lead):
    d = {(n, typ, z): (v, angle) for n, typ, z, s, e, v, angle in messages if e == lead and s == lead}
    u, angle = d["10u", "heightAboveGround", 10]
    v, other = d["10v", "heightAboveGround", 10]
    if angle != other:
        raise ValueError("Inconsistent wind grid")
    return (d["2t", "heightAboveGround", 2][0], d["2d", "heightAboveGround", 2][0],
            u*math.cos(angle)+v*math.sin(angle), -u*math.sin(angle)+v*math.cos(angle),
            d["sp", "surface", 0][0]/100)


def profile_values(messages, lead, pressure):
    vals = {"t": {}, "r": {}}
    for n, typ, p, s, e, v, angle in messages:
        if n in vals and typ == "isobaricInhPa" and s == e == lead:
            vals[n][p] = v
    return cloud_bands(vals["t"], vals["r"], pressure)


def precip(messages, lead, prev):
    def find(msg, start, end):
        for n, typ, _, s, e, v, _ in msg:
            if n in ("tp", "unknown") and typ == "surface" and (s,e) == (start,end):
                return v
    direct = find(messages, lead-1, lead)
    if direct is not None:
        return direct
    after, before = find(messages, 0, lead), find(prev, 0, lead-1)
    if after is None or before is None:
        raise ValueError(f"Missing precipitation for interval {lead-1}–{lead}")
    if after < before-0.05:
        raise ValueError("Unexpected precipitation accumulation reset")
    return max(0, after-before)


def build_staged(cycle, cloud_cycle):
    tasks = {}
    with ThreadPoolExecutor(max_workers=8) as headers, ThreadPoolExecutor(max_workers=12) as data:
        for lead in range(3, 19):
            for model in MODELS[:2]:
                tasks[model, lead] = data.submit(nomads_file, model, cycle, lead)
            tasks["RRFS", lead] = headers.submit(grib_ranges, "RRFS", cycle, lead, False)
            if lead < 18:
                f = lead + int((cycle-cloud_cycle).total_seconds()/3600)
                tasks["RRFS-profile", lead] = headers.submit(grib_ranges, "RRFS", cloud_cycle, f, True)
                tasks["HRRR-profile", lead] = headers.submit(grib_ranges, "HRRR", cycle, lead, True)
        ranges = {}
        for key, task in tasks.items():
            if key[0] in ("RRFS", "RRFS-profile", "HRRR-profile"):
                specs = task.result()
                if not specs:
                    raise ValueError(f"No GRIB records for {key}")
                ranges[key] = [data.submit(range_file, spec) for spec in specs]
        def get(k):
            # Keep the ecCodes library on the main thread; download workers only
            # stage files on disk, so hundreds of grid fields never build up in RAM.
            files = ranges[k] if k in ranges else [tasks[k]]
            return [record for task in files for record in nearest_messages(task.result().read_bytes())]
        values = {(m,f): get((m,f)) for m in MODELS for f in range(3,19)}
        profiles = {(m,f): get((m+"-profile",f)) for m in ("HRRR","RRFS") for f in range(3,18)}
    rows = []
    for lead in range(3, 18):
        parts = {}
        for m in MODELS:
            records = values[m,lead]
            t,d,u,v,p = point_surface(records, lead)
            pf = lead + int((cycle-cloud_cycle).total_seconds()/3600) if m == "RRFS" else lead
            clouds = profile_values(profiles.get((m,lead), records), pf, p)
            rain = precip(values[m,lead+1], lead+1, records)
            parts[m] = dict(tempF=(t-273.15)*1.8+32, dewF=(d-273.15)*1.8+32,
                            u=u, v=v, precipIn=rain/25.4,
                            low=100*clouds[0], mid=100*clouds[1], high=100*clouds[2])
        avg = {k: sum(v[k] for v in parts.values())/3 for k in parts["RAP"]}
        def finish(v):
            u, n = v.pop("u"), v.pop("v")
            mph = math.hypot(u,n)*2.236936
            return {**{k:round(x,4) for k,x in v.items()}, "windMph":round(mph,2),
                    "windDegrees": round(math.degrees(math.atan2(-u,-n))%360,1)%360 if mph >= 0.5 else None}
        valid = cycle+timedelta(hours=lead)
        rows.append(dict(valid=valid.isoformat(), precipEnds=(valid+timedelta(hours=1)).isoformat(),
                         blend=finish(avg), models={m:finish(v) for m,v in parts.items()}))
    return dict(location="Hopkins, MN", latitude=LAT, longitude=LON, run=cycle.isoformat(),
                rrfsCloudRun=cloud_cycle.isoformat(), rows=rows)


def build(cycle, cloud_cycle):
    if os.environ.get("HOPKINS_GRIB_CACHE"):
        Path(os.environ["HOPKINS_GRIB_CACHE"]).mkdir(parents=True, exist_ok=True)
        return build_staged(cycle, cloud_cycle)
    with tempfile.TemporaryDirectory(prefix="hopkins-grib-") as directory:
        os.environ["HOPKINS_GRIB_CACHE"] = directory
        try:
            return build_staged(cycle, cloud_cycle)
        finally:
            del os.environ["HOPKINS_GRIB_CACHE"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", required=True, type=datetime.fromisoformat)
    p.add_argument("--rrfs-cloud-run", required=True, type=datetime.fromisoformat)
    p.add_argument("--output", type=Path, default=Path("static/hopkins-models.json"))
    args = p.parse_args()
    if args.run.utcoffset() != timedelta(0) or args.rrfs_cloud_run.utcoffset() != timedelta(0):
        p.error("Supply UTC cycle timestamps")
    result = build(args.run, args.rrfs_cloud_run)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
