"""NOAA METAR archive reader and one-time twelve-hour history import.

Run in an authenticated environment with WEATHER_DATA_BUCKET set. NOAA caps
queries at 400 reports; recursively split explicit station batches instead of
accepting a truncated archive. Discover regional airport IDs from NOAA station
metadata; bbox queries can omit stations even below the cap. Routine reports
from :50–:59 are selected using the same hourly parser.
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

import airport_plots
import app as weather
import metar_clouds
from realtime import get_store

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
    return {"source": airport_plots.SOURCE, "sourceUrl": ARCHIVE_URL,
            "retrievedAt": metar_clouds.iso(now), "targetHour": metar_clouds.iso(end),
            "requests": requests, "reports": list(entries.values())}


def publish_history(archive, store, now):
    if archive.get("source") != airport_plots.SOURCE:
        raise ValueError("Only the NOAA AWC archive is accepted")
    # An update run pauses the hourly job until this import finishes. Re-read
    # genuine saved reports here so existing observations are preserved.
    hour = now.replace(minute=0, second=0, microsecond=0)
    previous_stations = store.read_json("live/station-plots.json") or {}
    rows = archive["reports"]
    rows = [row for row in rows if airport_plots.timestamp(row["time"]) is not None
            and airport_plots.timestamp(row["time"]) <= hour]
    clouds = metar_clouds.snapshot(rows, hour, metar_clouds.iso(now))
    if not clouds["stations"]:
        raise ValueError("Latest completed hour has no routine METARs; live history retained")
    missing = [frame['hour'] for frame in clouds['history'] if not frame['stations']]
    if missing:
        raise ValueError('NOAA archive has no eligible reports for '+', '.join(missing)
                         +'; previous live history retained')
    airport_rows = [row for frame in clouds["history"] for row in frame["stations"]]
    plots = airport_plots.collect(None, now, previous_stations, airport_rows=airport_rows)
    counts = [{"hour": f["hour"], "stations": len(f["stations"])} for f in plots["history"]]
    metadata = {"source": airport_plots.SOURCE, "sourceUrl": ARCHIVE_URL,
                "completedAt": metar_clouds.iso(now), "hours": counts}
    plots["archiveBackfill"] = metadata
    store.write_json("live/station-plots.json", plots)
    for row in counts:
        print(f"{row['hour']}: {row['stations']} airport stations", flush=True)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-only", type=Path, help="Save NOAA reports without modifying cloud data")
    parser.add_argument("--archive-file", type=Path, help="Reuse the included NOAA archive if it is still recent")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    archive = recent_archive(args.archive_file, now) if args.archive_file else None
    if archive is None:
        archive = fetch_history(weather.download, now, cache_dir="/tmp/weather-lab-metar-archive-cache")
    if args.download_only:
        args.download_only.write_text(json.dumps(archive))
        return
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET must be set")
    # If the download crossed an hour, use its original complete target. The
    # immediately-triggered hourly job supplies the next hour after the import.
    publish_history(archive, store, now)


def recent_archive(path, now):
    if not path.is_file():
        return None
    with gzip.open(path, 'rb') as stream:
        raw = stream.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError('Included NOAA archive is unexpectedly large')
    archive = json.loads(raw)
    retrieved = airport_plots.timestamp(archive.get('retrievedAt'))
    if archive.get('source') != airport_plots.SOURCE or retrieved is None:
        raise ValueError('Included archive lacks NOAA provenance')
    if (not 0 <= (now-retrieved).total_seconds() <= 7200
            or archive.get('targetHour') != metar_clouds.iso(now.replace(minute=0,second=0,microsecond=0))):
        print('Included NOAA archive has aged; downloading fresh history.', flush=True)
        return None
    print(f"Reusing NOAA archive retrieved {archive['retrievedAt']}", flush=True)
    return archive


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
