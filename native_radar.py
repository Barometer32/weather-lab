"""Native Level II reflectivity, with incremental low-tilt chunk collection."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import json
import logging
import re
import struct
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import numpy as np

UTC = timezone.utc
VERSION = "level2-polar-v2"
SITES = {"KMPX": {"name": "Twin Cities", "center": [44.925, -93.462], "zoom": 8}}
ARCHIVE = "https://unidata-nexrad-level2.s3.amazonaws.com/"
CHUNKS = "https://unidata-nexrad-level2-chunks.s3.amazonaws.com/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
log = logging.getLogger(__name__)
DECODE_LOCK = threading.Lock()


def site_id(value):
    if value not in SITES:
        raise ValueError("Unknown radar site")
    return value


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def fetch(url, header=False):
    headers = {"User-Agent": "Weather-Lab (https://github.com/Barometer32/weather-lab)"}
    if header:
        headers["Range"] = "bytes=0-23"
    with urlopen(Request(url, headers=headers), timeout=15) as response:
        data = response.read(24 if header else 40_000_001)
    if len(data) > 40_000_000:
        raise ValueError("Radar object exceeds download limit")
    return data


def objects(base, prefix):
    rows, token = [], None
    for _ in range(8):
        query = {"list-type": "2", "prefix": prefix, "max-keys": 1000}
        if token:
            query["continuation-token"] = token
        root = ET.fromstring(fetch(base + "?" + urlencode(query)))
        rows.extend({"key": item.find("s:Key", NS).text,
                     "modified": item.find("s:LastModified", NS).text}
                    for item in root.findall("s:Contents", NS))
        if root.find("s:IsTruncated", NS).text != "true":
            return rows
        token = root.find("s:NextContinuationToken", NS).text
    raise ValueError("Unexpected radar listing size")


def archive_volumes(site, now):
    start = now - timedelta(hours=2, minutes=15)
    dates = sorted({start.date(), now.date()})
    rows = []
    for date in dates:
        rows.extend(objects(ARCHIVE, f"{date:%Y/%m/%d}/{site}/"))
    result = []
    for row in rows:
        match = re.search(r"/" + site + r"(\d{8})_(\d{6})_V\d{2}$", row["key"])
        if match:
            stamp = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            if start <= stamp <= now:
                result.append({**row, "time": iso(stamp)})
    return sorted(result, key=lambda row: row["time"])


def packet(metadata, codes):
    head = json.dumps(metadata, separators=(",", ":")).encode()
    return gzip.compress(struct.pack(">I", len(head)) + head + np.asarray(codes, dtype=np.uint8).tobytes(), compresslevel=3, mtime=0)


def unpack(data):
    data = gzip.decompress(data)
    length = struct.unpack(">I", data[:4])[0]
    meta = json.loads(data[4:4+length])
    return meta, np.frombuffer(data[4+length:], dtype=np.uint8).reshape(len(meta["azimuths"]), meta["gates"]).copy()


class Radials(list):
    cuts = None


def cuts_from_plan(plan):
    return {str(i+1): {"angle": cut.el_angle, "waveform": cut.waveform,
                      "supplemental": cut.supplemental_data}
            for i, cut in enumerate(plan.els)} if plan else None


def decode(data, header=True):
    # Lazy import keeps the public serving process lightweight.
    from metpy.io import Level2File
    logging.getLogger("metpy.io.nexrad").setLevel(logging.ERROR)
    class ReflectivityFile(Level2File):
        def _decode_msg31(self, message):
            super()._decode_msg31(message)
            radial = self.sweeps[-1][-1]
            cuts = cuts_from_plan(getattr(self, "vcp_info", None))
            if not low_reflectivity(radial, cuts):
                self.sweeps[-1].pop()
                return
            # Discard other moments as each radial arrives, rather than keeping
            # a complete multi-moment volume in Cloud Run's limited RAM.
            for name in list(radial.moments):
                if name != b"REF":
                    radial.moments.pop(name)
    # Concurrent site/satellite jobs may overlap, but only one large radar
    # volume is decompressed at a time to stay within the 1 GiB service limit.
    with DECODE_LOCK:
        decoded = ReflectivityFile(BytesIO(data), has_volume_header=header)
        rows = Radials(radial for sweep in decoded.sweeps for radial in sweep if hasattr(radial, "moments"))
        plan = getattr(decoded, "vcp_info", None)
        if plan:
            rows.cuts = cuts_from_plan(plan)
        del decoded
        return rows


def low_reflectivity(radial, cuts=None):
    if b"REF" not in radial.moments:
        return False
    cut = (cuts or {}).get(str(getattr(radial.header, "el_num", "")))
    if cut and (cut["angle"] > 0.6 or cut["waveform"] != "Contiguous Surveillance"):
        return False
    if cut:
        lowest = min(info["angle"] for info in cuts.values() if info["waveform"] == "Contiguous Surveillance")
        if cut["angle"] > lowest+0.05:
            return False
    moment, _ = radial.moments[b"REF"]
    # Split-cut Doppler sweeps also contain short-range REF. Keep the original
    # surveillance REF cut, not a second image of the same scan strategy.
    return b"VEL" not in radial.moments or moment.first_gate + moment.num_gates * moment.gate_width >= 400


def consume(radials, site, pending=None, cuts=None):
    """Emit complete surveillance sweeps only; preserve a partial sweep for restart."""
    from metpy.io.nexrad import START_ELEVATION, END_ELEVATION, nexrad_to_datetime
    complete = []
    cuts = cuts or getattr(radials, "cuts", None)
    if pending:
        meta, codes = unpack(base64.b64decode(pending))
        values = list(codes)
    else:
        meta, values = None, []
    for radial in radials:
        hdr = radial.header
        if hdr.stid.decode() != site:
            raise ValueError("Radar station mismatch")
        if not low_reflectivity(radial, cuts):
            if hdr.rad_status & START_ELEVATION:
                meta, values = None, []
            continue
        moment, ref = radial.moments[b"REF"]
        if hdr.rad_status & START_ELEVATION:
            cut = (cuts or {}).get(str(getattr(hdr, "el_num", "")))
            if not cut and not 0.4 <= hdr.el_angle <= 0.8:
                meta, values = None, []
                continue
            nominal = 0.3 if cut and cut["angle"] < 0.4 else 0.5
            stamp = nexrad_to_datetime(hdr.date, hdr.time_ms).replace(tzinfo=UTC)
            vol = radial.vol_consts
            if vol is None:
                raise ValueError("Radar geographic coordinates missing")
            meta = {"site": site, "time": iso(stamp), "endTime": iso(stamp),
                    "id": stamp.strftime("%Y%m%d%H%M%S") + f"{stamp.microsecond//1000:03d}",
                    "latitude": vol.lat, "longitude": vol.lon, "elevation": hdr.el_angle, "nominalElevation": nominal,
                    "gates": moment.num_gates, "firstGateMeters": moment.first_gate*1000,
                    "gateWidthMeters": moment.gate_width*1000, "azimuthSpacing": hdr.az_spacing,
                    "vcp": vol.vcp, "azimuths": [], "rayNumbers": []}
            values = []
        if meta is None:
            continue  # Never publish a sweep whose beginning was missed.
        if (moment.num_gates != meta["gates"] or moment.gate_width*1000 != meta["gateWidthMeters"]
                or hdr.az_num != len(values)+1):
            meta, values = None, []  # A gap or a changing range grid invalidates this sweep.
            continue
        codes = np.zeros(moment.num_gates, dtype=np.uint8)
        visible = np.isfinite(ref) & (ref >= 10)
        codes[visible] = np.clip(np.rint((ref[visible]+32)*2+2), 2, 255).astype(np.uint8)
        values.append(codes)
        meta["azimuths"].append(hdr.az_angle)
        meta["rayNumbers"].append(hdr.az_num)
        meta["endTime"] = iso(nexrad_to_datetime(hdr.date, hdr.time_ms).replace(tzinfo=UTC))
        if hdr.rad_status & END_ELEVATION:
            angles = np.sort(np.asarray(meta["azimuths"]))
            gaps = np.diff(np.r_[angles, angles[0]+360])
            if len(values) >= 350 and max(gaps) <= max(2, hdr.az_spacing*3):
                meta.pop("rayNumbers", None)
                order = np.argsort(meta["azimuths"])
                meta["azimuths"] = angles.tolist()
                complete.append((meta, packet(meta, np.asarray(values)[order])))
            meta, values = None, []
    pending = base64.b64encode(packet(meta, values)).decode() if meta and values else None
    return complete, pending


def manifest(frames, now, site, palette):
    # Keep every available scan in the time window, regardless of scan frequency.
    start = now - timedelta(hours=2)
    frames = [frame for frame in frames if start <= datetime.fromisoformat(frame["time"].replace("Z", "+00:00")) <= now]
    frames.sort(key=lambda frame: frame["time"])
    elevation = min((frame.get("elevationDegrees", 0.5) for frame in frames), default=0.5)
    frames = [frame for frame in frames if frame.get("elevationDegrees", 0.5) == elevation]
    return {"site": site, "siteName": SITES[site]["name"], "center": SITES[site]["center"],
            "zoom": SITES[site]["zoom"], "frames": frames, "palette": palette,
            "renderVersion": VERSION, "windowStart": iso(start), "windowEnd": iso(now),
            "checkedAt": iso(now), "product": "Level II reflectivity", "elevationDegrees": elevation,
            "source": "NOAA/NWS Level II via NSF Unidata public archive and real-time chunks"}


def collect_site(store, now, site, palette, budget=45):
    site_id(site)
    previous = store.read_json(f"live/radar-{site}.json") or {}
    initial = previous.get("renderVersion") != VERSION or not previous.get("frames")
    deadline = time.monotonic() + (max(budget, 120) if initial else budget)
    frames = {frame["id"]: frame for frame in previous.get("frames", [])} if previous.get("renderVersion") == VERSION else {}
    state_key = f"live/radar-state-{site}.json"
    state = store.read_json(state_key) or {}
    if state.get("version") != VERSION:
        state = {"version": VERSION, "archives": [], "streams": {}}
    volumes = archive_volumes(site, now)
    if not volumes:
        raise ValueError("No recent Level II archive volumes; previous radar retained")
    recent_keys = {row["key"] for row in volumes}
    state["archives"] = [key for key in state["archives"] if key in recent_keys]
    # A 24-byte range request supplies the volume sequence, avoiding an entire
    # completed volume download merely to locate the current streaming directory.
    head = fetch(ARCHIVE + volumes[-1]["key"], header=True)
    if not head.startswith(b"AR2V") or head[20:24].decode() != site:
        raise ValueError("Unexpected native volume header")
    anchor = int(head[9:12])
    candidates = {(anchor+i-1) % 999+1 for i in range(5)}
    # Old incomplete stream entries are retried; closed streams are recovered
    # through the completed-volume archive if a chunk was missing.
    candidates.update(int(key) for key in state["streams"])
    with ThreadPoolExecutor(max_workers=5) as pool:
        listings = list(pool.map(lambda num: (num, objects(CHUNKS, f"{site}/{num}/")), sorted(candidates)))
    active = []
    latest_archive_start = datetime.fromisoformat(volumes[-1]["time"].replace("Z", "+00:00"))
    for number, rows in listings:
        rows = [row for row in rows if re.search(r"\d{8}-\d{6}-\d{3}-[SIE]$", row["key"])]
        if rows:
            rows.sort(key=lambda row: row["key"])
            start_text = rows[0]["key"].rsplit("/", 1)[1][:15]
            volume_start = datetime.strptime(start_text, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
            # Once a completed archive object exists, one download replaces
            # potentially hundreds of chunk requests for that old volume.
            if volume_start > latest_archive_start and volume_start >= now-timedelta(minutes=25):
                active.append((number, rows))
    active.sort(key=lambda entry: entry[1][0]["key"].rsplit("/", 1)[1])
    failures = 0

    def publish():
        data = manifest(list(frames.values()), now, site, palette)
        data.update(historyPending=sum(row["key"] not in state["archives"] for row in volumes),
                    collectionErrors=failures)
        if data["frames"]:
            store.write_json(f"live/radar-{site}.json", data)
        store.write_json(state_key, state)

    def save(items):
        for meta, data in items:
            if not now-timedelta(hours=2) <= datetime.fromisoformat(meta["time"].replace("Z", "+00:00")) <= now:
                continue
            if meta["id"] in frames:
                continue
            key = f"radar/{VERSION}/{site}/{meta['id']}.bin"
            store.write(key, data, "application/octet-stream")
            frames[meta["id"]] = {k: meta[k] for k in ("id", "time", "endTime", "gateWidthMeters", "azimuthSpacing", "vcp")}
            frames[meta["id"]]["elevationDegrees"] = meta["nominalElevation"]
            frames[meta["id"]]["url"] = f"/api/prepared/{key}"
            publish()

    # Process the newest volume first so initial history never delays live radar.
    for number, rows in reversed(active):
        cursor = state["streams"].setdefault(str(number), {"first": rows[0]["key"], "sequence": 0, "pending": None})
        if cursor["first"] != rows[0]["key"]:
            cursor = state["streams"][str(number)] = {"first": rows[0]["key"], "sequence": 0, "pending": None}
        remaining = [row for row in rows if int(row["key"].rsplit("/", 1)[1].split("-")[2]) > cursor["sequence"]]
        failed = False
        # Bounded prefetch keeps networking latency out of the scan publication
        # path without downloading an entire backlog after the time budget ends.
        with ThreadPoolExecutor(max_workers=8) as pool:
            for offset in range(0, len(remaining), 8):
                if time.monotonic() >= deadline or failed:
                    break
                batch = remaining[offset:offset+8]
                futures = [pool.submit(fetch, CHUNKS+row["key"]) for row in batch]
                for row, future in zip(batch, futures):
                    seq = int(row["key"].rsplit("/", 1)[1].split("-")[2])
                    if seq != cursor["sequence"]+1:
                        failed = True
                        failures += 1
                        break
                    try:
                        radials = decode(future.result(), row["key"].endswith("-S"))
                        if getattr(radials, "cuts", None):
                            cursor["cuts"] = radials.cuts
                        items, pending = consume(radials, site, cursor["pending"], cursor.get("cuts"))
                        cursor.update(sequence=seq, pending=pending)
                        save(items)
                    except Exception:
                        failed = True
                        failures += 1
                        log.exception("Could not process %s", row["key"])
                        break  # Retry this chunk; never silently skip a sequence.
        publish()
    state["streams"] = {str(number): state["streams"][str(number)] for number, _ in active if str(number) in state["streams"]}
    # The archive fills the two-hour loop and recovers missed streaming chunks.
    for row in reversed(volumes):
        if row["key"] in state["archives"] or time.monotonic() >= deadline:
            continue
        try:
            items, _ = consume(decode(fetch(ARCHIVE+row["key"])), site)
            if not items:
                raise ValueError("No complete base reflectivity sweep in archive volume")
            save(items)
            state["archives"].append(row["key"])
            publish()
        except Exception:
            failures += 1
            log.exception("Could not backfill %s", row["key"])
    publish()
    data = manifest(list(frames.values()), now, site, palette)
    if not data["frames"]:
        raise ValueError("No complete native low-tilt scans prepared")
    return {"frames": len(data["frames"]), "historyPending": len(volumes)-len(state["archives"]), "errors": failures}
