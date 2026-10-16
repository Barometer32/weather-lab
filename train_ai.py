"""Train the bounded CPU-only pilot. No training runs on public HTTP requests."""
import os
for _name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(_name,'2')

import argparse
from datetime import datetime, timezone
import base64
import gzip
import hashlib
import json
from pathlib import Path
import signal
import time

import numpy as np
from ai_data import STATIONS, download_history
from ai_features import FEATURE_VERSION, LEADS, TARGETS, make_arrays, features, predict_ensemble, constrain

UTC = timezone.utc
VERSION = 'airport-ai-v2'


def iso_now():
    return datetime.now(UTC).isoformat().replace('+00:00','Z')


class Progress:
    def __init__(self, path, store=None):
        self.path = Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.store = store; self.started = time.monotonic(); self.stage = None
        self.history = []; self.stage_started = self.started

    def __call__(self, stage, percent, message, **extra):
        if stage != self.stage:
            self.stage = stage; self.stage_started = time.monotonic()
        elapsed = time.monotonic()-self.started
        current = {'state': 'completed' if stage=='completed' else 'failed' if stage=='failed' else 'running',
            'stage': stage, 'percent': percent, 'message': message, 'updatedAt': iso_now(),
            'elapsedSeconds': round(elapsed), 'estimatedRemainingSeconds': None, **extra}
        if extra.get('completedUnits',0)>0 and extra.get('totalUnits',0)>extra['completedUnits']:
            current['estimatedRemainingSeconds'] = round((time.monotonic()-self.stage_started)/extra['completedUnits']*(extra['totalUnits']-extra['completedUnits']))
            current['etaScope'] = 'current stage only'
        self.history.append({k:current[k] for k in ('stage','percent','message','elapsedSeconds')})
        current['events'] = self.history[-35:]
        self.path.write_text(json.dumps(current,indent=2)+'\n')
        if self.store:
            self.store.write_json('live/ai-status.json',current)
        print(f'{percent}% [{stage}] {message} (elapsed {round(elapsed)} s)',flush=True)


def export_model(model):
    trees = []
    for iteration in model._predictors:
        nodes = iteration[0].nodes
        if nodes['is_categorical'].any():
            raise ValueError('Categorical trees are not supported by the portable predictor')
        trees.append([[-1 if n['is_leaf'] else int(n['feature_idx']),float(n['num_threshold']),
                       int(n['left']),int(n['right']),int(n['missing_go_to_left']),float(n['value'])] for n in nodes])
    return {'baseline': float(model._baseline_prediction[0,0]),'trees':trees}


def metrics(predicted, truth, current, mask):
    result = {}
    for key, indexes in [('tempF',[0]),('dewpointF',[1]),('wind',[2,3])]:
        good = mask.copy()
        for i in indexes:
            good &= np.isfinite(truth[:,i])&np.isfinite(current[:,i])&np.isfinite(predicted[:,i])
        n = int(good.sum())
        if n<100:
            raise ValueError('Too few independent-time test examples for '+key)
        residual = predicted[good][:,indexes]-truth[good][:,indexes]
        absolute = np.abs(residual[:,0]) if len(indexes)==1 else np.linalg.norm(residual,axis=1)
        result[key] = {'mae':round(float(absolute.mean()),3),'count':n,
                       'unit':'mph vector error' if key=='wind' else '°F'}
        if key=='wind':
            result[key]['speedMae'] = round(float(np.abs(np.linalg.norm(predicted[good,2:4],axis=1)-np.linalg.norm(truth[good,2:4],axis=1)).mean()),3)
    return result


def train(rows, metadata, progress, deadline):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from ai_features import for_lead
    import sklearn
    hours, stations, values, pressure = make_arrays(rows,STATIONS)
    if len(stations)<100 or len(hours)<30*24:
        raise ValueError('At least 100 regional airports and 30 days are required')
    train_end = hours[int(len(hours)*.75)]
    test_start = hours[int(len(hours)*.875)]
    issue = np.repeat(hours,len(stations))
    current = values.reshape(-1,4)
    base, feature_names = features(hours,stations,values,pressure,0)
    # One geographic station group is never a training target. It remains
    # available as a contemporaneous input, as it is in real operation.
    heldout = np.array([int(hashlib.sha256(s['station'].encode()).hexdigest()[:8],16)%5==0 for s in stations])
    spatial = np.tile(heldout,len(hours)); rng = np.random.RandomState(42)
    progress('sampling',35,'Building balanced examples for all 24 forecast hours',
             completedUnits=0,totalUnits=24)
    training_x=[[] for _ in TARGETS];training_y=[[] for _ in TARGETS]
    for li,lead in enumerate(LEADS):
        if time.monotonic()>=deadline:raise TimeoutError('Training sampling time limit reached')
        truth=np.full_like(values,np.nan);truth[:-lead]=values[lead:];truth=truth.reshape(-1,4)
        train_mask=(issue>=hours[0]+9)&(issue+lead<train_end)&~spatial
        for ti in range(4):
            good=np.flatnonzero(train_mask&np.isfinite(current[:,ti])&np.isfinite(truth[:,ti]))
            if len(good)<1000:raise ValueError('Insufficient regional training reports')
            take=rng.choice(good,min(8000,len(good)),replace=False)
            training_x[ti].append(for_lead(base[take],issue[take],feature_names,lead))
            training_y[ti].append(truth[take,ti]-current[take,ti])
        progress('sampling',35+int(5*(li+1)/len(LEADS)),f'Prepared +{lead} h training examples',
                 completedUnits=li+1,totalUnits=len(LEADS))
    estimators=[]; portable=[];sample_counts=[]
    for ti,target in enumerate(TARGETS):
        if time.monotonic()>=deadline:raise TimeoutError('Training runtime limit reached')
        progress('training',40+ti*5,f'Training regional {target} model for hours 1–24',
                 completedUnits=ti,totalUnits=4)
        x=np.concatenate(training_x[ti]); y=np.concatenate(training_y[ti]);sample_counts.append(len(y))
        training_x[ti]=[];training_y[ti]=[]
        model=HistGradientBoostingRegressor(max_iter=110,max_leaf_nodes=15,learning_rate=.07,
            min_samples_leaf=50,l2_regularization=8.,early_stopping=False,random_state=42)
        model.fit(x,y);exported=export_model(model)
        probe=x[::max(1,len(x)//1200)]
        np.testing.assert_allclose(predict_ensemble(exported,probe),model.predict(probe),atol=1e-7,rtol=1e-7)
        estimators.append(model);portable.append(exported)
        del x,y
    # Evaluate only later dates, reusing their causal inputs for every lead.
    eval_indices=np.flatnonzero(issue>=train_end)
    eval_base=base[eval_indices];eval_issue=issue[eval_indices];eval_current=current[eval_indices]
    eval_spatial=spatial[eval_indices]
    leads={};scores=[]
    for li,lead in enumerate(LEADS):
        if time.monotonic()>=deadline:raise TimeoutError('Validation runtime limit reached')
        progress('testing',60+int(30*li/len(LEADS)),f'Testing +{lead} h on held-out dates',
                 completedUnits=li,totalUnits=len(LEADS))
        x=for_lead(eval_base,eval_issue,feature_names,lead)
        raw_prediction=constrain(eval_current+np.column_stack([m.predict(x) for m in estimators]))
        # Verify exported inference on real missing-value and calendar inputs.
        probe=x[::max(1,len(x)//500)]
        for ti,m in enumerate(estimators):
            np.testing.assert_allclose(predict_ensemble(portable[ti],probe),m.predict(probe),atol=1e-7,rtol=1e-7)
        future=np.full_like(values,np.nan);future[:-lead]=values[lead:]
        truth=future.reshape(-1,4)[eval_indices]
        validation=(eval_issue+lead<test_start)&~eval_spatial
        test=(eval_issue>=test_start)&(eval_issue+lead<=hours[-1])
        alpha=np.zeros(4)
        for indexes in ([0],[1],[2,3]):
            good=validation.copy()
            for ti in indexes:
                good &= np.isfinite(eval_current[:,ti])&np.isfinite(truth[:,ti])&np.isfinite(raw_prediction[:,ti])
            if good.sum()<100:raise ValueError('Insufficient validation examples')
            losses=[]
            for a in (0.,.25,.5,.75,1.):
                prediction=eval_current[good][:,indexes]+a*(raw_prediction[good][:,indexes]-eval_current[good][:,indexes])
                residual=prediction-truth[good][:,indexes]
                losses.append(float(np.abs(residual[:,0]).mean()) if len(indexes)==1 else float(np.linalg.norm(residual,axis=1).mean()))
            alpha[indexes]=(0.,.25,.5,.75,1.)[int(np.argmin(losses))]
        prediction=constrain(eval_current+alpha*(raw_prediction-eval_current))
        score={'leadHours':lead,'forecast':metrics(prediction,truth,eval_current,test),
            'persistence':metrics(constrain(eval_current),truth,eval_current,test),
            'rawModel':metrics(raw_prediction,truth,eval_current,test),
            'spatialHoldout':metrics(prediction,truth,eval_current,test&eval_spatial),
            'modelWeight':{'tempF':float(alpha[0]),'dewpointF':float(alpha[1]),'wind':float(alpha[2])}}
        scores.append(score);leads[str(lead)]={'alpha':alpha.tolist()}
    progress('saving',93,'Saving 24-hour regional model and verification results')
    def stamp(hour):
        return datetime.fromtimestamp(int(hour)*3600,UTC).isoformat().replace('+00:00','Z')
    report={'version':VERSION,'trainedAt':iso_now(),'trainingData':metadata,'stationCount':len(stations),
        'fitStationCount':int((~heldout).sum()),'spatialHoldoutStations':[s['station'] for i,s in enumerate(stations) if heldout[i]],
        'stations':stations,'featureVersion':FEATURE_VERSION,'features':feature_names,'horizons':list(LEADS),
        'regionBounds':metadata['regionBounds'],'forecastNetwork':'All eligible live airport METARs within the observation region',
        'fitEndExclusive':stamp(train_end),'validationStart':stamp(train_end),'testStart':stamp(test_start),
        'testEnd':stamp(hours[-1]),'splitMethod':'Chronological 75% fit / 12.5% selection / 12.5% test; labels embargoed at boundaries; a geographic station group excluded from fitting and blend selection',
        'scores':scores,'algorithm':'Four pooled histogram gradient boosted models conditioned on forecast hour; predict temperature, dew point and vector-wind changes',
        'trainingSamplesPerTarget':sample_counts,'baseline':'Persistence: conditions remain at their issue-time values',
        'selection':'Hourly blend weights selected on validation dates only; held-out dates and geographic stations never select weights',
        'inputs':['Official routine airport METARs','Recent local and nearby-airport history','Altimeter pressure trends','Time of day, season, coordinates and forecast hour'],
        'excludedInputs':['Radar','Satellite','Upper-air data','Numerical forecast guidance'],
        'limitations':['Experimental surface-only forecasts; not official NWS guidance',
            'Regional training uses a geographically balanced subset; predictions at other airports generalize the pooled model',
            'Interpolation adds no observations; empty source areas and unsupported edges can remain blank',
            'Short training history does not cover all seasons; 12–24 h predictions can miss approaching systems',
            'Archive quality checks cover ranges, times and dew point consistency, not complete instrument QC',
            'Historical reports can include corrections unavailable at original issue time; prospective verification is still required'],
        'software':{'scikit-learn':sklearn.__version__,'numpy':np.__version__}}
    bundle={'version':VERSION,'featureVersion':FEATURE_VERSION,'networkMode':'all-live-regional-airports',
        'stations':stations,'sharedModels':portable,'leads':leads,'report':report}
    encoded=json.dumps(bundle,separators=(',',':'),allow_nan=False).encode()
    model_id=hashlib.sha256(encoded).hexdigest()[:16]
    bundle['modelId']=model_id;report['modelId']=model_id
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days',type=int,default=120)
    parser.add_argument('--history',default='training/region-history.json.gz')
    parser.add_argument('--output',default='ai_bundle')
    parser.add_argument('--publish',action='store_true',help='Publish private model and progress to the existing weather bucket')
    parser.add_argument('--max-seconds',type=int,default=1500)
    args = parser.parse_args()
    if not 60<=args.max_seconds<=1800:
        parser.error('The runtime budget must be 60--1800 seconds')
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('Training runtime limit reached')))
    signal.alarm(args.max_seconds)
    store = None
    if args.publish:
        from realtime import get_store
        store = get_store()
        if store is None:
            parser.error('WEATHER_DATA_BUCKET is required for --publish')
    output = Path(args.output); output.mkdir(parents=True,exist_ok=True)
    progress = Progress(output/'status.json',store)
    deadline = time.monotonic()+args.max_seconds
    try:
        progress('starting',0,'Starting bounded CPU-only experiment',budgetSeconds=args.max_seconds)
        path = Path(args.history)
        if path.exists():
            data = json.loads(gzip.decompress(path.read_bytes()))
            rows, metadata = data['rows'], data['metadata']
            if metadata['days']!=args.days or metadata['requestedStations']!=list(STATIONS):
                raise ValueError('Cached history has a different day count; choose a fresh --history path')
        else:
            rows, metadata = download_history(args.days,datetime.now(UTC),path.parent/'cache',progress,deadline)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps({'rows':rows,'metadata':metadata}).encode(),mtime=0))
        progress('preparing',32,f'Preparing {len(rows):,} eligible reports from {len(STATIONS)} requested airports',completedStations=len(STATIONS),totalStations=len(STATIONS))
        bundle = train(rows,metadata,progress,deadline)
        progress('saving',95,'Saving model, verification scores and training record')
        packed = gzip.compress(json.dumps(bundle,separators=(',',':'),allow_nan=False).encode(),mtime=0)
        (output/'model.json.gz.b64').write_text(base64.b64encode(packed).decode()+'\n')
        (output/'report.json').write_text(json.dumps(bundle['report'],indent=2)+'\n')
        if store:
            key = 'ai/models/'+bundle['modelId']+'.json.gz'
            store.write(key,packed,'application/gzip')
            store.write_json('live/ai-model.json',{'modelId':bundle['modelId'],'key':key,'report':bundle['report']})
        progress('completed',100,'Model trained and tested; forecast maps prepare with the hourly METAR collection',
                 modelId=bundle['modelId'],trainedAt=bundle['report']['trainedAt'])
        print(json.dumps(bundle['report']['scores'],indent=2),flush=True)
    except Exception as exc:
        progress('failed',0,'Training stopped; the previous model remains available',error=type(exc).__name__)
        raise
    finally:
        signal.alarm(0)


if __name__=='__main__':
    main()
