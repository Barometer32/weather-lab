"""Twelve hours at one selected point, using real archived MADIS reports.

Archives contain shared station reports; no personal travel history is created.
Historical estimates use observation timestamps, not the time reports arrived.
"""
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
import gzip
import json
import math
import re
import threading
import time

from regional_madis import fetch, parse_file, iso

VERSION = 'public-hourly-reports-v1'
PREFIX = 'test-history/v1/'
FAMILIES = ('mesonet','rwis','hfmetar')
_FIELDS = ('station','lat','lon','time','tempF','dewpointF','speedMph','direction','network','provider')
_history_lock = threading.Lock()


def archive_key(family, hour):
    if family not in FAMILIES:
        raise ValueError('Unknown TEST history feed')
    return PREFIX+hour.strftime('%Y%m%d_%H00')+'/'+family+'.jsonl.gz'


def save_archive(store, family, hour, rows):
    from io import BytesIO
    buffer=BytesIO()
    # Stream records instead of holding a second national array and JSON string.
    with gzip.GzipFile(fileobj=buffer,mode='wb',compresslevel=3,mtime=0) as output:
        output.write((json.dumps({'version':VERSION,'fields':_FIELDS},separators=(',',':'))+'\n').encode())
        for row in rows:
            wind=row.get('wind') or {}
            packed=[row.get('station'),row['lat'],row['lon'],row['time'],row.get('tempF'),row.get('dewpointF'),
                    wind.get('speedMph'),wind.get('direction'),row.get('network'),row.get('provider')]
            output.write((json.dumps(packed,separators=(',',':'),allow_nan=False)+'\n').encode())
    store.write(archive_key(family,hour),buffer.getvalue(),'application/gzip')


def nearby_archive(payload, lat, lon, start, end):
    if not payload:return []
    from point_weather import stamp
    from io import BytesIO
    lat_delta=100/111
    lon_delta=min(180,100/(111*math.cos(math.radians(min(89,abs(lat)+1)))))
    result=[]
    with gzip.GzipFile(fileobj=BytesIO(payload)) as source:
        header=json.loads(source.readline(4096))
        if header.get('version')!=VERSION or tuple(header.get('fields',[]))!=_FIELDS:
            raise ValueError('Unsupported TEST history format')
        total=0
        while True:
            line=source.readline(8193)
            if not line:break
            total+=len(line)
            if len(line)>8192 or total>200_000_000:
                raise ValueError('TEST history file exceeds expected size')
            row=json.loads(line)
            if len(row)!=10:continue
            if abs(row[1]-lat)>lat_delta or abs((row[2]-lon+180)%360-180)>lon_delta:continue
            if not start<=stamp(row[3])<=end:continue
            result.append({'station':row[0],'name':row[0],'lat':row[1],'lon':row[2],'time':row[3],
                           'tempF':row[4],'dewpointF':row[5],'wind':{'speedMph':row[6],'direction':row[7]},
                           'network':row[8],'provider':row[9],'source':'NOAA MADIS archived observations'})
    return result


def backfill(store, now, hours=14, download=None):
    """One-time seed only. Ordinary five-minute checks never fetch 12 hours."""
    download=download or (lambda url:fetch(url,timeout=20)[0])
    hour=now.replace(minute=0,second=0,microsecond=0)
    prepared, errors=0,[]
    for offset in range(hours):
        target=hour-timedelta(hours=offset)
        name=target.strftime('%Y%m%d_%H00.gz')
        for family in FAMILIES:
            key=archive_key(family,target)
            exists=store.exists(key) if hasattr(store,'exists') else store.read(key) is not None
            if exists:continue
            try:
                payload=download('https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/'+family+'/netCDF/'+name)
                rows=parse_file(payload,now,bounds=(-85,-180,85,180),window_start=target,
                                window_end=min(now+timedelta(seconds=1),target+timedelta(hours=1)),
                                excluded_stations=(),sensor_status_checks=True,derive_dewpoint=True)
                save_archive(store,family,target,rows)
                prepared+=1
                print('History prepared: '+name+' '+family+' · '+str(len(rows))+' reports',flush=True)
            except Exception as error:
                errors.append({'file':name,'feed':family,'error':str(error)[:120]})
                print('History unavailable: '+name+' '+family+' · '+str(error)[:120],flush=True)
    return {'preparedFiles':prepared,'unavailableFiles':errors}


def prune(store, now):
    """Retain at most about a day of shared TEST history; touch no other keys."""
    if not hasattr(store,'list_keys') or not hasattr(store,'delete'):return
    previous=store.read_json('live/test-history-cleanup.json') or {}
    if previous.get('hour')==now.strftime('%Y%m%d%H'):return
    cutoff=now-timedelta(hours=24)
    for key in store.list_keys(PREFIX):
        match=re.fullmatch(re.escape(PREFIX)+r'(\d{8}_\d{2})00/(mesonet|rwis|hfmetar)\.jsonl\.gz',key)
        if match and datetime.strptime(match[1],'%Y%m%d_%H').replace(tzinfo=timezone.utc)<cutoff:
            store.delete(key)
    store.write_json('live/test-history-cleanup.json',{'hour':now.strftime('%Y%m%d%H')})


def history(store, data, lat, lon, now):
    from point_weather import analysis, coordinates
    lat,lon=coordinates(lat,lon)
    start=now-timedelta(hours=12,minutes=30)
    hour=now.replace(minute=0,second=0,microsecond=0)
    rows, missing, failures=[],0,0
    for offset in range(14):
        target=hour-timedelta(hours=offset)
        for family in FAMILIES:
            try:
                payload=store.read(archive_key(family,target))
                if payload is None:missing+=1;continue
                rows.extend(nearby_archive(payload,lat,lon,start,now))
            except Exception:
                failures+=1
    frames=[]
    historical={'checkedAt':data['checkedAt'],'stations':rows,'errors':[]}
    for offset in reversed(range(1,13)):
        target=now-timedelta(hours=offset)
        value=analysis(historical,lat,lon,target)
        value.update(time=iso(target),historical=True)
        frames.append(value)
    live=analysis(data,lat,lon,now)
    live.update(time=iso(now),historical=False)
    frames.append(live)
    return {'version':VERSION,'latitude':lat,'longitude':lon,'windowStart':iso(now-timedelta(hours=12)),
            'windowEnd':iso(now),'checkedAt':data['checkedAt'],'observationWindowMinutes':30,
            'sampleIntervalMinutes':60,'frames':frames,'missingArchiveFiles':missing,'archiveReadErrors':failures,
            'availableFrames':sum(frame['available'] for frame in frames),
            'method':'Current estimate plus 12 hourly samples, each using reports from its preceding 30 minutes. Historical values are recalculated from archived observation times and can include late-arriving reports.'}


_history_cache = OrderedDict()


def get_history(store,lat,lon,now,checked_at):
    # One national-file decoding request at a time keeps phone refreshes from
    # multiplying server memory. Current conditions/forecast remain independent.
    if not _history_lock.acquire(timeout=1):
        raise ValueError('Another history point is loading. Please retry shortly.')
    try:
        key=(store,lat,lon,int(now.timestamp()//300),checked_at)
        if key in _history_cache:
            _history_cache.move_to_end(key)
            return _history_cache[key]
        data=store.read_json('live/test-weather.json')
        if not data:raise ValueError('TEST observations are not prepared')
        result=history(store,data,lat,lon,now)
        _history_cache[key]=result
        while len(_history_cache)>12:_history_cache.popitem(last=False)
        return result
    finally:_history_lock.release()
