from datetime import datetime, timedelta, timezone
from copy import deepcopy
from unittest.mock import patch

import numpy as np
import pytest

import expmet as e

NOW=datetime(2026,11,1,15,5,tzinfo=timezone.utc)
TARGET=NOW.replace(minute=0)


def row(name,lat=45.,lon=-93.,temp=50.,dew=40.,speed=10.,direction=0.,age=10,**extra):
    return dict(station=name,lat=lat,lon=lon,time=e.iso(TARGET-timedelta(minutes=age)),tempF=temp,
                dewpointF=dew,wind=dict(speedMph=speed,direction=direction),provider='MesoWest',**extra)


def cluster():
    return [row('A',44.9,-93.1),row('B',45.1,-93.1),row('C',45.,-92.9),row('D',45.1,-92.9)]


def test_window_is_observation_time_not_ingest_time_and_latest_station_wins():
    rows=[row('A',temp=40,age=40),row('A',temp=60,age=5),row('OLD',age=61),row('FUTURE',age=-1),
          row('EDGE',age=60),row('NOW',age=0),row('OUT',lat=35)]
    selected={r['station']:r for r in e.candidates(rows,TARGET)}
    assert set(selected)=={'A','EDGE','NOW'}
    assert selected['A']['tempF']==60
    assert len(rows)==7


def test_constant_fields_wind_wraparound_and_opposing_wind_vectors():
    rows=e.candidates(cluster(),TARGET)
    points=e.project([45.],[-93.])
    out,count,near,age=e.estimate(e.samples(rows,'tempF'),points)
    assert out[0,0]==pytest.approx(50)
    assert count[0]==4 and near[0]<20 and age[0]==pytest.approx(10)
    for i,r in enumerate(rows):
        angle=np.radians(350 if i%2 else 10)
        r['uv']=[-10*np.sin(angle),-10*np.cos(angle)]
    out,*_=e.estimate(e.samples(rows,'uv'),points)
    assert abs(np.degrees(np.arctan2(-out[0,0],-out[0,1])))<5 and out[0,1]<-9,'North winds stay northerly, never average to south'
    sample=(np.array([[-10.,0],[10.,0],[0.,10],[0.,-10]]),np.array([[10.,0],[-10.,0],[10.,0],[-10.,0]]),np.ones(4),np.zeros(4))
    out,*_=e.estimate(sample,np.array([[0.,0.]]))
    assert np.linalg.norm(out[0])<.001,'Opposing flows cancel in vector space'


def test_distant_and_sparse_points_are_filled_but_no_data_is_not_invented():
    rows=e.candidates(cluster(),TARGET)
    for field in ['tempF','dewpointF','uv']:
        out,counts,nearest,_=e.estimate(e.samples(rows,field),e.project([47.],[-96.]))
        assert np.isfinite(out).all() and counts[0]==0 and nearest[0]>50
    assert np.isfinite(e.estimate(e.samples(rows[:1],'tempF'),e.project([45.],[-93.]))[0]).all()
    rows[0]['dewpointF']=None;rows[1]['dewpointF']=None
    assert np.isfinite(e.estimate(e.samples(rows,'dewpointF'),e.project([45.],[-93.]))[0]).all()
    for row in rows:row['dewpointF']=None
    assert np.isnan(e.estimate(e.samples(rows,'dewpointF'),e.project([45.],[-93.]))[0]).all()
    assert np.isfinite(e.estimate(e.samples(rows,'tempF'),e.project([45.],[-93.]))[0]).all()


def test_declustering_and_robust_weighting_limit_one_bad_station():
    source=cluster()+[row('DUP',45.1001,-92.9001)]
    selected=e.samples(e.candidates(source,TARGET),'tempF')
    assert len(selected[0])==4,'A dense cluster does not get extra votes'
    positions=np.array([[-10.,0],[10.,0],[0.,10],[0.,-10],[8.,8.]])
    values=np.array([50.,50.,50.,50.,100.])
    out,*_=e.estimate((positions,values,np.ones(5),np.zeros(5)),np.array([[0.,0.]]))
    assert 50<=out[0,0]<52


def test_generated_grid_is_regular_and_dewpoint_never_exceeds_temperature():
    rows=cluster();rows[0]['dewpointF']=50.5
    data=e.analyze(rows,TARGET,NOW,{'airports':False,'madis':True})
    assert data['experimental'] and data['gridKm']==10 and data['stations']
    far=min(data['stations'],key=lambda p:p['lat']+p['lon'])
    assert far['extrapolated']['temperature'] and far['tempF']==pytest.approx(50)
    assert len({(p['gx'],p['gy']) for p in data['stations']})==len(data['stations'])
    for p in data['stations']:
        assert e.project([p['lat']],[p['lon']])[0]==pytest.approx([p['gx']*10,p['gy']*10],abs=.001)
        if p['tempF'] is not None and p['dewpointF'] is not None:assert p['dewpointF']<=p['tempF']
    assert data['windowEnd']==e.iso(TARGET)


class Store:
    def __init__(self):self.data={};self.writes=0
    def read_json(self,key):return deepcopy(self.data.get(key))
    def write_json(self,key,value):self.data[key]=deepcopy(value);self.writes+=1


def test_collector_two_public_files_once_per_hour_uses_all_cached_airports():
    store=Store();store.data['live/metar-clouds.json']={'history':[{'stations':[row('KAIR',reportType='METAR')]}]}
    calls=[]
    def download(url):calls.append(url);return b'data',{}
    def parse(payload,now,**selection):
        assert selection['excluded_stations']==()
        assert selection['window_start']==TARGET-timedelta(hours=1)
        assert selection['window_end']==TARGET+timedelta(seconds=1)
        return cluster()
    result=e.collect(store,NOW,download,parse)
    assert len(calls)==2 and '/20261101_1400.gz' in calls[0] and '/20261101_1500.gz' in calls[1]
    assert result['sources']['madis'] and result['sources']['airports']
    assert store.data[e.KEY]['providers']['Airport METAR']==1
    e.collect(store,NOW+timedelta(minutes=25),download,parse)
    assert len(calls)==2 and store.writes==1,'Refreshes never recollect the same analysis hour'


def test_source_failure_is_visible_and_total_failure_keeps_previous_analysis():
    store=Store();store.data['live/metar-clouds.json']={'history':[{'stations':[{**r,'reportType':'METAR'} for r in cluster()]}]}
    def failed(*args):raise OSError('unavailable')
    result=e.collect(store,NOW,failed)
    assert not result['sources']['madis'] and store.data[e.KEY]['sourceErrors']
    previous=deepcopy(store.data[e.KEY]);store.data.pop('live/metar-clouds.json')
    with pytest.raises(ValueError):e.collect(store,NOW+timedelta(hours=1),failed)
    assert store.data[e.KEY]==previous


def test_public_api_only_reads_prepared_data_and_collector_is_registered():
    import app,collector
    data=e.analyze(cluster(),TARGET,NOW,{'airports':False,'madis':True})
    with patch.object(app,'prepared_snapshot',return_value=data),patch.object(e,'collect',side_effect=AssertionError('No upstream calls from a page view')):
        response=app.app.test_client().get('/api/expmet')
        assert response.status_code==200 and response.json['experimental']
    assert 'expmet' in collector.locks
    with patch.object(collector,'get_store',return_value=Store()),patch.object(e,'collect',return_value={'points':100}) as collect:
        response=collector.app.test_client().post('/collect/expmet')
        assert response.status_code==200 and response.json['result']['points']==100
        collect.assert_called_once()

