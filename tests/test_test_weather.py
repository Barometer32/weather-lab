from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import copy
import gzip
import json
import math
from pathlib import Path

import pytest
import point_weather as w

NOW=datetime(2026,11,2,12,15,tzinfo=timezone.utc)


def row(station='A',lat=44.92,lon=-93.42,age=5,temp=50,dew=40,speed=10,direction=180,**extra):
    return {'station':station,'name':station,'lat':lat,'lon':lon,'time':w.iso(NOW-timedelta(minutes=age)),
            'tempF':temp,'dewpointF':dew,'wind':{'speedMph':speed,'direction':direction},'network':'Mesonet','provider':'public',**extra}


def cluster(**kwargs):
    return [row(str(i),lat=44.92+dy,lon=-93.42+dx,**kwargs) for i,(dy,dx) in enumerate([(0,0),(.02,.02),(-.02,-.02),(.04,-.03)])]


def data(rows):return {'version':w.VERSION,'checkedAt':w.iso(NOW),'stations':rows,'errors':[]}


def test_constant_fields_survive_grid_interpolation_and_times_are_real():
    result=w.analysis(data(cluster()),44.925,-93.415,NOW)
    assert result['available'] and result['gridSpacingKm']==5
    assert result['fields']['temperatureF']['value']==50
    assert result['fields']['dewpointF']['value']==40
    assert result['fields']['windMph']['value']==10
    assert result['windDirection']==pytest.approx(180)
    assert result['observationStart']==w.iso(NOW-timedelta(minutes=5))
    assert result['fields']['temperatureF']['representativeTime']==result['observationStart']
    assert result['checkedAt']!=result['observationStart']


def test_wind_averages_vectors_across_north_and_missing_wind_is_not_calm():
    rows=cluster(direction=359)
    rows[0]['wind']['direction']=1
    rows[1]['wind']={'speedMph':None,'direction':None}
    result=w.analysis(data(rows),44.925,-93.415,NOW)
    assert min(result['windDirection'],360-result['windDirection'])<2
    assert result['fields']['windMph']['stationCount']==3
    calm=w.analysis(data(cluster(speed=0,direction=None)),44.925,-93.415,NOW)
    assert calm['fields']['windMph']['value']==0 and calm['windDirection'] is None


def test_no_old_or_future_rows_no_interpolation_without_support():
    rows=cluster(age=40)
    rows += [row('STALE',age=61),row('FUTURE',age=-1)]
    assert len(w.latest(rows,NOW))==4
    narrow=w.analysis(data(rows),44.925,-93.415,NOW,30)
    assert not narrow['available']
    isolated=w.analysis(data([row()]),44.925,-93.415,NOW)
    assert not isolated['available']
    distant=w.analysis(data(cluster()),40,-80,NOW)
    assert not distant['available']


def test_each_variable_uses_its_own_good_station_support():
    rows=cluster()
    rows[0]['tempF']=None
    rows[1]['dewpointF']=80 # Impossible dewpoint is not accepted.
    result=w.analysis(data(rows),44.925,-93.415,NOW)
    assert result['fields']['temperatureF']['stationCount']==3
    assert result['fields']['dewpointF']['stationCount']==3
    assert result['fields']['dewpointF']['value']<=result['fields']['temperatureF']['value']
    assert result['fields']['windMph']['stationCount']==4


def test_latest_per_station_and_physical_duplicates_are_not_extra_votes():
    rows=cluster()+[row('0',age=10,temp=90),row('DUPLICATE',age=6)]
    selected=w.latest(rows,NOW)
    assert len(selected)==4
    assert next(r for r in selected if r['station']=='0')['tempF']==50
    assert len(w.latest(cluster()+[row('OUTOFRANGE',lat=95)],NOW))==4


class Store:
    def __init__(self):self.data={}
    def read_json(self,k):return copy.deepcopy(self.data.get(k))
    def write_json(self,k,v):self.data[k]=copy.deepcopy(v)


def test_conditional_feeds_replace_changed_qc_not_old_bad_readings():
    store=Store()
    def download(url,previous):return (b'AWC' if url==w.AWC else b'netCDF'),{'etag':'1'}
    with patch.object(w,'parse_file',return_value=cluster()),patch.object(w,'airport_rows',return_value=[]):
        first=w.collect(store,NOW,download)
    assert len(first['stations'])==4
    with patch.object(w,'parse_file',return_value=cluster()),patch.object(w,'airport_rows',return_value=[]):
        same=w.collect(store,NOW+timedelta(minutes=5),lambda url,old:(None,old))
    assert same['stations']==first['stations']
    # A reissued file removing a station must not resurrect it from the last snapshot.
    with patch.object(w,'parse_file',return_value=cluster()[1:]),patch.object(w,'airport_rows',return_value=[]):
        revised=w.collect(store,NOW+timedelta(minutes=10),download)
    assert len(revised['stations'])==3
    before=copy.deepcopy(store.data)
    def fail(*args):raise TimeoutError('source timeout')
    with pytest.raises(ValueError,match='retained'):w.collect(store,NOW+timedelta(minutes=15),fail)
    assert store.data==before


def test_collection_idempotence_avoids_repeated_bulk_requests():
    store=Store();store.data[w.KEY]=data(cluster())
    def forbidden(*args):raise AssertionError('Redundant upstream download')
    assert w.collect(store,NOW+timedelta(minutes=2),forbidden)['stations']


def test_airport_xml_uses_celsius_correctly_and_keeps_calm_direction_optional():
    xml=f'''<response><data><METAR><station_id>KMSP</station_id><observation_time>{w.iso(NOW-timedelta(minutes=7))}</observation_time><latitude>44.88</latitude><longitude>-93.22</longitude><temp_c>10</temp_c><dewpoint_c>5</dewpoint_c><wind_speed_kt>0</wind_speed_kt></METAR></data></response>'''
    rows=w.airport_rows(gzip.compress(xml.encode()),NOW)
    assert rows[0]['tempF']==50 and rows[0]['dewpointF']==41
    assert rows[0]['wind']['speedMph']==0


def test_search_coordinates_and_nws_redirect_are_validated(monkeypatch):
    w.location.cache_clear()
    assert w.location('44.9, -93.4')['latitude']==44.9
    monkeypatch.setattr(w,'read_url',lambda url:(b'', 'https://forecast.weather.gov/MapClick.php?CityName=Hopkins&state=MN&textField1=44.9&textField2=-93.4'))
    assert w.location('Hopkins, MN')['label']=='Hopkins, MN'
    monkeypatch.setattr(w,'read_url',lambda url:(b'', 'https://example.com/MapClick.php?textField1=44.9&textField2=-93.4'))
    with pytest.raises(ValueError,match='uniquely'):w.location('ambiguous')
    with pytest.raises(ValueError):w.coordinates('nan',0)


def test_public_point_apis_validate_input_and_never_download_station_feeds(monkeypatch):
    import app
    client=app.app.test_client()
    monkeypatch.setattr(app,'prepared_snapshot',lambda name,max_age:data(cluster()))
    monkeypatch.setattr(app,'utcnow',lambda:NOW)
    monkeypatch.setattr(w,'fetch',lambda *a,**kw:pytest.fail('No bulk source call on a page view'))
    assert client.get('/api/test/conditions?lat=nan&lon=0').status_code==400
    assert client.get('/api/test/conditions?lat=44.9&lon=-93.4&minutes=10').status_code==400
    result=client.get('/api/test/conditions?lat=44.9&lon=-93.4').get_json()
    assert result['available'] and len(result['stations'])==4
    monkeypatch.setattr(w,'point_forecast',lambda *a:{'periods':[{'endTime':w.iso(NOW+timedelta(hours=5))}],'source':'NWS'})
    assert client.get('/api/test/forecast?lat=44.9&lon=-93.4').status_code==200
    monkeypatch.setattr(app,'prepared_snapshot',lambda *a:None)
    assert client.get('/api/test/conditions?lat=44.9&lon=-93.4').status_code==503
    # A station failure does not break the independent forecast endpoint.
    assert client.get('/api/test/forecast?lat=44.9&lon=-93.4').status_code==200


def test_test_tab_does_not_change_original_metar_products_or_history():
    root=Path(__file__).resolve().parents[1]
    html=(root/'static/index.html').read_text()
    import re
    ids=re.findall(r'\bid="([^"]+)"',html)
    assert len(ids)==len(set(ids))
    assert 'id="tab-test"' in html and 'id="tab-expmet"' not in html
    assert 'const historyHours=4;' in (root/'static/metar-views.js').read_text()
    assert 'value="plots">PLOTS' in html and 'value="clouds">CLOUDS' in html
    installer=(root/'setup-weather-lab-test.sh').read_text()
    assert "--schedule='*/5 * * * *'" in installer
    assert '--set-env-vars' not in installer.split('gcloud run services update weather-lab',1)[1].split('\n',1)[0]
    assert '--min-instances' not in installer
    assert 'jobs pause weather-live-metar-clouds' not in installer
    assert 'domain-mappings' not in installer


def test_test_parser_screens_sensor_faults_and_can_derive_missing_dewpoint(tmp_path):
    from scipy.io import netcdf_file
    import numpy as np
    from test_regional_madis import payload, NOW as FIXTURE_NOW
    from regional_madis import parse_file
    raw=payload(tmp_path,[{'stationId':'FAULT','dewpoint':-9999.},
                          {'stationId':'GOOD','dewpoint':-9999.},
                          {'stationId':'RESERVED','dewpoint':-9999.}])
    path=tmp_path/'sensors.nc';path.write_bytes(gzip.decompress(raw))
    with netcdf_file(path,'a') as n:
        f=n.createVariable('temperatureStatus','i',('recNum',));f[:]=[2,0,4]
        f=n.createVariable('relHumidity','d',('recNum',));f.units=b'percent';f[:]=[50,50,50]
    rows=parse_file(gzip.compress(path.read_bytes()),FIXTURE_NOW,excluded_stations=(),sensor_status_checks=True,derive_dewpoint=True)
    by_id={r['station']:r for r in rows}
    assert by_id['FAULT']['tempF'] is None and by_id['FAULT']['dewpointF'] is None
    assert by_id['GOOD']['tempF']==68 and by_id['GOOD']['dewpointF']==pytest.approx(48.7,abs=.1)
    assert by_id['RESERVED']['tempF']==68,'Reserved status with affirmative QC is usable'
