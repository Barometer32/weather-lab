"""Experimental observation-only surface estimates, prepared once per UTC hour.

Uses existing airport reports plus the public MADIS Integrated Mesonet files.
No forecast model, terrain correction, or claim of meteorological assimilation.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import math

import numpy as np
from scipy.spatial import cKDTree

from regional_madis import SOURCE, fetch, iso, parse_file

UTC = timezone.utc
KEY = 'live/expmet.json'
VERSION = 'expmet-grid-v1'
BOUNDS = (40., -100., 50., -85.)  # south, west, north, east, same airport domain
GRID_KM = 10
RADIUS_KM = 120
NEAREST_KM = 50
MIN_SITES = 3
PROJECTION_SCALE = 6371.0088*math.cos(math.radians(45))
PROJECTION_Y0 = math.log(math.tan(math.pi/4+math.radians(45)/2))


def project(lat, lon):
    """Scaled Web Mercator km at 45N, matching uniform screen-grid spacing."""
    return np.column_stack((np.radians(np.asarray(lon)+93)*PROJECTION_SCALE,
                            (np.log(np.tan(np.pi/4+np.radians(np.asarray(lat))/2))-PROJECTION_Y0)*PROJECTION_SCALE))


def unproject(x, y):
    return math.degrees(2*math.atan(math.exp(y/PROJECTION_SCALE+PROJECTION_Y0)))-90, -93+math.degrees(x/PROJECTION_SCALE)


def candidates(rows, target):
    """Latest report per physical station; no six-hour availability filter."""
    latest = {}
    south, west, north, east = BOUNDS
    for original in rows:
        try:
            row = dict(original)
            stamp = datetime.fromisoformat(row['time'].replace('Z', '+00:00')).astimezone(UTC)
            age = (target-stamp).total_seconds()/60
            lat, lon = float(row['lat']), float(row['lon'])
            if not 0 <= age <= 60 or not south <= lat <= north or not west <= lon <= east:
                continue
            name = str(row['station']).strip().upper()
            if not name:
                continue
            for key, low, high in [('tempF', -100, 140), ('dewpointF', -130, 120)]:
                value = row.get(key)
                row[key] = float(value) if isinstance(value, (int, float)) and math.isfinite(value) and low <= value <= high else None
            if row['tempF'] is not None and row['dewpointF'] is not None and row['dewpointF'] > row['tempF']+1:
                row['dewpointF'] = None
            wind = row.get('wind') or {}
            speed, direction = wind.get('speedMph'), wind.get('direction')
            row['uv'] = None
            if isinstance(speed, (int, float)) and math.isfinite(speed) and 0 <= speed <= 200:
                if speed == 0:
                    row['uv'] = [0., 0.]
                elif isinstance(direction, (int, float)) and math.isfinite(direction) and 0 <= direction <= 360:
                    angle = math.radians(direction)
                    row['uv'] = [-speed*math.sin(angle), -speed*math.cos(angle)]
            if row['tempF'] is None and row['dewpointF'] is None and row['uv'] is None:
                continue
            airport = row.get('reportType') == 'METAR'
            row.update(station=name, age=age, lat=lat, lon=lon,
                       provider='Airport METAR' if airport else row.get('provider') or 'MADIS',
                       reliability=1. if airport else .4 if row.get('provider') == 'APRSWXNET' else .7)
            # Same physical airport can appear in multiple feeds. Prefer its
            # official report at the same timestamp; never count it twice.
            rank = (stamp, airport)
            if name not in latest or rank > latest[name][0]:
                latest[name] = (rank, row)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [value[1] for value in latest.values()]


def samples(rows, field):
    """One best-supported sample per 5 km bin, separately for each variable."""
    selected = {}
    for row in rows:
        if row.get(field) is None:
            continue
        xy = project([row['lat']], [row['lon']])[0]
        cell = tuple(np.floor(xy/5).astype(int))
        rank = (row['reliability'], -row['age'], row['station'])
        if cell not in selected or rank > selected[cell][0]:
            selected[cell] = (rank, row, xy)
    chosen = list(selected.values())
    return (np.array([r[2] for r in chosen]).reshape(-1, 2),
            np.array([r[1][field] for r in chosen]),
            np.array([r[1]['reliability']*math.exp(-r[1]['age']/60) for r in chosen]),
            np.array([r[1]['age'] for r in chosen]))


def estimate(sample, points):
    """Local weighting, expanding to distant observations where necessary."""
    positions, values, reliability, ages = sample
    n = len(positions)
    width = values.shape[1] if values.ndim == 2 else 1
    output = np.full((len(points), width), np.nan)
    counts = np.zeros(len(points), dtype=int)
    nearest = np.full(len(points), np.inf)
    mean_age = np.full(len(points), np.nan)
    if n == 0:
        return output, counts, nearest, mean_age
    dist, idx = cKDTree(positions).query(points, k=min(24, n))
    dist, idx = np.asarray(dist).reshape(len(points),-1), np.asarray(idx).reshape(len(points),-1)
    local = dist <= RADIUS_KM
    counts = local.sum(axis=1)
    nearest = dist[:,0]
    well_supported = (counts >= MIN_SITES) & (nearest <= NEAREST_KM)
    # Always fill every regional grid point if this field has any usable data.
    # Sparse locations use the nearest available stations at any distance;
    # their low-support status is retained rather than hiding the point.
    valid = np.where(well_supported[:,None],local,True)
    safe = idx
    vals = values[safe]
    if vals.ndim == 2:
        vals = vals[..., None]
    masked = np.where(valid[..., None], vals, np.nan)
    # Median-based weights limit the influence of one extreme reading while
    # retaining gradual gradients. These are not MADIS QC flags or validation.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        median = np.nanmedian(masked, axis=1)
        residual = np.linalg.norm(vals-median[:, None, :], axis=2)
        spread = np.nanmedian(np.where(valid, residual, np.nan), axis=1)
    threshold = np.maximum(8. if width == 1 else 10., 3*1.4826*spread)
    robust = 1/np.maximum(1, residual/threshold[:, None])**2
    weight = np.where(valid, reliability[safe]*robust/(dist**2+15**2), 0.)
    weight = np.nan_to_num(weight)
    total = weight.sum(axis=1)
    supported = total > 0
    output[supported] = (weight[..., None]*vals).sum(axis=1)[supported]/total[supported, None]
    mean_age[supported] = (weight*ages[safe]).sum(axis=1)[supported]/total[supported]
    return output, counts, nearest, mean_age


def analyze(rows, target, checked_at, source_status):
    rows = candidates(rows, target)
    if not rows:
        raise ValueError('No observations in the target-hour window; previous analysis retained')
    sw, ne = project([BOUNDS[0], BOUNDS[2]], [BOUNDS[1], BOUNDS[3]])
    xs = np.arange(math.ceil(sw[0]/GRID_KM), math.floor(ne[0]/GRID_KM)+1, dtype=int)
    ys = np.arange(math.ceil(sw[1]/GRID_KM), math.floor(ne[1]/GRID_KM)+1, dtype=int)
    gx, gy = np.meshgrid(xs, ys)
    grid = np.column_stack((gx.ravel(), gy.ravel()))
    points = grid*GRID_KM
    inputs = {field:samples(rows, field) for field in ('tempF', 'dewpointF', 'uv')}
    estimates = {field:estimate(sample, points) for field, sample in inputs.items()}
    plotted = []
    for i, (x, y) in enumerate(points):
        values = {key:result[0][i] for key, result in estimates.items()}
        if not any(np.isfinite(v).all() for v in values.values()):
            continue
        lat, lon = unproject(x,y)
        station = dict(station=f'GRID:{grid[i,0]}:{grid[i,1]}',gx=int(grid[i,0]),gy=int(grid[i,1]),
                       lat=round(lat, 5),lon=round(lon, 5),
                       tempF=round(float(values['tempF'][0]), 1) if np.isfinite(values['tempF']).all() else None,
                       dewpointF=round(float(values['dewpointF'][0]), 1) if np.isfinite(values['dewpointF']).all() else None,
                       wind={},support={},nearestKm={},ageMinutes={},extrapolated={},contributors={})
        if station['tempF'] is not None and station['dewpointF'] is not None:
            station['dewpointF'] = min(station['tempF'], station['dewpointF'])
        if np.isfinite(values['uv']).all():
            u, v = map(float, values['uv'])
            speed = math.hypot(u, v)
            station['wind'] = dict(speedMph=round(speed, 1),speedKnots=round(speed/1.150779, 2),
                                   direction=round(math.degrees(math.atan2(-u, -v)) % 360, 1) if speed >= .5 else None)
        for field, label in [('tempF','temperature'), ('dewpointF','dewpoint'), ('uv','wind')]:
            if not np.isfinite(values[field]).all():
                continue
            result = estimates[field]
            station['support'][label] = int(result[1][i])
            station['nearestKm'][label] = round(float(result[2][i]), 1)
            station['ageMinutes'][label] = round(float(result[3][i]), 1)
            sparse = result[1][i] < MIN_SITES or result[2][i] > NEAREST_KM
            station['extrapolated'][label] = bool(sparse)
            station['contributors'][label] = min(24,len(inputs[field][0])) if sparse else int(result[1][i])
        plotted.append(station)
    if not plotted:
        raise ValueError('Too few nearby independent stations for an analysis')
    counts = Counter(row['provider'] for row in rows)
    source_status = {**source_status,'airports':any(row.get('reportType') == 'METAR' for row in rows),
                     'madis':any(row.get('reportType') != 'METAR' for row in rows)}
    return dict(version=VERSION,analysisTime=iso(target),checkedAt=iso(checked_at),experimental=True,
                bounds=[[BOUNDS[0],BOUNDS[1]],[BOUNDS[2],BOUNDS[3]]],gridKm=GRID_KM,stations=plotted,
                windowStart=iso(target-timedelta(hours=1)),windowEnd=iso(target),sources=source_status,
                stationCount=len(rows),providers=dict(sorted(counts.items())),
                fieldStations={field:len(sample[0]) for field,sample in inputs.items()},
                oldestObservation=min(row['time'] for row in rows),newestObservation=max(row['time'] for row in rows),
                method='Robust distance/age-weighted observations; 5 km declustering; wind u/v components',
                minStations=MIN_SITES,maxNearestKm=NEAREST_KM,maxRadiusKm=RADIUS_KM,
                sparseFallback='Nearest available regional observations; all grid points filled when a variable has any usable data',
                notice='Experimental estimates, not airport observations. Grid spacing does not imply accuracy at that scale.')


def collect(store, now, download=fetch, parse=parse_file):
    now = now.astimezone(UTC)
    target = now.replace(minute=0,second=0,microsecond=0)
    previous = store.read_json(KEY) or {}
    if previous.get('version') == VERSION and previous.get('analysisTime') == iso(target):
        return {'status':'already prepared this hour','analysisTime':iso(target),'points':len(previous['stations'])}
    airport = store.read_json('live/metar-clouds.json') or {}
    rows = [{**row,'provider':'Airport METAR'} for frame in airport.get('history',[]) for row in frame.get('stations',[])]
    status = {'airports':bool(rows),'madis':False,'madisFiles':0}
    errors = []
    # Hourly mesonet files are keyed by observation hour, not retrieval hour.
    for hour in [target-timedelta(hours=1), target]:
        name = hour.strftime('%Y%m%d_%H00.gz')
        try:
            payload, _metadata = download(SOURCE+name)
            parsed = parse(payload, now, window_start=target-timedelta(hours=1),
                           window_end=target+timedelta(seconds=1),bounds=BOUNDS,excluded_stations=())
            rows.extend(parsed)
            status['madisFiles'] += 1
            status['madis'] = status['madis'] or bool(parsed)
        except (OSError, ValueError, EOFError) as error:
            errors.append({'file':name,'error':str(error)[:160]})
    data = analyze(rows, target, now, status)
    data['sourceErrors'] = errors
    store.write_json(KEY, data)
    return {'analysisTime':data['analysisTime'],'points':len(data['stations']),
            'stations':data['stationCount'],'sources':data['sources'],'providers':data['providers']}


if __name__ == '__main__':
    import json
    from realtime import get_store
    store = get_store()
    if store is None:
        raise SystemExit('WEATHER_DATA_BUCKET is required')
    print(json.dumps(collect(store, datetime.now(UTC))), flush=True)
