"""Latest individual pollutant observations from nearby active AirNow monitors.

Locations use the nearest available monitor per pollutant within 50 km. Values
are hourly measurements and provided monitor AQI subindices, not a fabricated
combined score or an exact measurement at the selected GPS point.
"""
from datetime import datetime, timedelta, timezone
import csv
from io import StringIO
import math
from threading import Lock
import time
from urllib.request import Request, urlopen

from current_analysis import coordinates, state_for

UTC = timezone.utc
VERSION = 'local-pollutants-v2'
FEED_ROOT = 'https://files.airnowtech.org/airnow/'
# AQI column, raw concentration column, expected concentration units.
COLUMNS = {'PM2.5': (16, 22, 'UG/M3'), 'PM10': (15, 32, 'UG/M3'),
           'Ozone': (14, 24, 'PPB'), 'NO2': (17, 26, 'PPB')}
_snapshot = None
_checked = float('-inf')
_guard = Lock()


def iso(value):
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def number(value, minimum, maximum):
    try:
        value = float(value)
        return value if math.isfinite(value) and minimum <= value <= maximum else None
    except (ValueError, TypeError):
        return None


def distance(lat, lon, y, x):
    a, b = math.radians(lat), math.radians(y)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(x-lon)/2)**2
    return 6371*2*math.asin(math.sqrt(min(1., max(0., h))))


def download(url):
    request = Request(url, headers={'User-Agent': 'Weather-Lab (https://github.com/Barometer32/weather-lab)'})
    with urlopen(request, timeout=15) as response:
        content = response.read(8_000_001)
    if len(content) > 8_000_000:
        raise ValueError('AirNow response exceeded its expected size.')
    return content.decode('utf-8-sig')


def parse_hour(content, hour):
    result = []
    for row in csv.reader(StringIO(content)):
        try:
            if len(row) < 34 or row[2] != 'Active' or row[8] != 'US' or row[9] not in ('MN', 'WI'):
                continue
            observed = datetime.strptime(row[10]+' '+row[11], '%m/%d/%Y %H:%M').replace(tzinfo=UTC)
            if observed != hour:
                continue
            lat, lon = coordinates(row[4], row[5])
            if not state_for(lat, lon):
                continue
            values, scores = {}, {}
            for name, (aq_col, raw_col, expected) in COLUMNS.items():
                raw = number(row[raw_col], -5., 2000.)
                unit = row[raw_col+1].upper().strip()
                if name in ('Ozone', 'NO2') and unit == 'PPM' and raw is not None:
                    raw *= 1000; unit = 'PPB'
                if unit == expected and raw is not None and -5 <= raw <= 2000:
                    values[name] = raw
                score = number(row[aq_col], 0, 1000)
                if score is not None:
                    scores[name] = int(math.floor(score+.5))
            if values or scores:
                result.append(dict(id=row[0], name=row[1], lat=lat, lon=lon,
                    start=iso(hour), end=iso(hour+timedelta(hours=1)), values=values, scores=scores,
                    source=row[12]))
        except (ValueError, TypeError, IndexError):
            continue
    return result


def hour_url(hour):
    return FEED_ROOT+hour.strftime('%Y/%Y%m%d/HourlyAQObs_%Y%m%d%H.dat')


def load_snapshot(now, fetch=download):
    for offset in (1, 2, 3):
        hour = now.replace(minute=0, second=0, microsecond=0)-timedelta(hours=offset)
        try:
            rows = parse_hour(fetch(hour_url(hour)), hour)
            if rows:
                return dict(version=VERSION, checkedAt=iso(now), latestHour=iso(hour), rows=rows, errors=[])
        except Exception:
            continue
    raise ValueError('AirNow observations are temporarily unavailable.')


def shared_snapshot(now):
    global _snapshot, _checked
    with _guard:
        if _snapshot is not None and time.monotonic()-_checked < 1800:
            return _snapshot
        try:
            value = load_snapshot(now)
        except Exception:
            if _snapshot is None:
                raise
            _snapshot = {**_snapshot, 'errors': ['AirNow refresh delayed']}
            _checked = time.monotonic()-1500
            return _snapshot
        _snapshot, _checked = value, time.monotonic()
        return value


def local_air(snapshot, latitude, longitude, now):
    lat, lon = coordinates(latitude, longitude)
    result = dict(version=VERSION, latitude=lat, longitude=lon, checkedAt=snapshot['checkedAt'],
                  readings=[], errors=snapshot.get('errors', []),
                  source='EPA AirNow / state monitoring agencies', method='nearest-monitor-hourly', estimated=True)
    in_region = state_for(lat, lon)
    latest = stamp(snapshot['latestHour']) if snapshot.get('latestHour') else None
    usable = in_region and latest is not None and timedelta(0) <= now-(latest+timedelta(hours=1)) <= timedelta(hours=3)
    current = [r for r in snapshot.get('rows', []) if usable and stamp(r['start']) == latest]
    current.sort(key=lambda r:distance(lat,lon,r['lat'],r['lon']))
    for name in COLUMNS:
        # Prefer an actual hourly concentration; use an available subindex alone
        # only when no nearby monitor has that concentration for the same hour.
        nearby = [r for r in current if distance(lat,lon,r['lat'],r['lon']) <= 50]
        station = next((r for r in nearby if name in r['values']), None)
        station = station or next((r for r in nearby if name in r['scores']), None)
        reading = dict(pollutant=name, value=None, aqi=None,
                       unit='µg/m³' if name in ('PM2.5','PM10') else 'ppb',
                       aqiType='Hourly AQI' if name=='NO2' else 'NowCast AQI',
                       station=None, stationId=None, distanceKm=None, start=None, time=None)
        if station:
            raw = station['values'].get(name)
            reading.update(value=max(0.,raw) if raw is not None else None,
                           rawValue=raw, aqi=station['scores'].get(name),
                           station=station['name'], stationId=station['id'],
                           distanceKm=round(distance(lat,lon,station['lat'],station['lon']),1),
                           start=station['start'], time=station['end'])
        result['readings'].append(reading)
    result['available'] = any(r['value'] is not None or r['aqi'] is not None for r in result['readings'])
    times = [stamp(r['time']) for r in result['readings'] if r['time']]
    result['stale'] = bool(snapshot.get('errors')) or any(now-t > timedelta(hours=2) for t in times)
    if not in_region:
        result['message'] = 'Local air quality currently covers Minnesota and Wisconsin.'
    elif not result['available']:
        result['message'] = 'Recent pollutant observations within 50 km are unavailable.'
    return result
