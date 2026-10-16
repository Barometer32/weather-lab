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
VERSION = 'airport-ai-v1'


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
    import sklearn
    hours, stations, values, pressure = make_arrays(rows,STATIONS)
    if len(stations)<15 or len(hours)<30*24:
        raise ValueError('At least 15 airports and 30 days are required')
    train_end = hours[int(len(hours)*.75)]
    test_start = hours[int(len(hours)*.875)]
    issue = np.repeat(hours,len(stations))
    current = values.reshape(-1,4)
    leads, scores, feature_names = {}, [], None
    for li,lead in enumerate(LEADS):
        x, feature_names = features(hours,stations,values,pressure,lead)
        future = np.full_like(values,np.nan); future[:-lead] = values[lead:]
        truth = future.reshape(-1,4)
        train_mask = (issue>=hours[0]+9)&(issue+lead<train_end)
        validation = (issue>=train_end)&(issue+lead<test_start)
        test = (issue>=test_start)&(issue+lead<=hours[-1])
        raw_prediction = np.full_like(current,np.nan); models = []
        for ti,target in enumerate(TARGETS):
            if time.monotonic()>=deadline:
                raise TimeoutError('Training time limit reached')
            completed = li*4+ti
            progress('training',35+int(45*completed/20),f'Training +{lead} h {target}',
                     completedUnits=completed,totalUnits=20)
            good = train_mask&np.isfinite(current[:,ti])&np.isfinite(truth[:,ti])
            if good.sum()<1000:
                raise ValueError('Insufficient training reports for '+target)
            model = HistGradientBoostingRegressor(max_iter=60,max_leaf_nodes=9,learning_rate=.08,
                min_samples_leaf=45,l2_regularization=5.,early_stopping=False,random_state=42)
            model.fit(x[good],truth[good,ti]-current[good,ti])
            exported = export_model(model)
            probe = x[np.flatnonzero(validation|test)[::17]]
            np.testing.assert_allclose(predict_ensemble(exported,probe),model.predict(probe),atol=1e-7,rtol=1e-7)
            raw_prediction[:,ti] = current[:,ti]+model.predict(x)
            models.append(exported)
        raw_prediction = constrain(raw_prediction)
        alpha = np.zeros(4)
        for indexes in ([0],[1],[2,3]):
            good = validation.copy()
            for ti in indexes:
                good &= np.isfinite(current[:,ti])&np.isfinite(truth[:,ti])&np.isfinite(raw_prediction[:,ti])
            if good.sum()<100:
                raise ValueError('Insufficient validation examples')
            losses = []
            for a in (0.,.25,.5,.75,1.):
                prediction = current[good][:,indexes]+a*(raw_prediction[good][:,indexes]-current[good][:,indexes])
                residual = prediction-truth[good][:,indexes]
                losses.append(float(np.abs(residual[:,0]).mean()) if len(indexes)==1 else float(np.linalg.norm(residual,axis=1).mean()))
            alpha[indexes] = (0.,.25,.5,.75,1.)[int(np.argmin(losses))]
        prediction = constrain(current+alpha*(raw_prediction-current))
        deployed_metrics = metrics(prediction,truth,current,test)
        baseline_metrics = metrics(constrain(current),truth,current,test)
        raw_metrics = metrics(raw_prediction,truth,current,test)
        scores.append({'leadHours':lead,'forecast':deployed_metrics,'persistence':baseline_metrics,'rawModel':raw_metrics,
            'modelWeight':{'tempF':float(alpha[0]),'dewpointF':float(alpha[1]),'wind':float(alpha[2])}})
        leads[str(lead)] = {'models':models,'alpha':alpha.tolist()}
    progress('testing',85,'Checking held-out forecast errors and portable model parity')
    def stamp(hour):
        return datetime.fromtimestamp(int(hour)*3600,UTC).isoformat().replace('+00:00','Z')
    report = {'version':VERSION,'trainedAt':iso_now(),'trainingData':metadata,'stationCount':len(stations),
        'stations':stations,'featureVersion':FEATURE_VERSION,'features':feature_names,'horizons':list(LEADS),
        'fitEndExclusive':stamp(train_end),'validationStart':stamp(train_end),'testStart':stamp(test_start),
        'testEnd':stamp(hours[-1]),'splitMethod':'Chronological 75% fit / 12.5% selection / 12.5% test; labels embargoed at each boundary',
        'scores':scores,'algorithm':'Histogram gradient boosted trees predicting changes in temperature, dew point, and vector wind',
        'baseline':'Persistence: conditions remain at their issue-time values',
        'selection':'Blend weights selected on validation dates only; held-out test never selects weights',
        'inputs':['Official routine airport METARs','Recent local and nearby-airport history','Altimeter pressure trends','Time of day, season and coordinates'],
        'excludedInputs':['Radar','Satellite','Upper-air data','Numerical forecast guidance'],
        'limitations':['Experimental surface-only forecasts; not official NWS guidance',
            'Sparse airport network provides coarse spatial detail; interpolation adds no observations',
            'Short training history does not cover all seasons; 12–24 h predictions can miss approaching systems',
            'Archive quality checks cover ranges, times and dew point consistency, not complete instrument QC',
            'Historical reports can include corrections unavailable at original issue time; prospective verification is still required'],
        'software':{'scikit-learn':sklearn.__version__,'numpy':np.__version__}}
    bundle = {'version':VERSION,'featureVersion':FEATURE_VERSION,'stations':stations,'leads':leads,'report':report}
    encoded = json.dumps(bundle,separators=(',',':'),allow_nan=False).encode()
    model_id = hashlib.sha256(encoded).hexdigest()[:16]
    bundle['modelId'] = model_id;report['modelId'] = model_id
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days',type=int,default=120)
    parser.add_argument('--history',default='training/history.json.gz')
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
            if metadata['days']!=args.days:
                raise ValueError('Cached history has a different day count; choose a fresh --history path')
        else:
            rows, metadata = download_history(args.days,datetime.now(UTC),path.parent/'cache',progress,deadline)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps({'rows':rows,'metadata':metadata}).encode(),mtime=0))
        progress('preparing',32,f'Preparing {len(rows):,} eligible reports from 25 airports',completedStations=25,totalStations=25)
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
