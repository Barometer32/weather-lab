import copy
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
import app
import collector
import hennepin_observations as obs
import observation_stations as inventory
from test_regional_madis import payload as netcdf_payload

NOW=datetime(2026,11,13,18,10,tzinfo=timezone.utc)
class Store:
    def __init__(self):self.data={}
    def read_json(self,key):return copy.deepcopy(self.data.get(key))
    def write_json(self,key,value):self.data[key]=copy.deepcopy(value)

def row(station='HPN20',**changes):
    result={'station':station,'name':'Hopkins MN US HENNEPIN','network':'Hennepin West',
            'lat':44.95,'lon':-93.41,'time':obs.iso(NOW-timedelta(minutes=20)),
            'tempF':35.4,'dewpointF':22.8,'wind':{'speedMph':5.4,'direction':350}}
    result.update(changes);return result

def saved(rows,**changes):
    return {'version':obs.VERSION,'stationPolicy':obs.POLICY,'checkedAt':obs.iso(NOW),
            'reports':rows,'sourceFailures':[],**changes}


def test_exact_approved_19_roster_never_admits_removed_or_new_stations():
    assert set(obs.STATIONS)=={'HPN02','HPN03','HPN05','HPN07','HPN08','HPN09','HPN20','HPN21','HPN24','HPN25','HPN26','HPN28','HPN30','HPN31','HPN37','HPN38','HPN39','HPN45','HPN47'}
    excluded=['HPN04','HPN27','HPN42','HPN29','HPN44','HPN19','HPN06','HPN10','HPN11','HPN60','KFCM','KMIC','KMSP']
    data=obs.present(saved([row(code,tempF=100) for code in excluded]+[row(s) for s in obs.STATIONS]),NOW)
    assert data['current']['temperatureF']==35.4 and data['current']['stationCount']==19
    assert {r['station'] for r in data['stations']}==set(obs.STATIONS)
    assert not obs.present(saved([row(network='CWOP')]),NOW)['available']
    assert not obs.present(saved([row(lat=44.74,lon=-93.12)]),NOW)['available']


def test_latest_per_station_equal_fahrenheit_weight_and_real_time_range():
    rows=[row('HPN20',tempF=34.1),row('HPN20',tempF=35.4),
          row('HPN24',tempF=36.1,time=obs.iso(NOW-timedelta(minutes=19))),
          row('HPN25',tempF=36.8)]
    result=obs.present(saved(rows),NOW)['current']
    assert result['temperatureF']==pytest.approx((35.4+36.1+36.8)/3)
    assert result['dewpointF']==22.8 and result['windSpeedMph']==5.4
    assert result['observedAt']==obs.iso(NOW-timedelta(minutes=19))
    assert result['oldestObservedAt']==obs.iso(NOW-timedelta(minutes=20))
    assert result['stationCount']==3 and result['sampleCounts']['temperature']==3
    assert result['windCardinal']=='N'


def test_qc_missing_fields_and_bad_correction_do_not_reuse_older_good_value():
    rows=[row(tempF=90),row(tempF=None,dewpointF=None,wind={'speedMph':None,'direction':None}),
          row('HPN24',tempF=36.2,dewpointF=23.4),row('HPN25',tempF=float('nan'),dewpointF=999,wind={'speedMph':float('inf')})]
    data=obs.present(saved(rows),NOW)
    assert data['current']['temperatureF']==36.2
    assert data['current']['sampleCounts']['temperature']==1
    assert len(data['stations'])==3
    bad=next(r for r in data['stations'] if r['station']=='HPN20')
    assert bad['tempF'] is bad['dewpointF'] is None
    assert obs.present(saved([row(tempF=34,dewpointF=80)]),NOW)['current']['dewpointF'] is None


def test_expiry_future_and_failed_source_preserve_actual_report_times():
    data=saved([row(),row('HPN24',time=obs.iso(NOW-timedelta(minutes=31))),row('HPN25',time=obs.iso(NOW+timedelta(minutes=1)))])
    assert [r['station'] for r in obs.present(data,NOW)['stations']]==['HPN20']
    assert not obs.present(saved([row()]),NOW+timedelta(minutes=11))['available']
    failed=obs.present(saved([row()],sourceFailures=[{'file':'mesonet','error':'offline'}]),NOW)
    assert failed['stale'] and failed['current']['observedAt']==row()['time']
    assert obs.present(saved([row()]),NOW+timedelta(minutes=12))['stale']
    with pytest.raises(ValueError):obs.present({'version':'three-airport-rapid-main-c-v1'},NOW)


def test_wind_uses_scalar_speed_and_speed_weighted_circular_direction():
    rows=[row(s,wind={'speedMph':speed,'direction':direction}) for s,speed,direction in [('HPN20',5,350),('HPN24',5,10),('HPN25',0,None)]]
    current=obs.present(saved(rows),NOW)['current']
    assert current['windDirection']==pytest.approx(0,abs=1e-8) and current['windCardinal']=='N'
    assert current['windSpeedMph']==pytest.approx(10/3)
    assert obs.present(saved([row(wind={'speedMph':0})]),NOW)['current']['windCardinal']=='Calm'
    assert obs.present(saved([row(wind={'speedMph':5,'variable':True})]),NOW)['current']['windCardinal']=='Variable'
    assert obs.present(saved([row(wind={'speedMph':5,'direction':None})]),NOW)['current']['windCardinal']=='Unknown'


def test_collector_conditional_files_and_same_time_correction(tmp_path):
    store=Store();calls=[]
    def download(url,meta):calls.append((url,meta));return b'payload',{'etag':'new'}
    with patch('regional_madis.parse_file',return_value=[row(),row('HPN24'),row('HPN27',tempF=100)]):
        result=obs.collect(store,NOW,download)
    assert result['stations']==2 and result['expectedStations']==19
    assert len(calls)==2 and all('LDAD/mesonet' in url and 'hfmetar' not in url for url,_ in calls)
    assert store.read_json(obs.KEY)['version']==obs.VERSION
    again=obs.collect(store,NOW+timedelta(minutes=5),lambda u,m:(None,m))
    assert again['observedAt']==result['observedAt']
    with patch('regional_madis.parse_file',return_value=[row(tempF=None),row('HPN24',tempF=36.1)]):
        obs.collect(store,NOW+timedelta(minutes=6),download)
    assert obs.present(store.read_json(obs.KEY),NOW+timedelta(minutes=6))['current']['temperatureF']==36.1
    before=copy.deepcopy(store.data[obs.KEY])
    def offline(*a):raise OSError('offline')
    with pytest.raises(ValueError):obs.collect(store,NOW+timedelta(minutes=40),offline)
    assert store.data[obs.KEY]==before


def test_real_netcdf_qc_rejects_bad_temperature_without_rounding_to_whole_c(tmp_path):
    # The native whole-Kelvin-Celsius restriction from METAR is deliberately gone.
    import regional_madis
    source=[{'stationId':'HPN20','stationName':'Hopkins MN US HENNEPIN','dataProvider':'MesoWest',
             'observationTime':(NOW-timedelta(minutes=12)).timestamp(),'temperature':275.35},
            {'stationId':'HPN24','stationName':'Edina MN US HENNEPIN','dataProvider':'MesoWest',
             'observationTime':(NOW-timedelta(minutes=12)).timestamp(),'temperature':290,'temperatureQCR':1}]
    rows=regional_madis.parse_file(netcdf_payload(tmp_path,source),NOW,window_start=NOW-timedelta(hours=1),window_end=NOW,station_prefix='HPN',include_invalid=True,excluded_stations=())
    value=obs.present(saved(rows),NOW)['current']
    assert value['temperatureF']==36.0 and value['sampleCounts']['temperature']==1


def test_prepared_only_public_endpoint_and_private_collection_route():
    store=Store();store.data[obs.KEY]=saved([row(s) for s in obs.STATIONS]);app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('regional_madis.fetch') as upstream,patch('app.download') as metars:
        response=app.app.test_client().get('/api/observations/current')
        assert response.status_code==200 and response.json['version']==obs.VERSION
        assert response.json['current']['stationCount']==19 and response.headers['Cache-Control']=='no-store'
        upstream.assert_not_called();metars.assert_not_called()
    app._cache.clear()
    with patch('collector.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('hennepin_observations.collect',return_value={'available':True}) as run:
        assert collector.app.test_client().post('/collect/rapid-observations').status_code==200
        run.assert_called_once_with(store,NOW)
