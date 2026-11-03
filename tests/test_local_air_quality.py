import csv
from datetime import datetime,timedelta,timezone
from io import StringIO
from unittest.mock import patch
import pytest
import local_air_quality as air

NOW=datetime(2026,11,3,4,45,tzinfo=timezone.utc)
HOUR=NOW.replace(hour=3,minute=0)


def station(name='Shakopee',lat=44.7894,lon=-93.5125,values=None,scores=None):
    return dict(id=name,name=name,lat=lat,lon=lon,start=air.iso(HOUR),end=air.iso(HOUR+timedelta(hours=1)),
        values=values if values is not None else {'PM2.5':8.,'Ozone':30.},
        scores=scores if scores is not None else {'PM2.5':40,'Ozone':30.},source='MPCA')


def snapshot():
    return dict(version=air.VERSION,rows=[station(),station('Other monitor',44.80,-93.53,{'PM10':10.,'NO2':3.},{'PM10':7,'NO2':2})],
                latestHour=air.iso(HOUR),checkedAt=air.iso(NOW),errors=[])


def csv_row():
    values=['']*34
    for i,v in {0:'271390505',1:'Shakopee',2:'Active',4:'44.7894',5:'-93.5125',8:'US',9:'MN',10:'11/03/2026',11:'03:00',12:'MPCA',
                14:'30',16:'40',22:'8',23:'UG/M3',24:'0.030',25:'PPM',26:'3',27:'PPB'}.items():values[i]=v
    out=StringIO();csv.writer(out).writerow(values);return out.getvalue()


def test_each_pollutant_uses_nearest_monitor_with_its_own_value_and_score():
    p=air.local_air(snapshot(),44.782,-93.484,NOW)
    assert p['version']=='local-pollutants-v2' and p['available']
    r={r['pollutant']:r for r in p['readings']}
    assert r['PM2.5']['station']=='Shakopee' and r['PM2.5']['value']==8 and r['PM2.5']['aqi']==40
    assert r['PM10']['station']=='Other monitor' and r['PM10']['value']==10 and r['PM10']['aqi']==7
    assert r['NO2']['aqiType']=='Hourly AQI' and r['Ozone']['aqiType']=='NowCast AQI'
    assert r['PM10']['unit']=='µg/m³' and r['NO2']['unit']=='ppb'
    assert 'mix' not in p and 'aqi' not in p


def test_missing_pollutants_remain_unavailable_not_zero():
    data=snapshot();data['rows']=data['rows'][:1]
    r={r['pollutant']:r for r in air.local_air(data,44.782,-93.484,NOW)['readings']}
    assert r['PM10']['value'] is None and r['PM10']['aqi'] is None
    assert r['NO2']['value'] is None
    assert r['PM2.5']['value']==8


def test_actual_zero_and_negative_instrument_noise_are_not_missing():
    data=snapshot();data['rows'][0]['values']['PM2.5']=-.2;data['rows'][0]['scores']['PM2.5']=0
    r=air.local_air(data,44.782,-93.484,NOW)['readings'][0]
    assert r['value']==0 and r['rawValue']==-.2 and r['aqi']==0


def test_remote_stale_and_future_hour_data_cannot_fill_the_point():
    data=snapshot()
    for r in data['rows']:r.update(lat=46.,lon=-94.)
    assert not air.local_air(data,44.782,-93.484,NOW)['available']
    assert not air.local_air(snapshot(),44.782,-93.484,NOW+timedelta(hours=4))['available']
    assert not air.local_air(snapshot(),44.782,-93.484,HOUR)['available']


def test_parser_normalizes_units_and_ignores_inactive_wrong_hour_nonfinite():
    parsed=air.parse_hour(csv_row(),HOUR)
    assert parsed[0]['values']['Ozone']==30 and parsed[0]['scores']['PM2.5']==40
    assert parsed[0]['end']=='2026-11-03T04:00:00Z'
    assert not air.parse_hour(csv_row().replace('Active','Inactive'),HOUR)
    assert not air.parse_hour(csv_row(),HOUR+timedelta(hours=1))
    assert 'PM2.5' not in air.parse_hour(csv_row().replace(',8,UG/M3',',NaN,UG/M3'),HOUR)[0]['values']


def test_downloads_only_latest_available_hour_not_a_three_hour_history():
    calls=[]
    def fetch(url):calls.append(url);return csv_row()
    data=air.load_snapshot(NOW,fetch)
    assert len(calls)==1 and len(data['rows'])==1
    with pytest.raises(ValueError):air.load_snapshot(NOW,fetch=lambda url:'')


def test_snapshot_is_shared_between_locations_and_failure_keeps_original_time():
    with patch.object(air,'_snapshot',None),patch.object(air,'_checked',float('-inf')),patch.object(air,'load_snapshot',return_value=snapshot()) as fetch,patch.object(air.time,'monotonic',return_value=100):
        a=air.shared_snapshot(NOW);air.shared_snapshot(NOW);assert fetch.call_count==1
        with patch.object(air.time,'monotonic',return_value=2000),patch.object(air,'load_snapshot',side_effect=TimeoutError):failed=air.shared_snapshot(NOW)
        assert failed['errors'] and failed['checkedAt']==a['checkedAt']


def test_endpoint_is_post_only_no_store_and_invalid_points_do_not_download():
    import app
    client=app.app.test_client()
    with patch.object(air,'shared_snapshot',return_value=snapshot()) as shared,patch.object(app,'utcnow',return_value=NOW):
        response=client.post('/api/local-air-quality',json={'latitude':44.782,'longitude':-93.484})
        assert response.status_code==200 and response.json['version']==air.VERSION
        assert response.headers['Cache-Control']=='no-store'
        assert client.get('/api/local-air-quality').status_code==405
        shared.reset_mock()
        assert client.post('/api/local-air-quality',json={'latitude':None,'longitude':-93}).status_code==400
        assert not client.post('/api/local-air-quality',json={'latitude':30,'longitude':-93}).json['available']
        shared.assert_not_called()
