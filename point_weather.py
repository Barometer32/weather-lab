"""Experimental point analysis: shared public observations, small on-demand grid.

Grid spacing is computational spacing, not an accuracy claim. The original
hourly airport product and Hopkins forecast are deliberately independent.
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import gzip
import json
import math
import re
import time
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

import numpy as np
from regional_madis import fetch, parse_file, iso

KEY = 'live/test-weather.json'
VERSION = 'point-analysis-v1'
UA = 'Weather-Lab (https://github.com/Barometer32/weather-lab)'
FAMILIES = ('mesonet', 'rwis', 'hfmetar')
AWC = 'https://aviationweather.gov/data/cache/metars.cache.xml.gz'
GRID_KM = 5
RADIUS_KM = 80


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def coordinates(lat, lon):
    lat, lon = float(lat), float(lon)
    if not math.isfinite(lat+lon) or not -85 <= lat <= 85 or not -180 <= lon <= 180:
        raise ValueError('Enter a valid latitude and longitude.')
    return round(lat, 4), round(lon, 4)


def number(value, low, high):
    try:
        value = float(value)
        return value if math.isfinite(value) and low <= value <= high else None
    except (ValueError, TypeError):
        return None


def airport_rows(payload, now):
    rows = []
    for entry in ET.fromstring(gzip.decompress(payload)).iter('METAR'):
        get = entry.findtext
        try:
            observed = stamp(get('observation_time'))
            lat, lon = coordinates(get('latitude'), get('longitude'))
        except (TypeError, ValueError, AttributeError):
            continue
        if not now-timedelta(hours=1) <= observed <= now:
            continue
        temp, dew = number(get('temp_c'), -90, 60), number(get('dewpoint_c'), -100, 60)
        speed, direction = number(get('wind_speed_kt'), 0, 200), number(get('wind_dir_degrees'), 0, 360)
        rows.append({'station': get('station_id'), 'name': get('station_id'), 'lat': lat, 'lon': lon,
                     'time': iso(observed), 'source': 'NOAA Aviation Weather Center', 'network': 'Airport METAR',
                     'provider': 'AWC', 'tempF': temp*1.8+32 if temp is not None else None,
                     'dewpointF': dew*1.8+32 if dew is not None else None,
                     'wind': {'speedMph': speed*1.15077945 if speed is not None else None, 'direction': direction}})
    return rows


def compact(row):
    return {key: row.get(key) for key in ('station','name','lat','lon','time','source','network','provider','tempF','dewpointF','wind')}


def latest(rows, now, minutes=60):
    chosen = {}
    for original in rows:
        try:
            row = compact(original)
            observed = stamp(row['time'])
            coordinates(row['lat'], row['lon'])
            if not row['station'] or not now-timedelta(minutes=minutes) <= observed <= now:
                continue
            # Preserve distinct providers when their station identifiers collide.
            key = (row['station'], round(row['lat'], 2), round(row['lon'], 2))
            if key not in chosen or row['time'] > chosen[key]['time']:
                chosen[key] = row
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    # Remove duplicate physical sensors distributed by more than one feed.
    # At 0.0002 degrees (~20m), separate airport/road sites remain distinct.
    physical = {}
    for row in sorted(chosen.values(), key=lambda r: (r['time'], r['provider'] == 'AWC'), reverse=True):
        key = (round(row['lat']*5000), round(row['lon']*5000))
        if key not in physical:
            physical[key] = row
    return list(physical.values())


def collect(store, now, download=None):
    download = download or (lambda url, previous: fetch(url, previous, timeout=20))
    previous = store.read_json(KEY) or {}
    if previous.get('version') == VERSION and now-stamp(previous['checkedAt']) < timedelta(minutes=4):
        return previous
    rows, errors, pending, good = [], [], [], 0
    hour = now.replace(minute=0, second=0, microsecond=0)
    for family in FAMILIES:
        for offset in (0, 1):
            name = (hour-timedelta(hours=offset)).strftime('%Y%m%d_%H00.gz')
            file_id = family+'/'+name
            old = store.read_json('live/test-input-'+family+'-'+str(offset)+'.json') or {}
            if old.get('file') != file_id:
                old = {}
            url = 'https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/'+family+'/netCDF/'+name
            try:
                payload, metadata = download(url, old.get('metadata'))
                if payload is not None:
                    parsed = parse_file(payload, now, bounds=(-85,-180,85,180),
                                        window_start=hour-timedelta(hours=1), window_end=now+timedelta(seconds=1),
                                        excluded_stations=(), sensor_status_checks=True, derive_dewpoint=True)
                    parsed = latest(parsed, now, 120)
                    old = {'file': file_id, 'metadata': metadata, 'stations': parsed}
                    store.write_json('live/test-input-'+family+'-'+str(offset)+'.json', old)
                rows.extend(old.get('stations', []))
                good += 1
            except Exception as error:
                # A current-hour 404 is normal before NOAA publishes that file.
                if offset == 0 and isinstance(error, HTTPError) and error.code == 404:
                    pending.append(family)
                else:
                    errors.append({'feed': family, 'file': name, 'error': str(error)[:160]})
                rows.extend(old.get('stations', []))
    old = store.read_json('live/test-input-airports.json') or {}
    try:
        payload, metadata = download(AWC, old.get('metadata'))
        if payload is not None:
            old = {'metadata': metadata, 'stations': airport_rows(payload, now)}
            store.write_json('live/test-input-airports.json', old)
        rows.extend(old.get('stations', []))
        good += 1
    except Exception as error:
        rows.extend(old.get('stations', []))
        errors.append({'feed': 'airports', 'error': str(error)[:160]})
    if not good:
        raise ValueError('All TEST observation feeds failed; previous snapshot retained.')
    # Reuse still-current previous rows only for feeds that failed this check.
    # Successfully reissued files replace prior QC decisions rather than merging.
    stations = latest(rows, now)
    if not stations:
        raise ValueError('No recent TEST observations; previous snapshot retained.')
    data = {'version': VERSION, 'checkedAt': iso(now), 'windowStart': iso(now-timedelta(hours=1)),
            'windowEnd': iso(now), 'stations': stations, 'errors': errors, 'pendingFiles': pending,
            'source': 'NOAA MADIS public mesonet, RWIS, high-frequency airports and AWC METAR'}
    store.write_json(KEY, data)
    return data


def haversine(lat, lon, lats, lons):
    y1, y2 = np.radians(lat), np.radians(lats)
    dy, dx = y2-y1, np.radians(lons-lon)
    a = np.sin(dy/2)**2 + np.cos(y1)*np.cos(y2)*np.sin(dx/2)**2
    return 6371*2*np.arcsin(np.sqrt(np.clip(a,0,1)))


def analysis(data, lat, lon, now, minutes=30):
    """IDW at four fixed 5-km grid nodes, bilinear sampling at the chosen pin."""
    from scipy.spatial import cKDTree
    lat, lon = coordinates(lat, lon)
    if minutes != 30:
        raise ValueError('TEST uses only observations from the past 30 minutes.')
    result = {'latitude': lat, 'longitude': lon, 'estimated': True, 'gridSpacingKm': GRID_KM,
              'windowMinutes': minutes, 'checkedAt': data.get('checkedAt'), 'available': False,
              'sourceErrors': data.get('errors', []), 'pendingFiles': data.get('pendingFiles', []), 'fields': {}, 'stations': []}
    rows = latest(data.get('stations', []), now, minutes)
    if not rows:
        result['message'] = 'No recent usable observations in this time window.'
        return result
    lats, lons = np.array([r['lat'] for r in rows]), np.array([r['lon'] for r in rows])
    d = haversine(lat,lon,lats,lons)
    selected = np.flatnonzero(d <= RADIUS_KM+GRID_KM*2)
    rows, d = [rows[i] for i in selected], d[selected]
    if not rows:
        result['message'] = 'No nearby recent stations. NWS forecast can still be available.'
        return result
    # A local metric grid in latitude/longitude coordinates. Longitude scale is
    # fixed to this 1-degree latitude band so the grid does not move with a pin.
    scale = 111.195*math.cos(math.radians(math.floor(lat)+.5))
    x, y = lon*scale, lat*111.195
    gx, gy = math.floor(x/GRID_KM)*GRID_KM, math.floor(y/GRID_KM)*GRID_KM
    fx, fy = (x-gx)/GRID_KM, (y-gy)/GRID_KM
    nodes = [(gx,gy,(1-fx)*(1-fy)),(gx+GRID_KM,gy,fx*(1-fy)),
             (gx,gy+GRID_KM,(1-fx)*fy),(gx+GRID_KM,gy+GRID_KM,fx*fy)]
    xy = np.array([[r['lon']*scale,r['lat']*111.195] for r in rows])
    tree = cKDTree(xy)
    density = np.array([len(v) for v in tree.query_ball_point(xy, 5)])
    ages = np.array([(now-stamp(r['time'])).total_seconds()/60 for r in rows])
    source_weights = np.array([.55 if r.get('network') == 'CWOP' else 1 for r in rows])
    base = np.exp(-ages/30)*source_weights/np.sqrt(np.maximum(1,density))
    temps = np.array([number(r.get('tempF'), -130, 140) for r in rows], dtype=float)
    dews = np.array([number(r.get('dewpointF'), -148, 140) for r in rows], dtype=float)
    dews[dews > temps+3.6] = np.nan
    speeds = np.array([number((r.get('wind') or {}).get('speedMph'),0,230) for r in rows],dtype=float)
    dirs = np.array([number((r.get('wind') or {}).get('direction'),0,360) for r in rows],dtype=float)
    dirs[speeds == 0] = 0  # Missing direction is valid only for a calm wind.
    u, v = -speeds*np.sin(np.radians(dirs)), -speeds*np.cos(np.radians(dirs))
    def estimate(values, robust=True):
        valid = np.isfinite(values)
        support = np.zeros(len(rows), dtype=float)
        total = 0.
        for nx,ny,blend in nodes:
            if blend < 1e-10:
                continue
            distances = haversine(ny/111.195,nx/scale,np.array([r['lat'] for r in rows]),np.array([r['lon'] for r in rows]))
            mask = valid & (distances <= RADIUS_KM)
            if mask.sum() < 3 or distances[mask].min() > 40:
                return None, support
            weights = base[mask]*np.exp(-distances[mask]/25)/(distances[mask]+2)**2
            if robust:
                center = float(np.median(values[mask]))
                spread = max(12., 4.5*float(np.median(np.abs(values[mask]-center))))
                weights *= np.minimum(1, spread/np.maximum(spread,np.abs(values[mask]-center)))**2
            weights /= weights.sum()
            total += blend*float(np.dot(weights,values[mask]))
            support[mask] += blend*weights
        return total, support
    supports = []
    def field(name, value, support):
        if value is None:
            result['fields'][name] = {'value': None, 'stationCount': 0}
            return
        indices = np.flatnonzero(support > 0)
        times = [rows[i]['time'] for i in indices]
        result['fields'][name] = {'value': round(value,1), 'stationCount': len(indices),
             'observationStart': min(times), 'observationEnd': max(times),
             'representativeTime': iso(datetime.fromtimestamp(sum(stamp(rows[i]['time']).timestamp()*support[i] for i in indices)/support.sum(),timezone.utc)),
             'nearestKm': round(float(d[indices].min()),1)}
        supports.append(support)
    temp, ts = estimate(temps)
    dew, ds = estimate(dews)
    field('temperatureF',temp,ts)
    field('dewpointF',min(dew,temp) if dew is not None and temp is not None else dew,ds)
    ue, us = estimate(u,False)
    ve, vs = estimate(v,False)
    speed = math.hypot(ue,ve) if ue is not None and ve is not None else None
    field('windMph',speed,us if speed is not None else np.zeros(len(rows)))
    result['windDirection'] = (math.degrees(math.atan2(-ue,-ve))%360) if speed is not None and speed >= .5 else None
    result['available'] = any(f['value'] is not None for f in result['fields'].values())
    if supports:
        combined = np.maximum.reduce(supports)
        used = np.flatnonzero(combined > 0)
        result.update(stationCount=len(used), observationStart=min(rows[i]['time'] for i in used),
                      observationEnd=max(rows[i]['time'] for i in used), nearestKm=round(float(d[used].min()),1))
        result['stations'] = [{**rows[i], 'distanceKm':round(float(d[i]),1)} for i in sorted(used,key=lambda i:d[i])[:30]]
        result['message'] = 'Sparse station support; treat as a broad-area estimate.' if len(used)<6 or d[used].min()>15 else ''
    else:
        result['message'] = 'At least three recent stations within 80 km, including one within 40 km, are needed for each value.'
    result['stale'] = not data.get('checkedAt') or now-stamp(data['checkedAt']) > timedelta(minutes=12)
    return result


def read_url(url):
    with urlopen(Request(url,headers={'User-Agent':UA,'Accept':'application/geo+json, application/json, text/html'}),timeout=20) as response:
        body = response.read(4_000_001)
        if len(body)>4_000_000:
            raise ValueError('Upstream response exceeds expected size.')
        return body, response.geturl()


@lru_cache(maxsize=256)
def location(query):
    query = query.strip()
    if not query or len(query)>160:
        raise ValueError('Enter a city and state, ZIP code, or latitude, longitude.')
    match = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*',query)
    if match:
        lat, lon = coordinates(*match.groups())
        return {'latitude':lat,'longitude':lon,'label':f'{lat:.4f}, {lon:.4f}'}
    _, final = read_url('https://forecast.weather.gov/zipcity.php?'+urlencode({'inputstring':query}))
    parsed = urlparse(final)
    params = parse_qs(parsed.query)
    try:
        if parsed.hostname != 'forecast.weather.gov' or parsed.path != '/MapClick.php':
            raise ValueError()
        lat, lon = coordinates(params['textField1'][0],params['textField2'][0])
    except (KeyError, ValueError):
        raise ValueError('NWS could not uniquely locate that place. Add a state, use a ZIP code, or enter latitude, longitude.')
    label = ', '.join(params[k][0] for k in ('CityName','state') if params.get(k)) or query
    return {'latitude':lat,'longitude':lon,'label':label}


@lru_cache(maxsize=256)
def point_info(lat, lon, day):
    return json.loads(read_url(f'https://api.weather.gov/points/{lat},{lon}')[0])['properties']


@lru_cache(maxsize=256)
def point_forecast(lat, lon, slot):
    info = point_info(lat,lon,int(time.time()//86400))
    url = info['forecast']
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'api.weather.gov' or not parsed.path.startswith('/gridpoints/'):
        raise ValueError('Unexpected NWS forecast URL.')
    data = json.loads(read_url(url)[0])['properties']
    rel = info.get('relativeLocation',{}).get('properties',{})
    return {'source':'National Weather Service','updatedAt':data.get('updated'), 'timeZone':info.get('timeZone','America/Chicago'),
            'location':', '.join(rel[k] for k in ('city','state') if rel.get(k)),
            'sourceUrl':f'https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}',
            'periods':[{k:p.get(k) for k in ('name','temperature','temperatureUnit','detailedForecast','startTime','endTime','isDaytime')} for p in data.get('periods',[])]}


def main():
    from realtime import get_store
    data = collect(get_store(),datetime.now(timezone.utc))
    print(json.dumps({'stations':len(data['stations']),'checkedAt':data['checkedAt'],'partialFeedErrors':data['errors']}),flush=True)


if __name__ == '__main__':
    main()
