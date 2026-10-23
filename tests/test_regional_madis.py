from datetime import datetime, timedelta, timezone
import copy
import gzip
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

import numpy as np
import pytest
from scipy.io import netcdf_file
import regional_madis as madis

NOW=datetime(2026,10,23,12,tzinfo=timezone.utc)

class Store:
    def __init__(self,data=None):self.data=copy.deepcopy(data or {});self.writes=0
    def read_json(self,key):return copy.deepcopy(self.data.get(key))
    def write_json(self,key,value):self.data[key]=copy.deepcopy(value);self.writes+=1


def sample(station='HPN20',minute=53,**updates):
    return {'station':station,'name':'Hopkins MN US HENNEPIN','lat':44.95,'lon':-93.41,
            'time':madis.iso(NOW-timedelta(minutes=60-minute)),'tempF':68.,'dewpointF':50.,
            'wind':{'speedMph':5.,'direction':180},'network':'Hennepin West','source':'NOAA MADIS',**updates}


def payload(tmp_path, rows, units=None):
    path=tmp_path/'test.nc'
    with netcdf_file(path,'w') as n:
        n.createDimension('recNum',len(rows));n.createDimension('idLen',8);n.createDimension('nameLen',64)
        for name,length in [('stationId','idLen'),('stationName','nameLen'),('dataProvider','nameLen')]:
            f=n.createVariable(name,'c',('recNum',length));width=8 if length=='idLen' else 64
            f[:]=np.array([list(str(r.get(name,'')).ljust(width)[:width]) for r in rows],dtype='S1')
        expected={'temperature':b'kelvin','dewpoint':b'kelvin','windSpeed':b'meter/sec','windDir':b'degree'}
        defaults={'latitude':44.95,'longitude':-93.41,'observationTime':(NOW-timedelta(minutes=7)).timestamp(),
                  'temperature':293.15,'dewpoint':283.15,'windSpeed':2.236,'windDir':180,'restrictedDataLevel':-32767}
        for name,default in defaults.items():
            f=n.createVariable(name,'d',('recNum',));f[:]=[r.get(name,default) for r in rows];f.missing_value=-9999.
            if name in expected:f.units=(units or {}).get(name,expected[name])
        for name in expected:
            for suffix in ['QCR','ICR']:
                f=n.createVariable(name+suffix,'i',('recNum',));f[:]=[r.get(name+suffix,0) for r in rows]
            f=n.createVariable(name+'DD','c',('recNum',));f[:]=np.array([r.get(name+'DD','V') for r in rows],dtype='S1')
    return gzip.compress(path.read_bytes())


def test_parses_hennepin_mndot_cwop_and_partial_fields_with_qc(tmp_path):
    rows=[{'stationId':'HPN20','stationName':'Hopkins MN US HENNEPIN','dataProvider':'MesoWest'},
          {'stationId':'MN085','stationName':'I-494 Minnetonka MN US MNDOT','dataProvider':'MesoWest'},
          {'stationId':'C5791','stationName':'Minnetonka','dataProvider':'APRSWXNET','temperatureQCR':65,'temperatureDD':'Q'},
          {'stationId':'BAD','temperatureQCR':1,'dewpointQCR':1,'windSpeedQCR':1},
          {'stationId':'OUT','longitude':-120},
          {'stationId':'PRIVATE','restrictedDataLevel':5},
          {'stationId':'EARLY','observationTime':(NOW-timedelta(minutes=30)).timestamp()},
          {'stationId':'FILL','temperature':-9999.,'dewpoint':-9999.,'windSpeed':-9999.}]
    result=madis.parse_file(payload(tmp_path,rows),NOW);by_id={r['station']:r for r in result}
    assert set(by_id)=={'HPN20','MN085','C5791','EARLY'}
    assert by_id['HPN20']['tempF']==68. and by_id['HPN20']['dewpointF']==50.
    assert by_id['HPN20']['network']=='Hennepin West' and by_id['MN085']['network']=='MnDOT'
    assert by_id['C5791']['network']=='CWOP' and by_id['C5791']['tempF'] is None
    assert by_id['C5791']['dewpointF']==50.,'one bad field does not discard all station fields'
    assert by_id['HPN20']['skyCover']['displayFraction'] is None
    assert by_id['HPN20']['ceiling'] is None
    assert by_id['HPN20']['time'].endswith('11:53:00Z')


def test_wrong_units_fail_without_silent_conversion(tmp_path):
    with pytest.raises(ValueError,match='units'):
        madis.parse_file(payload(tmp_path,[{'stationId':'HPN20'}],{'temperature':b'fahrenheit'}),NOW)


def test_snapshot_latest_in_completed_hour_no_carry_forward_or_future_hours():
    data=madis.snapshot([sample(minute=48),sample(minute=53),sample(minute=58),
                         sample('OLD',time=madis.iso(NOW-timedelta(hours=13,minutes=7))),
                         sample('FUT',time=madis.iso(NOW+timedelta(minutes=53)))],NOW)
    assert len(data['history'])==12
    assert data['history'][-1]['stations'][0]['time'].endswith('11:58:00Z')
    assert not data['history'][0]['stations']
    assert not madis.snapshot(data['history'][-1]['stations'],NOW+timedelta(hours=1))['history'][-1]['stations']


def test_new_file_replaces_prior_qc_and_not_modified_preserves_data():
    old=madis.snapshot([sample('HPN20')],NOW-timedelta(seconds=1))
    # Use target NOW so the saved row is included in the expected frame.
    old=madis.snapshot([sample('HPN20')],NOW)
    name=(NOW-timedelta(hours=1)).strftime('%Y%m%d_%H00.gz');old['files']={name:{'etag':'old'}}
    store=Store({madis.KEY:old});calls=[]
    def download(url,meta):calls.append((url,meta));return b'changed',{'etag':'new'}
    with patch('regional_madis.parse_file',return_value=[sample('HPN24')]):
        fresh=madis.collect(store,NOW,hours=1,download=download)
    assert [r['station'] for r in fresh['history'][-1]['stations']]==['HPN24']
    assert calls[0][1]=={'etag':'old'}
    again=madis.collect(store,NOW,hours=1,download=lambda url,meta:(None,meta))
    assert again['history']==fresh['history']


def test_failed_download_preserves_prepared_object_and_failed_file_is_visible():
    store=Store({madis.KEY:madis.snapshot([sample()],NOW)});before=copy.deepcopy(store.data)
    def fail(*args):raise TimeoutError('timeout')
    with pytest.raises(ValueError,match='retained'):madis.collect(store,NOW,download=fail)
    assert store.data==before and store.writes==0
    def partly(url,meta):
        if url.endswith('1100.gz'):return None,{'etag':'same'}
        raise HTTPError(url,404,'not found',None,None)
    data=madis.collect(store,NOW,download=partly)
    assert data['errors'] and data['history'][-1]['stations']


def test_combined_map_prefers_official_airport_and_keeps_sources_and_missing_hours():
    airports=madis.snapshot([],NOW);airports['history'][-1]['stations']=[sample('KMSP',tempF=71.)]
    regional=madis.snapshot([sample('KMSP',tempF=99.),sample('HPN20')],NOW)
    result=madis.merge(airports,regional,NOW)
    frame=result['history'][-1]
    assert frame['airportCount']==1 and frame['madisCount']==1 and frame['hennepinCount']==1
    assert next(r for r in frame['stations'] if r['station']=='KMSP')['tempF']==71.
    assert not result['madis']['delayed'] and not result['history'][0]['stations']
    assert madis.merge(airports,None,NOW)['madis']['delayed']


def test_public_endpoint_reads_only_saved_data_and_current_remains_independent():
    import app
    app._cache.clear()
    airport=madis.snapshot([],NOW);airport.update(version=3,checkedAt=madis.iso(NOW))
    store=Store({'live/metar-clouds.json':airport,madis.KEY:madis.snapshot([sample()],NOW)})
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as upstream,patch('regional_madis.fetch') as fetch:
        response=app.app.test_client().get('/api/station-plots')
    assert response.status_code==200
    assert response.json['history'][-1]['stations']==[]
    assert response.json['sourcePolicy']=='airport-routine-only'
    assert 'madis' not in response.json
    upstream.assert_not_called();fetch.assert_not_called()
    assert response.headers['Cache-Control']=='no-store'
