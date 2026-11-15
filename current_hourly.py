"""Prepared CURRENT tab: twelve official :50–:59 three-airport hours."""
from datetime import timedelta
import json
import math
from urllib.parse import urlencode

import app as weather
from hourly_airport_observations import select_reports

KEY = 'live/current-hourly-v1.json'
VERSION = 'official-hourly-t-remarks-v1'
HISTORY_HOURS = 12
STATIONS = ('KMSP', 'KFCM', 'KMIC')
SOURCE_URL = 'https://aviationweather.gov/api/data/metar'


def nearest(value):
    return math.floor(value + .5) if value is not None else None


def hour_summary(selected, hour):
    reports = [weather.metar_precision(selected[hour, code][1], fallback=False)
               for code in STATIONS if (hour, code) in selected]
    summary = weather.summarize(reports, hour, mean_digits=8)
    wind = summary['wind']
    complete = all(n == 3 for n in (summary['tempCount'], summary['dewpointCount'], wind['speedCount']))
    for station in summary['stations']:
        report = next((r for r in reports if r['icaoId'] == station['code']), None)
        station['wind'] = weather.wind_mean([report], speed_digits=8) if report else {}
        station['tempC'] = report.get('temp') if report else None
        station['dewpointC'] = report.get('dewp') if report else None
        if report and weather.valid_number(report.get('temp'), -90, 60):
            station['tempF'] = nearest(report['temp'] * 1.8 + 32)
        if report and weather.valid_dewpoint(report):
            station['dewpointF'] = nearest(report['dewp'] * 1.8 + 32)
    # Average native Celsius/knots first; round only the final display values.
    return {**summary, 'complete': complete,
            'tempF': nearest(summary['tempC'] * 1.8 + 32) if summary['tempCount'] == 3 else None,
            'dewpointF': nearest(summary['dewpointC'] * 1.8 + 32) if summary['dewpointCount'] == 3 else None,
            'wind': {**wind, 'speedMph': nearest(wind['speedMph']) if wind['speedCount'] == 3 else None}}


def present(saved, now):
    saved = saved or {}
    target = now.replace(minute=0, second=0, microsecond=0)
    selected = select_reports(saved.get('reports', []), now)
    hours = [hour_summary(selected, target-timedelta(hours=i)) for i in range(13)]
    pending = not hours[0]['complete']
    current = next((row for row in hours if row['complete']), None)
    # Preserve twelve prior hours while the new one is still incomplete.
    history = [row for row in (hours[1:13] if pending else hours[:12]) if row['complete']]
    return {'version': VERSION, 'current': current, 'history': history,
            'pending': hours[0] if pending else None, 'pendingHour': weather.iso(target) if pending else None,
            'checkedAt': saved.get('checkedAt'), 'serverTime': weather.iso(now),
            'stale': current is None or current['hour'] < weather.iso(target-timedelta(hours=1)),
            'source': 'NOAA Aviation Weather Center official METARs', 'sourceUrl': SOURCE_URL,
            'stationIds': list(STATIONS), 'reportWindow': ':50–:59', 'precision': 'T remarks only',
            'updateIntervalSeconds': 120}


def collect(store, now):
    saved = store.read_json(KEY) or {}
    target = now.replace(minute=0, second=0, microsecond=0)
    if present(saved, now)['pendingHour'] is None:
        return {'status': 'already prepared', 'hour': weather.iso(target), 'checkedAt': saved.get('checkedAt')}
    # A small three-airport query recovers history on first run. Later retries
    # fetch only recent reports and merge without discarding earlier hours.
    hours = 2 if saved.get('reports') else 14
    params = {'ids': ','.join(STATIONS), 'format': 'json', 'hours': hours, 'date': weather.iso(target)}
    raw = weather.download(SOURCE_URL + '?' + urlencode(params))
    fresh = json.loads(raw) if raw else []
    if not isinstance(fresh, list):
        raise ValueError('NOAA returned an invalid METAR history response')
    chosen = select_reports([*saved.get('reports', []), *fresh], now)
    if not chosen:
        raise ValueError('No official :50–:59 METARs available; prior prepared history retained')
    data = {'version': VERSION, 'checkedAt': weather.iso(now),
            'reports': [r for _, r in chosen.values()]}
    store.write_json(KEY, data)
    result = present(data, now)
    return {'reports': len(chosen), 'currentHourReady': result['pendingHour'] is None,
            'checkedAt': data['checkedAt']}
