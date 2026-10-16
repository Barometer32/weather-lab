"""Portable CPU inference and prepared maps for the experimental airport model."""
import base64
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path
import re

import numpy as np
from ai_features import FEATURE_VERSION, LEADS, features, for_lead, predict_ensemble, constrain
from metar_clouds import BOUNDS, in_region
from surface_analysis import FIELDS, PALETTES, grid, image, lines, value

VERSION = 'airport-ai-v2'
BUNDLE = Path(__file__).parent/'ai_bundle'
UTC = timezone.utc


def iso(t):
    return t.isoformat().replace('+00:00','Z')


def stamp(s):
    return datetime.fromisoformat(s.replace('Z','+00:00'))


@lru_cache(maxsize=2)
def local_model():
    return json.loads(gzip.decompress(base64.b64decode((BUNDLE/'model.json.gz.b64').read_text())))


@lru_cache(maxsize=2)
def saved_model(model_id, packed):
    bundle = json.loads(gzip.decompress(packed))
    if bundle.get('modelId')!=model_id:
        raise ValueError('Saved model does not match its manifest')
    return bundle


def load_model(store=None):
    pointer = store.read_json('live/ai-model.json') if store else None
    if pointer and pointer.get('report',{}).get('version')!='airport-ai-v1':
        if not re.fullmatch(r'ai/models/[a-f0-9]{16}\.json\.gz',pointer.get('key','')):
            raise ValueError('Invalid saved model path')
        bundle = saved_model(pointer['modelId'],store.read(pointer['key']))
    else:
        bundle = local_model()
    if bundle.get('version')!=VERSION or bundle.get('featureVersion')!=FEATURE_VERSION:
        raise ValueError('Unsupported experimental model version')
    return bundle


def status(store=None):
    training = store.read_json('live/ai-status.json') if store else None
    if training and training.get('state')=='completed' and store:
        pointer = store.read_json('live/ai-model.json') or {}
        if pointer.get('report',{}).get('version')=='airport-ai-v1':
            training = None  # The regional bundle supersedes the old pilot.
    if training is None:
        training = json.loads((BUNDLE/'status.json').read_text()) if (BUNDLE/'status.json').exists() else {
            'state':'not-started','stage':'not-started','percent':0,'message':'Model has not been trained yet'}
    if training.get('state')=='running' and training.get('updatedAt'):
        training = dict(training)
        if (datetime.now(UTC)-stamp(training['updatedAt'])).total_seconds()>1800:
            training.update(state='interrupted',message='No training progress for over 30 minutes; check the private job logs',estimatedRemainingSeconds=None)
    return training


def live_inputs(observations,bundle):
    hour = stamp(observations['hour'])
    hours = np.arange(int(hour.timestamp()/3600)-11,int(hour.timestamp()/3600)+1)
    # The regional pooled model forecasts the actual live airport network,
    # including airports that were not supervised training targets.
    metadata = {}
    for frame in observations.get('history',[]):
        for row in frame.get('stations',[]):
            if in_region(row):
                station = row['station'].removeprefix('K') if row['station'].startswith('K') and len(row['station'])==4 else row['station']
                metadata[station] = {'station':station,'icaoId':row['station'],'lat':row['lat'],'lon':row['lon']}
    stations = [metadata[s] for s in sorted(metadata)]
    indexes = {s['station']:i for i,s in enumerate(stations)}
    values = np.full((12,len(stations),4),np.nan); pressure = np.full((12,len(stations)),np.nan)
    latest_reports = []
    for frame in observations.get('history',[]):
        index = int(stamp(frame['hour']).timestamp()/3600)-hours[0]
        if not 0<=index<12:
            continue
        for row in frame.get('stations',[]):
            station = row['station'].removeprefix('K') if row['station'].startswith('K') and len(row['station'])==4 else row['station']
            if station not in indexes:
                continue
            si = indexes[station]
            for ti,field in enumerate(('tempF','dewpointF')):
                v = value(row,field)
                if v is not None:
                    values[index,si,ti] = v
            wind = value(row,'wind')
            if wind is not None:
                values[index,si,2:4] = wind
            found = re.search(r'\bA(\d{4})\b',row.get('rawOb',''))
            if found and 2600<=int(found[1])<=3300:
                pressure[index,si] = int(found[1])/100
            if index==11:
                latest_reports.append(row['time'])
    return hours,stations,values,pressure,latest_reports


def predict(observations,bundle):
    hours,stations,values,pressure,latest_reports = live_inputs(observations,bundle)
    if np.isfinite(values[-1,:,0]).sum()<8:
        raise ValueError('Fewer than eight eligible airports have current temperature reports')
    now_values = values[-1]
    base,names = features(hours,stations,values,pressure,0)
    base = base[-len(stations):]
    if names!=bundle['report']['features']:
        raise ValueError('Model feature order differs from training')
    frames = []
    for lead in LEADS:
        x = for_lead(base,np.full(len(stations),hours[-1]),names,lead)
        spec = bundle['leads'][str(lead)]
        delta = np.column_stack([predict_ensemble(m,x) for m in bundle['sharedModels']])
        # Apply constraints before blending, exactly as in validation/testing.
        raw = constrain(now_values+delta)
        prediction = constrain(now_values+np.asarray(spec['alpha'])*(raw-now_values))
        valid_at = stamp(observations['hour'])+timedelta(hours=lead)
        rows = []
        for i,station in enumerate(stations):
            p = prediction[i]; speed = float(np.linalg.norm(p[2:4]))
            finite = lambda n: round(float(n),3) if np.isfinite(n) else None
            if not np.isfinite(p).any():
                continue
            rows.append({'station':station['icaoId'],'stationKey':'AI:'+station['station'],
                'network':'EXPERIMENTAL_AI','lat':station['lat'],'lon':station['lon'],
                'time':iso(valid_at),'tempF':finite(p[0]),'dewpointF':finite(p[1]),
                'wind':{'speedMph':finite(speed),'direction':round(float(np.degrees(np.arctan2(-p[2],-p[3]))%360),2) if math.isfinite(speed) else None},
                'product':'forecast','modelId':bundle['modelId']})
        frames.append({'hour':iso(valid_at),'leadHours':lead,'stations':rows})
    return frames,latest_reports


def render(frame,store,prefix):
    result = {'hour':frame['hour'],'leadHours':frame['leadHours'],'bounds':BOUNDS,'fields':{}}
    for field in FIELDS:
        coverage = {}
        lons,lats,z,u,v,used = grid(frame['stations'],field,coverage=coverage)
        image_key = prefix+'/'+field+'.png'
        store.write(image_key,image(z,PALETTES[field],banded=True),'image/png')
        arrows = []
        if field=='wind':
            for iy in range(4,len(lats),8):
                for ix in range(4,len(lons),8):
                    if np.isfinite(z[iy,ix]) and z[iy,ix]>=.5:
                        arrows.append({'lat':round(float(lats[iy]),4),'lon':round(float(lons[ix]),4),
                            'speed':round(float(z[iy,ix]),1),
                            'direction':round(float(np.degrees(np.arctan2(-u[iy,ix],-v[iy,ix]))%360),1)})
        result['fields'][field] = {'imageUrl':'/api/prepared/'+image_key,'palette':PALETTES[field],
            'contours':{'type':'FeatureCollection','features':lines(lons,lats,z,5)},'arrows':arrows,
            'used':used,'supportedCells':int(np.isfinite(z).sum()),'coverage':coverage}
    key = prefix+'/manifest.json';store.write_json(key,result)
    return '/api/prepared/'+key


def prepare(store,observations,now):
    bundle = load_model(store)
    previous = store.read_json('live/ai-forecast.json') or {}
    # Observation contents can be corrected within the same hourly label.
    import hashlib
    signature = hashlib.sha256(json.dumps(observations.get('history',[]),sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
    if previous.get('modelId')==bundle['modelId'] and previous.get('inputSignature')==signature:
        return {'status':'already prepared','issueHour':previous['issueHour']}
    store.write_json('live/ai-forecast-status.json',{'state':'running','updatedAt':iso(now),'message':'Preparing 24 hourly forecasts'})
    frames,latest_reports = predict(observations,bundle)
    saved = []
    label = stamp(observations['hour']).strftime('%Y%m%d%H%M')
    for frame in frames:
        prefix = f"ai/forecast-v2/{label}/{bundle['modelId']}/{signature}/{frame['leadHours']:02}"
        url = render(frame,store,prefix)
        saved.append({'hour':frame['hour'],'leadHours':frame['leadHours'],'stationCount':len(frame['stations']),'analysisUrl':url})
    # Keep numerical forecasts as issued for later prospective verification.
    # These records never replace, or enter, the observation collection.
    store.write_json(f"ai/issued/{label}/{bundle['modelId']}-{signature}.json",{
        'modelId':bundle['modelId'],'issueHour':observations['hour'],'generatedAt':iso(now),
        'latestReportTime':max(latest_reports) if latest_reports else None,'frames':frames})
    result = {'version':VERSION,'modelId':bundle['modelId'],'inputSignature':signature,
        'issueHour':observations['hour'],'generatedAt':iso(now),'inputCheckedAt':observations['checkedAt'],
        'latestReportTime':max(latest_reports) if latest_reports else None,
        'history':saved,'modelReport':bundle['report']}
    # Publish only after all 24 immutable products are complete.
    store.write_json('live/ai-forecast.json',result)
    store.write_json('live/ai-forecast-status.json',{'state':'completed','updatedAt':iso(now),'message':'All 24 hourly forecasts ready'})
    return {'status':'prepared','issueHour':observations['hour'],'frames':len(saved)}
