from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from unittest.mock import patch
import copy

import app
import collector
import observation_stations as obs

NOW=datetime(2026,10,24,18,23,tzinfo=timezone.utc)


class Store:
    def __init__(self,data=None): self.data=copy.deepcopy(data or {})
    def read_json(self,key): return copy.deepcopy(self.data.get(key))
    def write_json(self,key,value): self.data[key]=copy.deepcopy(value)


def sample(code="HPN20",**changes):
    row={"station":code,"name":"Hopkins MN US HENNEPIN","network":"Hennepin West","lat":44.95556,"lon":-93.41139,
         "time":obs.iso(NOW-timedelta(minutes=20)),"tempF":71.4,"dewpointF":50.6,"wind":{"speedMph":7,"direction":222.5}}
    row.update(changes);return row


def test_county_boundary_uses_geometry_instead_of_rectangle_or_old_radius():
    assert obs.in_county(45.1182,-93.4283)  # Maple Grove, outside old ten-mile radius.
    assert obs.in_county(44.83196,-93.47098)  # Eden Prairie.
    assert not obs.in_county(45.16,-93.29)  # Anoka County, inside county bounding box.
    assert not obs.in_county(44.797,-93.527)  # Shakopee.
    assert not obs.in_county(None,-93.4)


def test_latest_keeps_only_hennepin_west_and_retains_partial_fields_and_corrections():
    old=sample(time=obs.iso(NOW-timedelta(minutes=40)))
    fresh=sample(tempF=None)
    corrected=sample(tempF=None,dewpointF=None)
    quiet=sample("HPN24",time=obs.iso(NOW-timedelta(hours=3)))
    rows=obs.latest([old,fresh,corrected,quiet,sample("CWOP1",network="CWOP"),sample("KMSP",network="Airport ASOS (5 min)"),sample("OUT",lat=45.16,lon=-93.29),sample("EXPIRED",time=obs.iso(NOW-timedelta(days=2)))],NOW)
    assert {r['station'] for r in rows}=={'HPN20','HPN24'}
    assert next(r for r in rows if r['station']=='HPN20')['tempF'] is None
    result=obs.present({'version':obs.VERSION,'stations':rows,'checkedAt':obs.iso(NOW)},NOW)
    assert result['average'] is None
    assert next(r for r in result['stations'] if r['station']=='HPN20')['ageMinutes']==20
    assert not result['collectorDelayed']


def test_current_and_previous_files_conditional_refresh_and_equal_time_qc_correction():
    store=Store();calls=[]
    def download(url,meta):calls.append((url,meta));return b'data',{'etag':url[-11:]}
    with patch('regional_madis.parse_file',return_value=[sample()]) as meso,patch('madis_observations.parse_file',return_value=[]):
        data=obs.collect(store,NOW,download)
    assert len(calls)==2
    assert all("hfmetar" not in url for url,_ in calls)
    assert any('20261024_1800.gz' in url for url,_ in calls)
    assert any('20261024_1700.gz' in url for url,_ in calls)
    assert all(call.kwargs['excluded_stations']==() for call in meso.call_args_list)
    assert len(data['stations'])==1
    again=obs.collect(store,NOW+timedelta(minutes=2),lambda url,meta:(None,meta))
    assert again['stations'][0]['time']==data['stations'][0]['time']
    with patch('regional_madis.parse_file',return_value=[sample(tempF=None)]),patch('madis_observations.parse_file',return_value=[]):
        corrected=obs.collect(store,NOW+timedelta(minutes=3),download)
    assert corrected['stations'][0]['tempF'] is None


def test_failed_source_retains_known_station_time_and_reports_failure():
    store=Store({obs.KEY:{'version':obs.VERSION,'stations':[sample()],'checkedAt':obs.iso(NOW)}})
    def fail(url,meta):raise RuntimeError('source unavailable')
    data=obs.collect(store,NOW+timedelta(minutes=2),fail)
    assert data['stations'][0]['time']==sample()['time']
    assert len(data['sourceFailures'])==2
    assert data['average'] is None


def test_current_hour_404_is_normal_and_never_creates_fake_station_data():
    store=Store()
    def download(url,meta):
        if '_1800' in url:raise HTTPError(url,404,'Not ready',{},None)
        return b'data',{}
    with patch('regional_madis.parse_file',return_value=[sample()]),patch('madis_observations.parse_file',return_value=[]):
        data=obs.collect(store,NOW,download)
    assert not data['sourceFailures']
    assert data['stations'][0]['time']==sample()['time']


def test_public_route_only_reads_saved_data_and_private_route_collects_inventory():
    store=Store({obs.KEY:{'version':obs.VERSION,'stations':[sample()],'checkedAt':obs.iso(NOW)}})
    app._cache.pop('prepared-observation-stations',None)
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('regional_madis.fetch') as fetch:
        response=app.app.test_client().get('/api/observation-stations')
    assert response.status_code==200 and response.json['average'] is None
    assert response.json['stations'][0]['station']=='HPN20'
    assert response.headers['Cache-Control']=='no-store'
    fetch.assert_not_called()
    with patch('collector.get_store',return_value=store),patch('collector.weather.utcnow',return_value=NOW),patch('observation_stations.collect',return_value={'stations':[sample()],'sourceFailures':[]}):
        result=collector.app.test_client().post('/collect/observation-stations')
    assert result.status_code==200 and result.json['result']['stations']==1
