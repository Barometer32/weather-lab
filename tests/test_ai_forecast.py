"""Checks for causal features, portable inference and private preparation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

import ai_data
import ai_features as features
import ai_forecast as ai
import app
import collector
from test_support import MemoryStore

NOW = datetime(2026,10,16,21,2,tzinfo=timezone.utc)


def observations():
    bundle = ai.local_model()
    history=[]
    for i in range(12):
        hour=NOW.replace(minute=0)-timedelta(hours=11-i)
        rows=[]
        for j,station in enumerate(bundle['stations']):
            rows.append({'station':'K'+station['station'],'stationKey':'AWC_METAR:K'+station['station'],
                'network':'AWC_METAR','source':'NOAA Aviation Weather Center','reportType':'METAR',
                'lat':station['lat'],'lon':station['lon'],'time':ai.iso(hour-timedelta(minutes=7)),
                'tempF':45+i*.4+j*.1,'dewpointF':35+i*.1,'rawOb':'K'+station['station']+' 162053Z 36010KT 10SM CLR 10/05 A3000',
                'wind':{'speedMph':10,'direction':359 if j%2 else 1}})
        history.append({'hour':ai.iso(hour),'stations':rows})
    return {'hour':history[-1]['hour'],'checkedAt':ai.iso(NOW),'stations':history[-1]['stations'],'history':history}


class ArchiveTests(unittest.TestCase):
    def test_only_real_routine_window_reports_with_range_checks_and_calm_wind(self):
        text='station,valid,lon,lat,tmpf,dwpf,drct,sknt,alti,metar\n'
        text+='MSP,2026-10-01 12:49,-93.2,44.9,60,40,180,10,30.00,KMSP 011249Z\n'
        text+='MSP,2026-10-01 12:53,-93.2,44.9,61,40,180,10,30.01,KMSP 011253Z\n'
        text+='MSP,2026-10-01 12:55,-93.2,44.9,62,40,180,10,30.01,SPECI KMSP 011255Z\n'
        text+='STC,2026-10-01 12:53,-94.0,45.5,50,60,M,0,30.00,KSTC 011253Z\n'
        rows=ai_data.parse_csv(text)
        self.assertEqual(len(rows),2)
        msp=next(r for r in rows if r['station']=='MSP')
        self.assertEqual(msp['values'][:2],[61,40]);self.assertEqual(msp['hour'],int(datetime(2026,10,1,13,tzinfo=timezone.utc).timestamp()/3600))
        stc=next(r for r in rows if r['station']=='STC')
        self.assertIsNone(stc['values'][1]);self.assertEqual(stc['values'][2:],[0,0])

    def test_future_reports_cannot_change_past_features_and_lags_do_not_wrap(self):
        rng=np.random.RandomState(2);values=rng.normal(size=(48,3,4));pressure=np.full((48,3),30.)
        hours=np.arange(480000,480048);sites=[{'lat':44+i,'lon':-94+i} for i in range(3)]
        a,names=features.features(hours,sites,values,pressure,24)
        changed=values.copy();changed[30:]=1000
        b,_=features.features(hours,sites,changed,pressure,24)
        np.testing.assert_equal(a[:30*3],b[:30*3])
        self.assertTrue(np.isnan(a[:3,names.index('tempF_lag9')]).all())

    def test_portable_trees_follow_missing_paths_and_keep_wind_components(self):
        tree=[[0,1.,1,2,1,0],[-1,0,0,0,0,2],[-1,0,0,0,0,-3]]
        x=np.array([[np.nan],[1.],[2.]])
        np.testing.assert_allclose(features.predict_tree(tree,x),[2,2,-3])
        np.testing.assert_allclose(features.predict_ensemble({'baseline':5,'trees':[tree]},x),[7,7,2])
        p=features.constrain(np.array([[50.,60.,300.,400.]]))
        self.assertEqual(p[0,1],50);self.assertAlmostEqual(np.linalg.norm(p[0,2:]),115)
        self.assertEqual(features.constrain(np.array([[np.nan,35.,0.,0.]]))[0,1],35)


class ForecastTests(unittest.TestCase):
    def test_live_model_uses_only_saved_inputs_and_five_genuine_future_labels(self):
        source=observations();before=deepcopy(source)
        with patch('app.download') as upstream:
            frames,reports=ai.predict(source,ai.local_model())
        upstream.assert_not_called();self.assertEqual(source,before)
        self.assertEqual([f['leadHours'] for f in frames],[1,3,6,12,24])
        for frame in frames:
            self.assertEqual(ai.stamp(frame['hour']),ai.stamp(source['hour'])+timedelta(hours=frame['leadHours']))
            self.assertEqual(len(frame['stations']),25)
            for row in frame['stations']:
                self.assertLessEqual(row['dewpointF'],row['tempF']+.001)
                self.assertEqual(row['product'],'forecast')
        self.assertEqual(max(reports),source['stations'][0]['time'])

    def test_missing_station_is_not_replaced_by_a_synthetic_measurement(self):
        source=observations();missing=source['stations'][0]['station']
        for frame in source['history']:
            frame['stations']=[r for r in frame['stations'] if r['station']!=missing]
        predictions,_=ai.predict(source,ai.local_model())
        self.assertTrue(all(missing not in [r['station'] for r in f['stations']] for f in predictions))

    def test_saved_model_overrides_bundle_only_with_matching_version_and_id(self):
        import gzip
        store=MemoryStore();bundle=deepcopy(ai.local_model());bundle['modelId']='a'*16
        key='ai/models/'+'a'*16+'.json.gz';store.write(key,gzip.compress(json.dumps(bundle).encode()),'application/gzip')
        store.write_json('live/ai-model.json',{'modelId':'a'*16,'key':key})
        self.assertEqual(ai.load_model(store)['modelId'],'a'*16)
        store.write_json('live/ai-model.json',{'modelId':'b'*16,'key':key})
        with self.assertRaises(ValueError):ai.load_model(store)

    def test_atomic_map_publish_reuse_and_numerical_archive_preserve_observations(self):
        store=MemoryStore();source=observations();before=deepcopy(source)
        result=ai.prepare(store,source,NOW);self.assertEqual(result['frames'],5)
        index=store.read_json('live/ai-forecast.json');self.assertEqual(source,before)
        self.assertEqual(len(index['history']),5)
        for frame in index['history']:
            manifest=store.read_json(frame['analysisUrl'].removeprefix('/api/prepared/'))
            self.assertTrue(all(p['supportedCells']>1000 for p in manifest['fields'].values()))
        self.assertTrue(any(k.startswith('ai/issued/') for k in store.objects))
        writes=len(store.writes);self.assertEqual(ai.prepare(store,source,NOW)['status'],'already prepared');self.assertEqual(len(store.writes),writes)
        source['history'][-1]['stations'][0]['tempF']+=1
        previous=store.read('live/ai-forecast.json')
        with patch('ai_forecast.render',side_effect=ValueError('fixture')):
            outcome=collector.prepare_ai(store,source,NOW)
        self.assertIn('delayed',outcome['status']);self.assertEqual(store.read('live/ai-forecast.json'),previous)

    def test_public_api_reads_status_and_assets_without_starting_work(self):
        store=MemoryStore();ai.prepare(store,observations(),NOW)
        app.prepared_image.cache_clear()
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('ai_forecast.prepare') as work,patch('app.download') as upstream:
            client=app.app.test_client();response=client.get('/api/ai-forecast')
            self.assertEqual(response.status_code,200);self.assertFalse(response.json['forecast']['stale'])
            self.assertEqual(response.json['training']['state'],'completed')
            url=response.json['forecast']['history'][-1]['analysisUrl'];manifest=client.get(url)
            self.assertEqual(manifest.status_code,200)
            self.assertEqual(client.get(manifest.json['fields']['wind']['imageUrl']).mimetype,'image/png')
            self.assertEqual(client.get('/api/prepared/ai/models/'+'a'*16+'.json.gz').status_code,404)
            work.assert_not_called();upstream.assert_not_called()
        app.prepared_image.cache_clear()

    def test_training_scores_include_embargoed_split_and_fallback_disclosure(self):
        r=ai.local_model()['report']
        self.assertEqual(r['stationCount'],25);self.assertEqual(r['trainingData']['days'],120)
        self.assertLess(ai.stamp(r['fitEndExclusive']),ai.stamp(r['testStart']))
        self.assertEqual(r['excludedInputs'],['Radar','Satellite','Upper-air data','Numerical forecast guidance'])
        self.assertEqual(r['scores'][0]['modelWeight']['dewpointF'],0)
        for score in r['scores']:
            for field in ('tempF','dewpointF','wind'):
                self.assertGreater(score['forecast'][field]['count'],100)
                self.assertGreaterEqual(score['forecast'][field]['mae'],0)


if __name__=='__main__':unittest.main()
