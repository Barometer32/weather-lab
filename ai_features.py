"""Shared causal feature construction for training and hourly inference."""
import math
import numpy as np

FEATURE_VERSION = 'airport-features-v1'
LEADS = (1, 3, 6, 12, 24)
LAGS = (0, 1, 3, 6, 9)
TARGETS = ('tempF', 'dewpointF', 'uMph', 'vMph')


def lag(values, hours):
    if not hours:
        return values.copy()
    shifted = np.full_like(values, np.nan)
    shifted[hours:] = values[:-hours]
    return shifted


def make_arrays(rows, stations):
    metadata = {r['station']: {'station': r['station'], 'lat': r['lat'], 'lon': r['lon']} for r in rows}
    stations = [metadata[s] for s in stations if s in metadata]
    hours = np.arange(min(r['hour'] for r in rows), max(r['hour'] for r in rows)+1)
    values = np.full((len(hours), len(stations), 4), np.nan)
    pressure = np.full((len(hours), len(stations)), np.nan)
    index = {s['station']: i for i,s in enumerate(stations)}
    for r in rows:
        if r['station'] not in index:
            continue
        ti, si = r['hour']-hours[0], index[r['station']]
        values[ti, si] = [np.nan if x is None else x for x in r['values']]
        pressure[ti, si] = r['altimeter'] if r.get('altimeter') is not None else np.nan
    return hours, stations, values, pressure


def features(hours, stations, values, pressure, lead):
    """Every feature uses issue-time or earlier values, never future reports."""
    h, n, _ = values.shape
    parts, names = [], []
    for offset in LAGS:
        parts.append(lag(values, offset)); names.extend(f'{key}_lag{offset}' for key in TARGETS)
    lat = np.array([s['lat'] for s in stations]); lon = np.array([s['lon'] for s in stations])
    xy = np.column_stack((lon*111.2*math.cos(math.radians(45)), lat*111.2))
    distance = np.linalg.norm(xy[:,None]-xy[None,:], axis=2)
    np.fill_diagonal(distance, np.inf)
    weights = np.where(distance <= 350, 1/np.maximum(distance, 10), 0)
    # At most five nearby airports per site; missing neighbors cannot vote.
    order = np.argsort(distance, axis=1)
    mask = np.zeros_like(weights, dtype=bool)
    for i in range(n):
        mask[i, order[i, :min(5,n-1)]] = True
    weights *= mask
    for label, inputs in [('neighbors', values), ('neighborChange3', values-lag(values,3))]:
        good = np.isfinite(inputs)
        numerator = np.einsum('ij,tjk->tik', weights, np.where(good, inputs, 0))
        denominator = np.einsum('ij,tjk->tik', weights, good.astype(float))
        parts.append(np.divide(numerator, denominator, out=np.full_like(numerator,np.nan), where=denominator>0))
        names.extend(f'{label}_{key}' for key in TARGETS)
    for label, inputs in [('altimeter',pressure),('pressureChange3',pressure-lag(pressure,3)),('pressureChange6',pressure-lag(pressure,6))]:
        parts.append(inputs[:,:,None]); names.append(label)
    day = hours/24
    calendar = np.column_stack((np.sin(2*np.pi*(hours%24)/24),np.cos(2*np.pi*(hours%24)/24),
        np.sin(2*np.pi*((hours+lead)%24)/24),np.cos(2*np.pi*((hours+lead)%24)/24),
        np.sin(2*np.pi*day/365.2425),np.cos(2*np.pi*day/365.2425)))
    parts.append(np.broadcast_to(calendar[:,None,:],(h,n,6)))
    names.extend(('issueHourSin','issueHourCos','validHourSin','validHourCos','seasonSin','seasonCos'))
    parts.append(np.broadcast_to(np.column_stack((lat,lon))[None,:,:],(h,n,2)))
    names.extend(('lat','lon'))
    return np.concatenate(parts,axis=2).reshape(h*n,-1), names


def predict_tree(tree, x):
    # Nodes: [feature, threshold, left, right, missing_go_left, value]. Leaves
    # have feature=-1. These plain numeric trees never execute pickled code.
    nodes = np.asarray(tree,dtype=float)
    current = np.zeros(len(x),dtype=int)
    for _ in range(len(nodes)+1):
        node = nodes[current]; active = node[:,0]>=0
        if not active.any():
            return node[:,5]
        rows = np.flatnonzero(active); a = node[active]
        inputs = x[rows,a[:,0].astype(int)]
        left = np.where(np.isnan(inputs),a[:,4].astype(bool),inputs<=a[:,1])
        current[rows] = np.where(left,a[:,2],a[:,3]).astype(int)
    raise ValueError('Invalid model tree')


def predict_ensemble(model, x):
    result = np.full(len(x),model['baseline'],dtype=float)
    for tree in model['trees']:
        result += predict_tree(tree,x)
    return result


def constrain(prediction):
    result = prediction.copy()
    result[:,0] = np.clip(result[:,0],-100,130)
    result[:,1] = np.clip(result[:,1],-120,100)
    result[:,1] = np.where(np.isfinite(result[:,0]),np.minimum(result[:,1],result[:,0]),result[:,1])
    speed = np.linalg.norm(result[:,2:4],axis=1)
    factor = np.minimum(1,115/np.maximum(speed,1))
    result[:,2:4] *= factor[:,None]
    return result
