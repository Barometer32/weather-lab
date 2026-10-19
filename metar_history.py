"""NOAA METAR archive reader and one-time twelve-hour history import.

Run in an authenticated environment with WEATHER_DATA_BUCKET set. NOAA caps
queries at 400 reports; recursively split explicit station batches instead of
accepting a truncated archive. Discover regional airport IDs from NOAA station
metadata; bbox queries can omit stations even below the cap. Routine reports
from :45–:59 are selected using the same hourly parser.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import app as weather
import metar_clouds
from realtime import get_store

SOURCE = "NOAA Aviation Weather Center"
ARCHIVE_URL = "https://aviationweather.gov/api/data/metar"
RESULT_LIMIT = 400
STATIONS_URL = "https://aviationweather.gov/data/cache/stations.cache.json.gz"


def regional_station_ids(download):
    raw = download(STATIONS_URL)
    if raw.startswith(b"\x1f\x8b"):
        from io import BytesIO
        with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
            raw = stream.read(30_000_001)
    if len(raw) > 30_000_000:
        raise ValueError("NOAA station metadata exceeds expected size")
    catalog = json.loads(raw)
    # Some reporting airports have an empty siteType list (e.g. K0D8), so do
    # not restrict discovery to metadata with an explicit METAR type flag.
    ids = {row["icaoId"] for row in catalog if row.get("icaoId")
           and metar_clouds.in_region({"station":row["icaoId"],
                                      "lat":row.get("lat"),"lon":row.get("lon")})}
    if not ids:
        raise ValueError("NOAA station metadata has no regional airports")
    return sorted(ids)


def fetch_history(download, now, *, limit=RESULT_LIMIT, pause=time.sleep, interval=0.7,
                  workers=3, cache_dir=None, hours=13):
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from hashlib import sha256
    import threading
    from urllib.error import HTTPError, URLError

    station_ids = regional_station_ids(download)
    end = now.replace(minute=0, second=0, microsecond=0)
    entries, requests = {}, 0
    last_request = None
    rate_lock = threading.Lock()
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get_batch(ids):
        nonlocal requests, last_request
        params = {"ids": ",".join(ids), "format": "xml", "hours": hours,
                  "date": metar_clouds.iso(end)}
        url = ARCHIVE_URL+"?"+urlencode(params)
        cached = cache_dir/(sha256(url.encode()).hexdigest()+'.xml') if cache_dir is not None else None
        if cached is not None and cached.exists():
            xml = cached.read_bytes()
        else:
            for attempt in range(3):
                with rate_lock:
                    if requests >= 255:
                        raise ValueError("NOAA archive request budget exceeded; no live history changed")
                    if last_request is not None:
                        pause(max(0, interval-(time.monotonic()-last_request)))
                    last_request = time.monotonic()
                    requests += 1
                try:
                    xml = download(url)
                    break
                except (TimeoutError, URLError, ConnectionError) as error:
                    if isinstance(error, HTTPError) and error.code not in (429,500,502,503,504):
                        raise
                    if attempt == 2:
                        raise
                    pause(10 if isinstance(error, HTTPError) and error.code == 429 else 2)
            if cached is not None:
                # Cache each successful response so a local retry reuses it.
                cached.write_bytes(xml)
        if not xml:  # NOAA 204: no reports in this station batch
            return [], []
        root = ET.fromstring(xml)
        errors = root.find("errors")
        if errors is not None and (list(errors) or (errors.text or "").strip()):
            raise ValueError("NOAA archive returned an error; no live history changed")
        reports = root.findall(".//METAR")
        if len(reports) >= limit:
            if len(ids) < 2:
                raise ValueError("NOAA archive is capped for one airport; refusing incomplete history")
            middle = len(ids)//2
            return [ids[:middle], ids[middle:]], []
        return [], metar_clouds.parse_reports(xml, end, hours=13)

    # Bbox responses can thin airports without reaching the documented cap.
    # Explicit station batches recover those reports and keep queries bounded.
    queued = [station_ids[i:i+20] for i in range(0,len(station_ids),20)]
    pending = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while queued or pending:
            while queued and len(pending)<workers:
                ids = queued.pop()
                pending.add(pool.submit(get_batch,ids))
            done,pending = wait(pending,return_when=FIRST_COMPLETED)
            for future in done:
                children,rows = future.result()
                queued.extend(children)
                for row in rows:
                    key = (row["station"],row["time"],row.get("rawOb"),row.get("receiptTime"))
                    entries[key] = row
                print(f"NOAA archive: {requests} requests, {len(entries)} distinct reports", flush=True)
    if not entries:
        raise ValueError("No regional historical METARs returned; no live history changed")
    return {"source": SOURCE, "sourceUrl": ARCHIVE_URL,
            "retrievedAt": metar_clouds.iso(now), "targetHour": metar_clouds.iso(end),
            "requests": requests, "reports": list(entries.values())}


def publish_history(archive, store, now):
    """Atomically replace the canonical prepared object with twelve real hours."""
    if archive.get("source") != SOURCE:
        raise ValueError("Only the NOAA AWC archive is accepted")
    target = datetime.fromisoformat(archive["targetHour"].replace("Z", "+00:00"))
    # Read again immediately before publishing, retaining already saved reports.
    previous = store.read_json("live/metar-clouds.json") or {}
    retained = [row for frame in previous.get("history", [])
                for row in frame.get("stations", []) if metar_clouds.in_region(row)]
    rows = [row for row in retained+archive["reports"]
            if datetime.fromisoformat(row["time"].replace("Z", "+00:00")) < target]
    data = metar_clouds.snapshot(rows, target, metar_clouds.iso(now))
    missing = [frame["hour"] for frame in data["history"] if not frame["stations"]]
    if missing:
        raise ValueError("NOAA returned no eligible reports for "+", ".join(missing)
                         +"; saved history was not replaced")
    counts = [{"hour": frame["hour"], "stations": len(frame["stations"])}
              for frame in data["history"]]
    data.update(observationReports=metar_clouds.observation_reports(data),
                collectionMode="official-hourly-archive", hourlyTarget=metar_clouds.iso(target),
                archiveBackfill={"source": SOURCE, "sourceUrl": ARCHIVE_URL,
                                 "completedAt": metar_clouds.iso(now), "hours": counts})
    store.write_json("live/metar-clouds.json", data)
    for frame in counts:
        print(f"{frame['hour']}: {frame['stations']} official airport reports", flush=True)
    return counts


def main():
    now = datetime.now(timezone.utc)
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET must be set")
    print("Downloading the last 12 completed hours of NOAA METARs.", flush=True)
    archive = fetch_history(weather.download, now, cache_dir="/tmp/weather-metar-history-cache")
    print("Validating and publishing all 12 hourly snapshots.", flush=True)
    publish_history(archive, store, datetime.now(timezone.utc))
    print("Twelve-hour METAR backfill completed.", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

