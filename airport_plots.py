"""Twelve hourly official airport METAR plot snapshots, with no analysis grids."""
from datetime import timedelta

import metar_clouds
from station_plots import history, iso, number, timestamp, valid_saved, WINDOW

VERSION = 7
NETWORK = 'AWC_METAR'
SOURCE = 'NOAA Aviation Weather Center'
MODE = 'official-airports'


def official(row):
    return row.get('source') == SOURCE and row.get('network') == NETWORK and row.get('reportType') == 'METAR'


def normalize(row, hour):
    if (row.get('reportType') != 'METAR' or str(row.get('rawOb', '')).startswith('SPECI')
            or 'MADISHF' in str(row.get('rawOb', ''))
            or not metar_clouds.in_region(row) or not valid_saved(row, hour)):
        return None
    temp, dew = number(row.get('tempF'), -130, 140), number(row.get('dewpointF'), -148, 140)
    if temp is not None and dew is not None and dew > temp+1:
        dew = None
    wind = row.get('wind') or {}
    knots, speed = number(wind.get('speedKnots'), 0, 200), number(wind.get('speedMph'), 0, 231)
    if speed is None and knots is not None:
        speed = knots*1.150779448
    if temp is None and dew is None and speed is None:
        return None
    return {'station': row['station'], 'stationKey': NETWORK+':'+row['station'],
            'network': NETWORK, 'name': row.get('name') or row['station'],
            'lat': row['lat'], 'lon': row['lon'], 'time': row['time'],
            'receiptTime': row.get('receiptTime', ''), 'rawOb': row.get('rawOb', ''),
            'tempF': temp, 'dewpointF': dew,
            'wind': {'speedKnots': knots, 'speedMph': speed,
                     'direction': number(wind.get('direction'), 0, 360), 'variable': bool(wind.get('variable'))},
            'source': SOURCE, 'reportType': 'METAR', 'quality': 'range-and-time-checked'}


def airport_history(frames, hour):
    clean = []
    for frame in frames:
        target = timestamp(frame.get('hour'))
        if target is None:
            continue
        rows = [normalize(row, target) for row in frame.get('stations', []) if official(row)]
        clean.append({'hour': iso(target), 'stations': [r for r in rows if r is not None],
                      **({'sourceHealth': frame['sourceHealth']} if 'sourceHealth' in frame else {})})
    return history(clean, hour)


def collect(download, now, previous=None, airport_rows=None):
    hour = now.replace(minute=0, second=0, microsecond=0)
    previous = previous or {}
    if airport_rows is None:
        from backfill_metars import fetch_history
        raw = fetch_history(download, now, hours=1)
        data = metar_clouds.snapshot(raw['reports'], hour, iso(now))
        airport_rows = [r for f in data['history'] for r in f['stations']]
    incoming = {}
    for row in airport_rows:
        if row.get('source', SOURCE) != SOURCE:
            continue
        observed = timestamp(row.get('time'))
        if observed is None:
            continue
        target = observed.replace(minute=0, second=0, microsecond=0)+timedelta(hours=1)
        if not hour-timedelta(hours=11) <= target <= hour:
            continue
        item = normalize(row, target)
        if item:
            incoming.setdefault(iso(target), []).append(item)
    frames = airport_history(previous.get('history', [])+
                             [{'hour': label, 'stations': rows} for label, rows in incoming.items()], hour)
    selected = frames[-1]['stations']
    if not incoming.get(iso(hour)):
        raise ValueError('No routine airport METARs in the :50–:59 window; previous snapshot retained')
    health = [{'source': 'AWC METAR', 'status': 'ok', 'reports': len(selected)}]
    frames[-1]['sourceHealth'] = health
    return {'version': VERSION, 'observationMode': MODE, 'collectionMode': 'hourly-window',
            'hour': iso(hour), 'checkedAt': iso(now), 'bounds': metar_clouds.BOUNDS,
            'stations': selected, 'history': frames, 'windowMinutes': 10,
            'source': SOURCE, 'sourceUrl': 'https://aviationweather.gov/data/api/',
            'sourceHealth': health, 'failedSources': []}


def current(data, now):
    hour = timestamp(data.get('hour')) or now.replace(minute=0, second=0, microsecond=0)
    frames = airport_history(data.get('history', []), hour)
    return {**data, 'stations': frames[-1]['stations'], 'history': frames, 'windowMinutes': 10}
