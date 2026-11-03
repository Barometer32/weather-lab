"""Shared 30-minute MN/WI observations; local 5-km-grid analysis on demand.

All downloads run in the private collector. A page request evaluates only four
nearby grid nodes using up to five QC-passing stations per measurement. Grid
spacing is not a claim of sensor spacing or measurement accuracy.
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial import cKDTree
from regional_madis import fetch, parse_file, iso

UTC=timezone.utc
KEY='live/current-analysis.json'
VERSION='current-mnwi-v1'
FAMILIES=('mesonet','rwis','hfmetar')
AWC='https://aviationweather.gov/data/cache/metars.cache.xml.gz'
BOUNDS=(42.45,-97.25,49.45,-86.2)
WINDOW_MINUTES=30
GRID_KM=5
MAX_RADIUS_KM=80
MAX_NEAREST_KM=35
MAX_STATIONS=5


def stamp(value):
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Observation time must have a timezone')
    return value.astimezone(UTC)


def number(value,low,high):
    if isinstance(value,bool):return None
    try:
        value=float(value)
        return value if math.isfinite(value) and low<=value<=high else None
    except (ValueError,TypeError):return None


@lru_cache(maxsize=1)
def state_rings():
    data=json.loads((Path(__file__).parent/'mn_wi_states.geojson').read_text())
    return [(f['properties']['STUSAB'],f['geometry']['coordinates']) for f in data['features']]


def in_ring(x,y,ring):
    inside=False
    for i,(x1,y1) in enumerate(ring):
        x2,y2=ring[i-1]
        if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1:inside=not inside
    return inside


def state_for(lat,lon):
    if not BOUNDS[0]<=lat<=BOUNDS[2] or not BOUNDS[1]<=lon<=BOUNDS[3]:return None
    for state,rings in state_rings():
        if in_ring(lon,lat,rings[0]) and not any(in_ring(lon,lat,r) for r in rings[1:]):return state
    return None


def coordinates(lat,lon):
    lat=number(lat,-85,85);lon=number(lon,-180,180)
    if lat is None or lon is None:raise ValueError('Select valid latitude and longitude.')
    return round(lat,5),round(lon,5)


def airport_rows(payload,now):
    content=gzip.decompress(payload)
    if len(content)>40_000_000:raise ValueError('Airport cache exceeds expected size')
    rows=[]
    for entry in ET.fromstring(content).iter('METAR'):
        get=entry.findtext
        try:
            observed=stamp(get('observation_time'));lat,lon=coordinates(get('latitude'),get('longitude'))
        except (ValueError,TypeError,AttributeError):continue
        if not now-timedelta(minutes=WINDOW_MINUTES)<=observed<=now or not state_for(lat,lon):continue
        temp=number(get('temp_c'),-90,60);dew=number(get('dewpoint_c'),-100,60)
        speed=number(get('wind_speed_kt'),0,200);direction=number(get('wind_dir_degrees'),0,360)
        rows.append(dict(station=get('station_id'),name=get('station_id'),lat=lat,lon=lon,time=iso(observed),
            source='NOAA Aviation Weather Center',network='Airport METAR',provider='AWC',
            tempF=temp*1.8+32 if temp is not None else None,dewpointF=dew*1.8+32 if dew is not None else None,
            wind=dict(speedMph=speed*1.15077945 if speed is not None else None,direction=direction),qcBasis='Reported airport observation; local checks'))
    return rows


def latest(rows,now):
    selected={}
    for original in rows:
        try:
            observed=stamp(original['time']);lat,lon=coordinates(original['lat'],original['lon'])
            if not now-timedelta(minutes=WINDOW_MINUTES)<=observed<=now or not state_for(lat,lon):continue
            station=str(original['station']).strip()
            if not station:continue
            row={k:original.get(k) for k in ('station','name','time','source','provider','network','tempF','dewpointF','qcBasis')}
            row.update(lat=lat,lon=lon,wind=dict(original.get('wind') or {}))
            row['tempF']=number(row['tempF'],-130,140);row['dewpointF']=number(row['dewpointF'],-148,140)
            if row['dewpointF'] is not None and row['tempF'] is not None and row['dewpointF']>row['tempF']+1:
                row['dewpointF']=None
            row['wind']['speedMph']=number(row['wind'].get('speedMph'),0,230)
            row['wind']['direction']=number(row['wind'].get('direction'),0,360)
            if not any(v is not None for v in (row['tempF'],row['dewpointF'],row['wind']['speedMph'])):continue
            key=(station,round(lat,3),round(lon,3))
            # A QC revision for an equal timestamp replaces its predecessor.
            if key not in selected or observed>=stamp(selected[key]['time']):selected[key]=row
        except (ValueError,TypeError,KeyError,AttributeError):continue
    physical={};identities={}
    for row in sorted(selected.values(),key=lambda r:(r['time'],r.get('provider')!='AWC'),reverse=True):
        # Airport coordinates can differ between feeds by hundreds of metres.
        # Match the same identifier locally as well as matching physical pins.
        identity=row['station'][1:] if len(row['station'])==4 and row['station'].startswith('K') else row['station']
        previous=identities.setdefault(identity,[])
        if any(((row['lat']-old['lat'])*111.195)**2+((row['lon']-old['lon'])*78.6)**2<=4 for old in previous):continue
        previous.append(row)
        # ~20 m: prevent a redistributed physical sensor receiving two votes.
        key=(round(row['lat']*5000),round(row['lon']*5000))
        physical.setdefault(key,row)
    return list(physical.values())


def spatial_qc(rows):
    """Flag isolated T/Td outliers only with a consistent, contemporaneous quorum."""
    if len(rows)<6:return rows,0
    xy=np.array([[r['lon']*78.6,r['lat']*111.195] for r in rows]);tree=cKDTree(xy)
    times=np.array([stamp(r['time']).timestamp() for r in rows]);rejected=0
    flags=[]
    for field in ('tempF','dewpointF'):
        values=np.array([r.get(field) if r.get(field) is not None else np.nan for r in rows],dtype=float)
        for i,peers in enumerate(tree.query_ball_point(xy,25)):
            if not np.isfinite(values[i]):continue
            peers=[j for j in peers if j!=i and np.isfinite(values[j]) and abs(times[j]-times[i])<=600]
            if len(peers)<5:continue
            center=float(np.median(values[peers]));mad=float(np.median(np.abs(values[peers]-center)))
            threshold=max(12.,5*1.4826*mad)
            if abs(values[i]-center)>threshold:flags.append((i,field))
    for i,field in flags:
        rows[i][field]=None;rows[i].setdefault('localQCRejected',[]).append(field);rejected+=1
    return rows,rejected


def collect(store,now,download=None):
    now=now.astimezone(UTC);download=download or (lambda url,old:fetch(url,old,timeout=20))
    rows=[];errors=[];pending=[];good=0
    hour=now.replace(minute=0,second=0,microsecond=0)
    offsets=(0,1) if now.minute<30 else (0,)
    for family in FAMILIES:
        for offset in offsets:
            name=(hour-timedelta(hours=offset)).strftime('%Y%m%d_%H00.gz')
            key=f'live/current-input-{family}-{offset}.json'
            old=store.read_json(key) or {}
            if old.get('file')!=name or old.get('version')!=VERSION:old={}
            try:
                payload,metadata=download(f'https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/{family}/netCDF/{name}',old.get('metadata'))
                if payload is not None:
                    parsed=parse_file(payload,now,bounds=BOUNDS,window_start=hour-timedelta(hours=1),
                        window_end=now+timedelta(seconds=1),excluded_stations=(),sensor_status_checks=True,derive_dewpoint=True)
                    for row in parsed:row['qcBasis']='MADIS field QC plus local checks'
                    old=dict(version=VERSION,file=name,metadata=metadata,stations=latest(parsed,now))
                    store.write_json(key,old)
                rows.extend(old.get('stations',[]));good+=1
            except Exception as error:
                if isinstance(error,HTTPError) and error.code==404 and offset==0:pending.append(family)
                else:errors.append(dict(feed=family,file=name,error=str(error)[:160]))
                rows.extend(old.get('stations',[]))
    key='live/current-input-airports.json';old=store.read_json(key) or {}
    try:
        payload,metadata=download(AWC,old.get('metadata'))
        if payload is not None:
            old=dict(metadata=metadata,stations=airport_rows(payload,now));store.write_json(key,old)
        rows.extend(old.get('stations',[]));good+=1
    except Exception as error:
        rows.extend(old.get('stations',[]));errors.append(dict(feed='airports',error=str(error)[:160]))
    if not good:raise ValueError('All current observation feeds failed; prior snapshot retained')
    stations,rejected=spatial_qc(latest(rows,now))
    # An empty but successful collection must clear expired observations.
    data=dict(version=VERSION,checkedAt=iso(now),windowStart=iso(now-timedelta(minutes=30)),windowEnd=iso(now),
        windowMinutes=30,gridSpacingKm=GRID_KM,stations=stations,errors=errors,pendingFiles=pending,
        localRejectedFields=rejected,region=['MN','WI'],source='Public NOAA MADIS mesonet, RWIS, high-frequency airports and AWC METAR')
    store.write_json(KEY,data)
    return data


def haversine(lat,lon,lats,lons):
    y1,y2=np.radians(lat),np.radians(lats);dy=y2-y1;dx=np.radians(lons-lon)
    a=np.sin(dy/2)**2+np.cos(y1)*np.cos(y2)*np.sin(dx/2)**2
    return 6371*2*np.arcsin(np.sqrt(np.clip(a,0,1)))


def airport_wind_site(row):
    return (str(row.get('provider','')).upper() in ('AWC','HF-METAR')
            or str(row.get('network','')).upper() in ('AIRPORT METAR','HF-METAR'))


def analysis(data,lat,lon,now):
    lat,lon=coordinates(lat,lon)
    result=dict(latitude=lat,longitude=lon,estimated=True,available=False,gridSpacingKm=GRID_KM,
        windowMinutes=30,windPolicy='airports-only-v1',checkedAt=data.get('checkedAt'),serverTime=iso(now),fields={},stations=[],
        sourceErrors=data.get('errors',[]),stale=not data.get('checkedAt') or now-stamp(data['checkedAt'])>timedelta(minutes=12))
    if not state_for(lat,lon):
        result['message']='Current analysis covers Minnesota and Wisconsin. Select a location in either state.';return result
    rows=latest(data.get('stations',[]),now)
    if not rows:
        result['message']='No observations from the last 30 minutes are available yet.';return result
    distances=haversine(lat,lon,np.array([r['lat'] for r in rows]),np.array([r['lon'] for r in rows]))
    ids=np.flatnonzero(distances<=MAX_RADIUS_KM+GRID_KM*2)
    rows=[rows[i] for i in ids];distances=distances[ids]
    if not rows:
        result['message']='No recent stations near this location.';return result
    # A fixed MN/WI metric grid; only the four nodes around a selected point
    # are evaluated. No all-state grid transfer or browser interpolation.
    xscale=111.195*math.cos(math.radians(46));x=lon*xscale;y=lat*111.195
    gx=math.floor(x/GRID_KM)*GRID_KM;gy=math.floor(y/GRID_KM)*GRID_KM
    fx=(x-gx)/GRID_KM;fy=(y-gy)/GRID_KM
    nodes=[(gx,gy,(1-fx)*(1-fy)),(gx+GRID_KM,gy,fx*(1-fy)),(gx,gy+GRID_KM,(1-fx)*fy),(gx+GRID_KM,gy+GRID_KM,fx*fy)]
    ages=np.array([(now-stamp(r['time'])).total_seconds()/60 for r in rows])
    source_weight=np.array([.65 if r.get('network')=='CWOP' else 1 for r in rows])
    # Nearby dense networks should not outweigh the whole surrounding area.
    xy=np.array([[r['lon']*xscale,r['lat']*111.195] for r in rows]);tree=cKDTree(xy)
    density=np.array([len(v) for v in tree.query_ball_point(xy,2)])
    base=np.exp(-ages/30)*source_weight/np.sqrt(np.maximum(1,density))
    airports=np.array([airport_wind_site(row) for row in rows],dtype=bool)
    wind_base=np.exp(-ages/30)
    airport_indices=np.flatnonzero(airports)
    if len(airport_indices):
        airport_xy=xy[airport_indices]
        airport_density=np.array([len(v) for v in cKDTree(airport_xy).query_ball_point(airport_xy,2)])
        wind_base[airport_indices]/=np.sqrt(np.maximum(1,airport_density))
    temperatures=np.array([r['tempF'] if r['tempF'] is not None else np.nan for r in rows])
    dews=np.array([r['dewpointF'] if r['dewpointF'] is not None else np.nan for r in rows])
    speeds=np.array([r['wind']['speedMph'] if r['wind']['speedMph'] is not None else np.nan for r in rows])
    directions=np.array([r['wind']['direction'] if r['wind']['direction'] is not None else np.nan for r in rows])
    directions[speeds==0]=0
    u=-speeds*np.sin(np.radians(directions));v=-speeds*np.cos(np.radians(directions))
    supports=[]
    def estimate(values,valid=None,base_weights=None):
        valid=np.isfinite(values) if valid is None else valid
        candidates=sorted(np.flatnonzero(valid&(distances<=MAX_RADIUS_KM)),key=lambda i:distances[i])[:MAX_STATIONS]
        support=np.zeros(len(rows));total=0.
        if len(candidates)<3 or distances[candidates[0]]>MAX_NEAREST_KM:return None,support
        candidates=np.array(candidates)
        for nx,ny,blend in nodes:
            if blend<1e-10:continue
            d=haversine(ny/111.195,nx/xscale,np.array([rows[i]['lat'] for i in candidates]),np.array([rows[i]['lon'] for i in candidates]))
            weights=(base if base_weights is None else base_weights)[candidates]/(d+2)**2
            weights/=weights.sum();total+=blend*float(np.dot(weights,values[candidates]));support[candidates]+=blend*weights
        return total,support
    def field(name,value,support):
        if value is None:result['fields'][name]=dict(value=None,stationCount=0);return
        used=np.flatnonzero(support>0);times=[rows[i]['time'] for i in used]
        representative=sum(stamp(rows[i]['time']).timestamp()*support[i] for i in used)/support.sum()
        result['fields'][name]=dict(value=round(value,2),stationCount=len(used),observationStart=min(times),observationEnd=max(times),
            representativeTime=iso(datetime.fromtimestamp(representative,UTC)),nearestKm=round(float(distances[used].min()),1))
        supports.append(support)
    temperature,ts=estimate(temperatures);dewpoint,ds=estimate(dews)
    field('temperatureF',temperature,ts)
    field('dewpointF',min(dewpoint,temperature) if dewpoint is not None and temperature is not None else dewpoint,ds)
    valid=airports&np.isfinite(u)&np.isfinite(v)
    ue,us=estimate(u,valid,wind_base);ve,vs=estimate(v,valid,wind_base)
    speed=math.hypot(ue,ve) if ue is not None and ve is not None else None
    field('windMph',speed,us)
    result['fields']['windMph']['sourcePolicy']='airports-only-v1'
    if speed is None:result['windMessage']='Wind unavailable: at least three recent usable airport reports are needed nearby.'
    result['windDirection']=(math.degrees(math.atan2(-ue,-ve))%360) if speed is not None and speed>=.5 else None
    result['available']=any(f['value'] is not None for f in result['fields'].values())
    if supports:
        used=np.flatnonzero(np.maximum.reduce(supports)>0)
        result.update(stationCount=len(used),observationStart=min(rows[i]['time'] for i in used),observationEnd=max(rows[i]['time'] for i in used))
        for i in sorted(used,key=lambda i:distances[i]):
            usage={name:round(float(s[i])*100,1) for name,s in [('temperature',ts),('dewpoint',ds),('wind',us)] if s[i]>0}
            result['stations'].append(dict(**rows[i],distanceKm=round(float(distances[i]),1),weightsPct=usage))
        weakest=min(f['stationCount'] for f in result['fields'].values() if f['value'] is not None)
        farthest_nearest=max(f['nearestKm'] for f in result['fields'].values() if f['value'] is not None)
        result['confidence']='limited' if weakest<5 or farthest_nearest>15 else 'normal'
        result['message']='Limited nearby station support; this is a broader-area estimate.' if result['confidence']=='limited' else ''
    else:result['message']='Each value needs at least three recent usable stations within 80 km, including one within 35 km.'
    return result


def main():
    from realtime import get_store
    store=get_store()
    if store is None:raise ValueError('WEATHER_DATA_BUCKET is required')
    data=collect(store,datetime.now(UTC))
    if not data['stations']:raise ValueError('No recent MN/WI observations available for the initial setup')
    print(json.dumps(dict(stations=len(data['stations']),checkedAt=data['checkedAt'],sourceErrors=data['errors'])),flush=True)


if __name__=='__main__':main()
