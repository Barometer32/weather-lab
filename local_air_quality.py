"""Official nearby-area U.S. AQI plus a separate classic three-pollutant AQHI estimate.

AQHI here is a local calculation from nearby U.S. monitors, not an issued
Canadian observation or an all-pollutant personal exposure measurement.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import csv
from io import StringIO
import math
from threading import Lock
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from current_analysis import coordinates, state_for

UTC = timezone.utc
REPORTING_URL = 'https://files.airnowtech.org/airnow/today/reportingarea.dat'
FEED_ROOT = 'https://files.airnowtech.org/airnow/'
COEFFICIENTS = {'PM2.5': .000487, 'Ozone': .000537, 'NO2': .000871}
# AQI column, raw concentration column, expected units.
COLUMNS = {'PM2.5': (16, 22, 'UG/M3'), 'Ozone': (14, 24, 'PPB'),
           'NO2': (17, 26, 'PPB'), 'PM10': (15, 32, 'UG/M3'),
           'CO': (None, 28, 'PPM'), 'SO2': (None, 30, 'PPB')}
CATEGORY = [(50, 'Good', '#00a82d'), (100, 'Moderate', '#ad8500'),
            (150, 'Unhealthy for sensitive groups', '#dd6500'),
            (200, 'Unhealthy', '#d42626'), (300, 'Very unhealthy', '#8f3f97'),
            (math.inf, 'Hazardous', '#7e0023')]
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
                # Slight negative raw values can be valid instrument drift in clean air.
                minimum = -.5 if name == 'CO' else -5.
                raw = number(row[raw_col], minimum, 2000.)
                unit = row[raw_col+1].upper().strip()
                if name in ('Ozone', 'NO2', 'SO2') and unit == 'PPM' and raw is not None:
                    raw *= 1000; unit = 'PPB'
                if unit == expected and raw is not None and minimum <= raw <= 2000:
                    values[name] = raw
                if aq_col is not None:
                    score = number(row[aq_col], 0, 1000)
                    if score is not None:
                        scores[name] = int(math.floor(score+.5))
            if values or scores:
                result.append(dict(id=row[0], name=row[1], lat=lat, lon=lon,
                    start=iso(hour), end=iso(hour+timedelta(hours=1)), values=values, scores=scores,
                    areas=[name.strip() for name in row[13].split('|') if name.strip()], source=row[12]))
        except (ValueError, TypeError, IndexError):
            continue
    return result


def parse_areas(content, now):
    offsets = {'EST': -5, 'EDT': -4, 'CST': -6, 'CDT': -5}
    result = []
    for row in csv.reader(StringIO(content), delimiter='|'):
        try:
            if len(row) < 17 or row[5] != 'O' or row[8] not in ('MN', 'WI') or row[3] not in offsets:
                continue
            observed = datetime.strptime(row[1]+' '+row[2], '%m/%d/%y %H:%M').replace(tzinfo=timezone(timedelta(hours=offsets[row[3]]))).astimezone(UTC)
            if not now-timedelta(hours=3) <= observed <= now:
                continue
            score = number(row[12], 0, 1000)
            lat, lon = coordinates(row[9], row[10])
            if score is None:
                continue
            name = {'OZONE': 'Ozone'}.get(row[11], row[11])
            result.append(dict(name=row[7], state=row[8], lat=lat, lon=lon,
                               pollutant=name, value=int(math.floor(score+.5)), time=iso(observed)))
        except (ValueError, TypeError, IndexError):
            continue
    return result


def hour_url(hour):
    return FEED_ROOT+hour.strftime('%Y/%Y%m%d/HourlyAQObs_%Y%m%d%H.dat')


def load_snapshot(now, fetch=download):
    errors = []
    latest, rows = None, []
    for offset in (1, 2, 3):
        hour = now.replace(minute=0, second=0, microsecond=0)-timedelta(hours=offset)
        try:
            parsed = parse_hour(fetch(hour_url(hour)), hour)
            if parsed:
                latest, rows = hour, parsed
                break
        except Exception:
            continue
    jobs = [('areas', REPORTING_URL)]
    if latest:
        jobs += [(latest-timedelta(hours=n), hour_url(latest-timedelta(hours=n))) for n in (1, 2)]
    areas = []
    def read(job):
        key, url = job
        try:
            text = fetch(url)
            return key, parse_areas(text, now) if key == 'areas' else parse_hour(text, key)
        except Exception:
            return key, None
    with ThreadPoolExecutor(max_workers=3) as pool:
        for key, data in pool.map(read, jobs):
            if data is None:
                errors.append('reporting areas' if key == 'areas' else 'one source hour')
            elif key == 'areas':
                areas = data
            else:
                rows.extend(data)
    if not areas and not rows:
        raise ValueError('AirNow observations are temporarily unavailable.')
    return dict(checkedAt=iso(now), latestHour=iso(latest) if latest else None,
                rows=rows, areas=areas, errors=errors)


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
            value = {**_snapshot, 'errors': ['AirNow refresh delayed']}
            _snapshot = value
            # Brief failure cache; source age is independently checked on every read.
            _checked = time.monotonic()-1500
            return value
        _snapshot, _checked = value, time.monotonic()
        return value


def classic_aqhi(concentrations):
    if any(concentrations.get(name) is None for name in COEFFICIENTS):
        return None
    # Raw 3-hour means in micrograms/m3 (PM2.5) and ppb (O3/NO2), not U.S. AQI scores.
    terms = {name: math.expm1(coefficient*max(0., concentrations[name]))
             for name, coefficient in COEFFICIENTS.items()}
    raw = 1000/10.4*sum(terms.values())
    level = max(1, int(math.floor(raw+.5)))
    category = 'Low' if level <= 3 else 'Moderate' if level <= 6 else 'High' if level <= 10 else 'Very high'
    total = sum(terms.values())
    return dict(value=level, display='10+' if level > 10 else str(level), rawValue=round(raw, 3),
                category=category, contributionsPct={name:round(term/total*100, 1) if total else 0 for name,term in terms.items()})


def local_air(snapshot, latitude, longitude, now):
    lat, lon = coordinates(latitude, longitude)
    result = dict(latitude=lat, longitude=lon, checkedAt=snapshot['checkedAt'], aqi=None,
                  mix=None, components=[], readings=[], errors=snapshot.get('errors', []),
                  source='EPA AirNow / state monitoring agencies', estimated=True)
    if not state_for(lat, lon):
        result['message'] = 'Local air quality currently covers Minnesota and Wisconsin.'
        return result
    latest = stamp(snapshot['latestHour']) if snapshot.get('latestHour') else None
    usable = latest is not None and timedelta(0) <= now-(latest+timedelta(hours=1)) <= timedelta(hours=3)
    current = [r for r in snapshot['rows'] if usable and stamp(r['start']) == latest]
    current.sort(key=lambda r:distance(lat,lon,r['lat'],r['lon']))
    # Prefer the reporting area assigned to the nearest active monitor. This is
    # an area lookup, not a claim that an area centre is a sensor at the GPS point.
    preferred = next((r['areas'] for r in current if r['areas'] and distance(lat,lon,r['lat'],r['lon']) <= 80), [])
    areas = [r for r in snapshot['areas'] if timedelta(0) <= now-stamp(r['time']) <= timedelta(hours=3)]
    names = {r['name'] for r in areas if r['name'] in preferred} or {r['name'] for r in areas}
    candidates = [r for r in areas if r['name'] in names and distance(lat,lon,r['lat'],r['lon']) <= 100]
    if candidates:
        anchor = min(candidates,key=lambda r:distance(lat,lon,r['lat'],r['lon']))
        same = [r for r in candidates if (r['name'],r['state']) == (anchor['name'],anchor['state'])]
        newest = max(r['time'] for r in same)
        same = [r for r in same if r['time'] == newest]
        maximum = max(same,key=lambda r:r['value'])
        category = next((name,color) for cutoff,name,color in CATEGORY if maximum['value'] <= cutoff)
        result['aqi'] = dict(value=maximum['value'], category=category[0], color=category[1],
            primaryPollutant=maximum['pollutant'], time=newest, area=anchor['name'], state=anchor['state'],
            selection='Nearby reporting area; not a measurement at the selected point',
            pollutants=[dict(pollutant=r['pollutant'],aqi=r['value']) for r in same])
    if usable:
        for name in COLUMNS:
            station = next((r for r in current if name in r['values'] and distance(lat,lon,r['lat'],r['lon']) <= 50), None)
            if station:
                result['readings'].append(dict(pollutant=name, value=station['values'][name],
                    unit='µg/m³' if name in ('PM2.5','PM10') else 'ppm' if name=='CO' else 'ppb',
                    time=station['end'], station=station['name'],
                    distanceKm=round(distance(lat,lon,station['lat'],station['lon']),1)))
        hours = [latest-timedelta(hours=n) for n in (2,1,0)]
        by_id = {}
        for r in snapshot['rows']:
            by_id.setdefault(r['id'], {})[r['start']] = r
        chosen = {}
        for name in COEFFICIENTS:
            options = []
            for station in current:
                d = distance(lat,lon,station['lat'],station['lon'])
                history = [by_id[station['id']].get(iso(hour)) for hour in hours]
                if d > 50 or not all(r and name in r['values'] for r in history):
                    continue
                options.append((d,station,history))
            if not options:
                continue
            d, station, history = min(options,key=lambda item:item[0])
            average = max(0.,sum(r['values'][name] for r in history)/3)
            chosen[name] = average
            result['components'].append(dict(pollutant=name, mean=round(average,3),
                unit='µg/m³' if name == 'PM2.5' else 'ppb', station=station['name'], stationId=station['id'],
                distanceKm=round(d,1), start=iso(hours[0]), end=iso(latest+timedelta(hours=1))))
        mix = classic_aqhi(chosen)
        if mix:
            result['mix'] = dict(**mix, start=iso(hours[0]), end=iso(latest+timedelta(hours=1)),
                method='Classic 3-pollutant AQHI estimate', official=False,
                limitation='Nearby-monitor estimate using PM2.5, ozone and NO2 only; not an official issued AQHI or an all-pollutant score. Does not include Canadian smoke overrides.')
        else:
            result['mixMessage'] = 'Combined estimate unavailable: three complete hourly readings are needed for PM2.5, ozone and NO₂ within 50 km.'
    else:
        result['mixMessage'] = 'Recent observations for the combined estimate are unavailable.'
    times = ([result['aqi']['time']] if result['aqi'] else [])+([result['mix']['end']] if result['mix'] else [])
    result['stale'] = bool(snapshot.get('errors')) or any(now-stamp(t)>timedelta(hours=2) for t in times)
    if not result['aqi'] and not result['mix']:
        result['message'] = 'Recent local air quality observations are unavailable.'
    return result
