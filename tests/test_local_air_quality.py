import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import patch
import math
import pytest
import local_air_quality as air

NOW=datetime(2026,11,3,4,45,tzinfo=timezone.utc)
HOUR=NOW.replace(hour=3,minute=0)


def rows():
    result=[]
    for n in (2,1,0):
        hour=HOUR-timedelta(hours=n)
        result.append(dict(id='local',name='Shakopee',lat=44.7894,lon=-93.5125,
            start=air.iso(hour),end=air.iso(hour+timedelta(hours=1)),
            values={'PM2.5':8.,'Ozone':30.,'NO2':10.},scores={'PM2.5':40,'Ozone':30},
            areas=['Southern Twin Cities Metro'],source='MPCA'))
    return result


def snapshot():
    area=dict(name='Southern Twin Cities Metro',state='MN',lat=44.71,lon=-93.25,
              pollutant='PM2.5',value=40,time='2026-11-03T04:00:00Z')
    return dict(rows=rows(),areas=[area,{**area,'pollutant':'Ozone','value':30}],
                latestHour=air.iso(HOUR),checkedAt=air.iso(NOW),errors=[])


def csv_row():
    values=['']*34
    for i,v in {0:'271390505',1:'Shakopee',2:'Active',4:'44.7894',5:'-93.5125',8:'US',9:'MN',
                10:'11/03/2026',11:'03:00',12:'MPCA',13:'Southern Twin Cities Metro',
                14:'30',16:'40',22:'8',23:'UG/M3',24:'0.030',25:'PPM',26:'10',27:'PPB'}.items():values[i]=v
    out=StringIO();csv.writer(out).writerow(values);return out.getvalue()


def test_classic_formula_uses_concentrations_and_rises_with_other_pollutants():
    p={'PM2.5':20.,'Ozone':60.,'NO2':10.}
    expected=1000/10.4*sum(math.expm1(air.COEFFICIENTS[k]*v) for k,v in p.items())
    result=air.classic_aqhi(p)
    assert result['rawValue']==round(expected,3)
    assert result['rawValue']>air.classic_aqhi({**p,'Ozone':10.})['rawValue']
    assert abs(sum(result['contributionsPct'].values())-100)<.2
    assert air.classic_aqhi({'PM2.5':20.,'Ozone':60.}) is None
    assert air.classic_aqhi(dict.fromkeys(p,0))['value']==1
    assert air.classic_aqhi(dict.fromkeys(p,1000))['display']=='10+'


def test_missing_one_hour_is_unavailable_not_zero_or_different_timestamps():
    data=snapshot();data['rows'][0]['values'].pop('NO2')
    p=air.local_air(data,44.782,-93.484,NOW)
    assert p['aqi']['value']==40
    assert p['mix'] is None and 'unavailable' in p['mixMessage'].lower()


def test_closest_complete_monitor_has_real_distance_and_exact_three_hour_window():
    p=air.local_air(snapshot(),44.782,-93.484,NOW)
    assert p['mix']['official'] is False and p['mix']['method']=='Classic 3-pollutant AQHI estimate'
    assert p['mix']['start']=='2026-11-03T01:00:00Z' and p['mix']['end']=='2026-11-03T04:00:00Z'
    assert len(p['components'])==3 and all(c['stationId']=='local' for c in p['components'])
    assert all(2<c['distanceKm']<3 for c in p['components'])
    assert p['aqi']['primaryPollutant']=='PM2.5' and p['aqi']['value']==40


def test_remote_stations_and_expired_observations_do_not_fill_the_mix():
    data=snapshot()
    for row in data['rows']:row.update(lat=46.,lon=-94.)
    assert air.local_air(data,44.782,-93.484,NOW)['mix'] is None
    result=air.local_air(snapshot(),44.782,-93.484,NOW+timedelta(hours=4))
    assert result['aqi'] is None and result['mix'] is None


def test_parser_converts_units_and_ignores_inactive_wrong_hour_and_nonfinite():
    parsed=air.parse_hour(csv_row(),HOUR)
    assert parsed[0]['values']['Ozone']==30
    assert parsed[0]['scores']['PM2.5']==40
    assert parsed[0]['end']=='2026-11-03T04:00:00Z','AirNow file timestamps mark the START of the sampled hour'
    assert not air.parse_hour(csv_row().replace('Active','Inactive'),HOUR)
    assert not air.parse_hour(csv_row(),HOUR+timedelta(hours=1))
    parsed=air.parse_hour(csv_row().replace(',8,UG/M3',',NaN,UG/M3'),HOUR)
    assert 'PM2.5' not in parsed[0]['values']


def test_reporting_area_time_uses_supplied_offset_once_even_after_dst():
    text='11/02/26|11/02/26|22:00|CST|0|O|Y|Southern Twin Cities Metro|MN|44.7100|-93.2500|PM2.5|40|Good|No||MPCA'
    assert air.parse_areas(text,NOW)[0]['time']=='2026-11-03T04:00:00Z'
    assert not air.parse_areas(text.replace('|O|','|F|'),NOW)
    assert not air.parse_areas(text,NOW+timedelta(hours=4))


def test_no_current_sources_does_not_create_a_clean_air_score():
    with pytest.raises(ValueError):air.load_snapshot(NOW,fetch=lambda url:'')


def test_snapshot_is_shared_across_locations_and_failure_is_visible():
    with patch.object(air,'_snapshot',None),patch.object(air,'_checked',float('-inf')),patch.object(air,'load_snapshot',return_value=snapshot()) as fetch,patch.object(air.time,'monotonic',return_value=100):
        a=air.shared_snapshot(NOW);air.shared_snapshot(NOW)
        assert fetch.call_count==1
        with patch.object(air.time,'monotonic',return_value=2000),patch.object(air,'load_snapshot',side_effect=TimeoutError):
            failed=air.shared_snapshot(NOW)
        assert failed['errors']
        assert failed['checkedAt']==a['checkedAt']


def test_endpoint_accepts_only_post_coordinates_and_sends_no_store():
    import app
    client=app.app.test_client()
    with patch.object(air,'shared_snapshot',return_value=snapshot()) as shared,patch.object(app,'utcnow',return_value=NOW):
        response=client.post('/api/local-air-quality',json={'latitude':44.782,'longitude':-93.484})
        assert response.status_code==200 and response.json['aqi']['value']==40
        assert response.headers['Cache-Control']=='no-store'
        assert client.get('/api/local-air-quality').status_code==405
        shared.reset_mock()
        assert client.post('/api/local-air-quality',json={'latitude':None,'longitude':-93}).status_code==400
        shared.assert_not_called()
        response=client.post('/api/local-air-quality',json={'latitude':30,'longitude':-93})
        assert response.json['aqi'] is None and response.json['mix'] is None
        shared.assert_not_called()
