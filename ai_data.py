"""Bounded downloads of routine airport reports from the free IEM archive.

IEM is the archive provider here, not a source of mesonet observations.
Only report_type=3 and :50--:59 reports are accepted. No times are filled.
"""
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UTC = timezone.utc
STATIONS = ('MSP','FCM','STC','AXN','BRD','BJI','INL','DLH','HIB','RWF',
            'MKT','RST','FRM','OTG','FAR','GFK','BIS','JMS','FSD','ABR',
            'ATY','EAU','LSE','MCW','DSM')
ARCHIVE = 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py'
COLUMNS = ('tmpf','dwpf','drct','sknt','alti','metar')


def number(raw, low, high):
    try:
        value = float(raw)
        return value if math.isfinite(value) and low <= value <= high else None
    except (ValueError, TypeError):
        return None


def parse_csv(text):
    """Return one real report per airport/hour; no interpolation or forward fill."""
    result = {}
    for raw in csv.DictReader(line for line in text.splitlines() if not line.startswith('#')):
        try:
            station = raw['station'].removeprefix('K')
            if station not in STATIONS:
                continue
            observed = datetime.fromisoformat(raw['valid']).replace(tzinfo=UTC)
            report = raw.get('metar', '').strip()
            if not 50 <= observed.minute <= 59 or report.startswith('SPECI') or 'MADISHF' in report:
                continue
            lat, lon = number(raw.get('lat'), 39, 51), number(raw.get('lon'), -108, -80)
            if lat is None or lon is None:
                continue
            temp, dew = number(raw.get('tmpf'), -100, 130), number(raw.get('dwpf'), -120, 100)
            if temp is not None and dew is not None and dew > temp+1:
                dew = None
            speed, direction = number(raw.get('sknt'), 0, 100), number(raw.get('drct'), 0, 360)
            u = v = None
            if speed is not None and speed < .5:
                u = v = 0.
            elif speed is not None and direction is not None:
                speed *= 1.150779448
                u, v = -speed*math.sin(math.radians(direction)), -speed*math.cos(math.radians(direction))
            hour = observed.replace(minute=0, second=0, microsecond=0)+timedelta(hours=1)
            rank = (abs(observed.minute+observed.second/60-53), -observed.timestamp(), ' COR ' not in ' '+report+' ')
            key = (int(hour.timestamp()/3600), station)
            row = {'station': station, 'lat': lat, 'lon': lon, 'hour': key[0],
                   'observedAt': observed.isoformat(), 'values': [temp, dew, u, v],
                   'altimeter': number(raw.get('alti'), 26, 33)}
            if key not in result or rank < result[key][0]:
                result[key] = (rank, row)
        except (KeyError, ValueError):
            continue
    return [item[1] for item in result.values()]


def download_history(days, end, cache_dir, progress=lambda *args, **kwargs: None, deadline=None):
    if not 30 <= days <= 183:
        raise ValueError('The pilot allows 30--183 history days per run')
    end = end.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end-timedelta(days=days)
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    rows, requests = [], []
    for offset in range(0, len(STATIONS), 5):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('Training runtime limit reached during download')
        group = STATIONS[offset:offset+5]
        params = [('station', s) for s in group]+[('data', c) for c in COLUMNS]
        params += [('report_type', '3'), ('latlon', 'yes'), ('tz', 'UTC'),
                   ('format', 'onlycomma'), ('missing', 'M'),
                   ('sts', start.isoformat()), ('ets', end.isoformat())]
        url = ARCHIVE+'?'+urlencode(params)
        path = cache_dir/(hashlib.sha256(url.encode()).hexdigest()+'.csv.gz')
        progress('download', 5+int(25*offset/len(STATIONS)),
                 f'Downloading airports {offset+1}–{offset+len(group)} of {len(STATIONS)}',
                 completedStations=offset, totalStations=len(STATIONS))
        if path.exists():
            text = gzip.decompress(path.read_bytes()).decode()
        else:
            text = None
            for attempt in range(2):
                try:
                    req = Request(url, headers={'User-Agent': 'Weather-Lab airport forecast pilot (github.com/Barometer32/weather-lab)'})
                    with urlopen(req, timeout=90) as response:
                        content = response.read(32_000_001)
                    if len(content) > 32_000_000:
                        raise ValueError('Archive response exceeded the pilot size limit')
                    text = content.decode('utf-8-sig')
                    if not text.startswith('station,'):
                        raise ValueError('Archive did not return the requested CSV columns')
                    path.write_bytes(gzip.compress(text.encode(), mtime=0))
                    break
                except Exception:
                    if attempt:
                        raise
                    time.sleep(5)
            time.sleep(1.1)  # IEM requires at least one second between requests.
        parsed = parse_csv(text)
        present = {r['station'] for r in parsed}
        if len(present) < 3 or len(parsed) < 500:
            raise ValueError('Too few eligible reports in an archive batch')
        rows.extend(parsed)
        requests.append({'stations': list(group), 'reports': len(parsed), 'sha256': hashlib.sha256(text.encode()).hexdigest()})
    meta = {'provider': 'Iowa Environmental Mesonet archive of official airport METARs',
            'sourceUrl': 'https://mesonet.agron.iastate.edu/request/download.phtml',
            'start': start.isoformat(), 'endExclusive': end.isoformat(), 'days': days,
            'requestedStations': list(STATIONS), 'requests': requests,
            'reportType': 'Routine METAR only', 'windowMinutes': [50,59], 'reports': len(rows)}
    return rows, meta


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--days', type=int, default=120)
    parser.add_argument('--output', default='training/history.json.gz')
    args = parser.parse_args()
    rows, metadata = download_history(args.days, datetime.now(UTC), 'training/cache',
        lambda stage, pct, detail, **kw: print(f'{pct}% {detail}', flush=True))
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps({'rows': rows, 'metadata': metadata}).encode(), mtime=0))
    print(json.dumps(metadata, indent=2))
