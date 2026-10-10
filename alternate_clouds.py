"""Local, north-up GOES cloud products, independent of the COD RGB viewer."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import re
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image

UTC = timezone.utc
BASE = "https://noaa-goes19.s3.amazonaws.com/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
# A north-up rectangle matching the region of the original COD S_Minnesota
# graticule, rather than its tilted image-coordinate footprint.
BOUNDS = [[43.3, -98.85], [46.9, -89.85]]
WIDTH, HEIGHT = 1024, 576
VERSION = "local-clouds-v1"
PRODUCTS = {
    "combined": {"label": "Cloud tops · all heights", "description": "One day/night view: blue low tops, teal middle tops, purple high tops. Gray clouds have no trusted height estimate. Tops are above sea level, not airport cloud bases."},
    "optical": {"label": "Optical thickness", "description": "Lighter blue means lower optical depth; darker blue means higher optical depth. Gray hatching means no trusted estimate. Nighttime sensitivity is limited; optical depth is not cloud depth in feet."},
}
FEEDS = {"mask": "ABI-L2-ACMC", "height": "ABI-L2-ACHAC", "optical": "ABI-L2-CODC"}
DECODE_LOCK = threading.Lock()  # netCDF/HDF5 libraries are not thread safe.
FRAME_LOCK = threading.Lock()
FRAME_CACHE = {}


def iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


def stamp_time(stamp):
    if not re.fullmatch(r"\d{14}", stamp):
        raise ValueError("Invalid GOES scan identifier")
    moment = datetime.strptime(stamp[:13], "%Y%j%H%M%S").replace(tzinfo=UTC, microsecond=int(stamp[13])*100000)
    if moment.strftime("%Y%j%H%M%S") != stamp[:13]:
        raise ValueError("Invalid GOES scan date")
    return moment


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "Weather-Lab (https://github.com/Barometer32/weather-lab)"}), timeout=20) as response:
        data = response.read(16_000_001)
        expected = response.headers.get("Content-Length")
        if expected is not None and len(data) != int(expected):
            raise ValueError("Incomplete GOES download")
    if len(data) > 16_000_000:
        raise ValueError("GOES object exceeds download limit")
    return data


def list_hour(feed, hour, now):
    root = ET.fromstring(fetch(BASE+"?"+urlencode({"list-type":"2", "prefix":f"{feed}/{hour:%Y/%j/%H}/", "max-keys":1000})))
    if root.findtext("s:IsTruncated", namespaces=NS) == "true":
        raise ValueError("Unexpected GOES listing size")
    rows = {}
    pattern = re.compile(re.escape(feed)+r"/\d{4}/\d{3}/\d{2}/OR_"+re.escape(feed)+r"-M\d_G19_s(\d{14})_e\d{14}_c\d{14}\.nc$")
    for item in root.findall("s:Contents", NS):
        key = item.findtext("s:Key", "", NS)
        match = pattern.fullmatch(key)
        if not match:
            continue
        try:
            moment = stamp_time(match[1])
        except ValueError:
            continue
        if now-timedelta(hours=2) <= moment <= now:
            rows[match[1]] = key  # Last published revision of a scan.
    return rows


def scans(now):
    hours = [now.replace(minute=0, second=0, microsecond=0)-timedelta(hours=i) for i in range(3)]
    work = [(name, feed, hour) for name, feed in FEEDS.items() for hour in hours]
    def read(job):
        name, feed, hour = job
        try:
            return name, list_hour(feed, hour, now)
        except Exception:
            # Optional fields can be absent. Missing mask hours become gaps.
            return name, {}
    joined = {name:{} for name in FEEDS}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name, rows in pool.map(read, work):
            joined[name].update(rows)
    if not joined["mask"]:
        raise ValueError("No recent NOAA cloud masks are available")
    return [{"id":stamp, "time":iso(stamp_time(stamp)), "keys":{name:rows.get(stamp) for name,rows in joined.items()}}
            for stamp in sorted(joined["mask"])]


def manifest(rows, now):
    frames = [{"id":r["id"], "time":r["time"], "url":f"/api/alternate-clouds/frame/{r['id']}/combined.png?v={revision(r)}"}
              for r in rows if now-timedelta(hours=2) <= stamp_time(r["id"]) <= now]
    if not frames:
        raise ValueError("No recent NOAA cloud masks are available")
    return {"frames":frames, "bounds":BOUNDS, "width":WIDTH, "height":HEIGHT,
            "renderVersion":VERSION, "label":"Local NOAA clouds", "sourceUrl":"https://registry.opendata.aws/noaa-goes/",
            "products":PRODUCTS, "windowStart":iso(now-timedelta(hours=2)), "checkedAt":iso(now)}


def revision(row):
    # Late optional files and corrected source objects create new image URLs.
    return hashlib.sha256("|".join(row["keys"].get(name) or "" for name in FEEDS).encode()).hexdigest()[:12]


def output_grid():
    south, west = BOUNDS[0]; north, east = BOUNDS[1]
    # Uniform Mercator y rows align with Leaflet's geographic image overlays.
    m = lambda lat: np.log(np.tan(np.pi/4+np.radians(lat)/2))
    xs = west+(np.arange(WIDTH)+.5)*(east-west)/WIDTH
    ys = m(north)-(np.arange(HEIGHT)+.5)*(m(north)-m(south))/HEIGHT
    lats = np.degrees(2*np.arctan(np.exp(ys))-np.pi/2)
    return np.meshgrid(xs, lats)


def sample(dataset, field, lon, lat):
    from pyproj import CRS, Transformer
    p = dataset["goes_imager_projection"]
    crs = CRS.from_proj4(f"+proj=geos +h={p.perspective_point_height} +lon_0={p.longitude_of_projection_origin} +a={p.semi_major_axis} +b={p.semi_minor_axis} +sweep={p.sweep_angle_axis}")
    gx, gy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    x, y = np.asarray(dataset["x"][:]), np.asarray(dataset["y"][:])
    if len(x)<2 or len(y)<2:
        raise ValueError("Invalid GOES coordinate grid")
    fx = (gx/p.perspective_point_height-x[0])/(x[1]-x[0])
    fy = (gy/p.perspective_point_height-y[0])/(y[1]-y[0])
    inside = np.isfinite(fx)&np.isfinite(fy)&(fx>=-.5)&(fx<len(x)-.5)&(fy>=-.5)&(fy<len(y)-.5)
    ix = np.clip(np.floor(np.where(inside,fx,0)+.5).astype(int),0,len(x)-1)
    iy = np.clip(np.floor(np.where(inside,fy,0)+.5).astype(int),0,len(y)-1)
    x0,x1,y0,y1 = ix.min(),ix.max(),iy.min(),iy.max()
    values = np.ma.asarray(dataset[field][y0:y1+1,x0:x1+1])[iy-y0,ix-x0]
    result = np.asarray(values.data,dtype=float)
    return result, inside & ~np.ma.getmaskarray(values) & np.isfinite(result)


def palette(mask, mask_ok, heights, height_ok, optical, optical_ok):
    cloudy = mask_ok & np.isin(mask,[2,3])
    yy,xx = np.indices(mask.shape); hatch = (xx+yy)%10<3
    outputs = {}
    for view in PRODUCTS:
        rgba = np.zeros((*mask.shape,4),dtype=np.uint8)
        rgba[~mask_ok&hatch] = [119,127,133,65]  # Missing is never clear.
        if view == "combined":
            valid = cloudy & height_ok
            rgba[valid & (heights<2000)] = [56,118,188,210]
            rgba[valid & (heights>=2000)&(heights<6000)] = [20,150,143,210]
            rgba[valid & (heights>=6000)] = [129,85,179,210]
            rgba[cloudy&~height_ok] = [138,146,153,175]
        else:
            trusted = cloudy & optical_ok
            for low,high,color in [(0,2,[168,213,237,220]),(2,6,[97,173,213,230]),(6,16,[43,119,174,240]),(16,161,[16,66,115,245])]:
                rgba[trusted&(optical>=low)&(optical<high)] = color
            rgba[cloudy&~optical_ok] = [171,179,185,100]
            rgba[cloudy&~optical_ok&hatch] = [119,127,133,160]
        outputs[view] = rgba
    return outputs


def render(blobs):
    from netCDF4 import Dataset
    lon,lat = output_grid(); arrays = {}
    with DECODE_LOCK:
        for name,blob in blobs.items():
            try:
                with Dataset("memory", memory=blob) as d:
                    field = {"mask":"ACM", "height":"HT", "optical":"COD"}[name]
                    data,valid = sample(d,field,lon,lat); q,qvalid = sample(d,"DQF",lon,lat)
                    if name=="mask": valid &= qvalid&(q==0)&np.isin(data,[0,1,2,3])
                    elif name=="height": valid &= qvalid&(q==0)&(data>=0)&(data<=20000)
                    else:
                        # Bits 0/1 identify night/day; all degradation bits must
                        # be zero. Saturated night COD is not trusted thickness.
                        valid &= qvalid&((q==1)|(q==2))&(data>=0)&(data<=160)
                        valid &= ~((q==1)&(data>=16))
                    arrays[name] = data,valid
            except Exception:
                if name=="mask": raise
    empty = (np.zeros(lon.shape),np.zeros(lon.shape,dtype=bool))
    if "mask" not in arrays: raise ValueError("A valid cloud mask is required")
    mask,ok = arrays["mask"]; height,h_ok=arrays.get("height",empty); depth,d_ok=arrays.get("optical",empty)
    images={}
    for view,rgba in palette(mask,ok,height,h_ok,depth,d_ok).items():
        buffer=BytesIO(); Image.fromarray(rgba).save(buffer,format="PNG");images[view]=buffer.getvalue()
    return images


def frame(row, view, now):
    if view not in PRODUCTS: raise ValueError("Unknown cloud view")
    moment=stamp_time(row["id"])
    if not now-timedelta(hours=2) <= moment <= now: raise ValueError("Cloud scan has expired")
    # Only output PNGs persist in memory. Raw CONUS files are released after
    # local sampling. Cache lifetime is bounded by the rolling two-hour window.
    with FRAME_LOCK:
        for stamp in list(FRAME_CACHE):
            if stamp_time(stamp)<now-timedelta(hours=2): del FRAME_CACHE[stamp]
        signature=revision(row)
        entry=FRAME_CACHE.get(row["id"])
        if entry is None or entry["revision"]!=signature:
            def download(item):
                name,key=item
                # A listed file that fails to download must be retried, not
                # cached as a permanent gray estimate under an immutable URL.
                return name,fetch(BASE+key)
            with ThreadPoolExecutor(max_workers=3) as pool:
                blobs={name:blob for name,blob in pool.map(download,[(n,k) for n,k in row["keys"].items() if k]) if blob}
            FRAME_CACHE[row["id"]]={"revision":signature,"images":render(blobs)}
        return FRAME_CACHE[row["id"]]["images"][view]
