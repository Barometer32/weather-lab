from datetime import datetime,timedelta,timezone
from io import BytesIO
import copy
import gzip
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from scipy.io import netcdf_file
import current_analysis as c

NOW=datetime(2026,11,3,3,30,tzinfo=timezone.utc)


def row(station='A',age=10,lat=44.925,lon=-93.463,temp=60,dew=50,speed=5,direction=180,**extra):
    return dict(station=station,name=station,lat=lat,lon=lon,time=c.iso(NOW-timedelta(minutes=age)),tempF=temp,dewpointF=dew,
        wind=dict(speedMph=speed,direction=direction),network='Hennepin West',provider='MesoWest',source='NOAA MADIS',**extra)


def observations(n=7,airport=False,**extra):
    rows=[row(str(i),lat=44.925+i*.01,lon=-93.463+i*.005,**extra) for i in range(n)]
    if airport:
        for r in rows:r.update(network="HF-METAR",provider="HF-METAR")
    return rows


class Store:
    def __init__(self):self.docs={}
    def read_json(self,k):return copy.deepcopy(self.docs.get(k))
    def write_json(self,k,v):self.docs[k]=copy.deepcopy(v)


def test_state_filter_uses_real_mn_wi_polygons():
    assert c.state_for(44.925,-93.463)=='MN'
    assert c.state_for(43.0748,-89.3848)=='WI'
    assert c.state_for(46.,-96.9) is None # ND despite being inside bounding box
    assert c.state_for(42.,-93.) is None


def test_latest_window_has_inclusive_30_minutes_and_no_future_reports():
    rows=[row('A',age=20,temp=50),row('A',age=5,temp=60),row('B',age=30,lat=44.93),row('C',age=30.01),row('D',age=-1),row('IA',lat=42,lon=-93)]
    chosen=c.latest(rows,NOW)
    assert {r['station'] for r in chosen}=={'A','B'}
    assert next(r for r in chosen if r['station']=='A')['tempF']==60


def test_duplicate_physical_sensor_receives_only_one_vote():
    assert len(c.latest([row('HPN20'),row('alias',age=8)],NOW))==1
    assert c.latest([row('HPN20'),row('alias',age=8)],NOW)[0]['station']=='alias'


def test_same_airport_is_not_counted_twice_when_feed_coordinates_differ():
    rows=[row('KMSP'),row('KMSP',age=5,lat=44.926,lon=-93.462)]
    chosen=c.latest(rows,NOW)
    assert len(chosen)==1 and chosen[0]['time']==c.iso(NOW-timedelta(minutes=5))
    rows=[row('KABC'),row('ABC',lat=44.926),row('KABC',lat=45.4)]
    assert len(c.latest(rows,NOW))==2,'Different places sharing an ID stay separate'


def test_grid_uses_five_nearest_stations_and_exact_constant_field():
    data=dict(stations=observations(9,airport=True),checkedAt=c.iso(NOW))
    result=c.analysis(data,44.925,-93.463,NOW)
    assert result['available'] and not result['stale']
    assert result['gridSpacingKm']==5
    assert result['fields']['temperatureF']['value']==60
    assert result['fields']['dewpointF']['value']==50
    assert result['fields']['windMph']['value']==5
    assert result['windDirection']==180
    assert all(f['stationCount']==5 for f in result['fields'].values())
    assert {r['station'] for r in result['stations']}==set('01234')
    assert abs(sum(r['weightsPct']['temperature'] for r in result['stations'])-100)<.3


def test_distance_and_age_weighting_favor_close_and_recent():
    rows=observations(5);rows[0]['tempF']=62;rows[1]['tempF']=58
    result=c.analysis(dict(stations=rows,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    weights={r['station']:r['weightsPct']['temperature'] for r in result['stations']}
    assert weights['0']>weights['1']
    a=row('young',age=2,lat=44.925,lon=-93.453);b=row('old',age=25,lat=44.925,lon=-93.473)
    result=c.analysis(dict(stations=[a,b,*observations(3)[1:]],checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    weights={r['station']:r['weightsPct']['temperature'] for r in result['stations']}
    assert weights['young']>weights['old']


def test_vector_wind_wraps_north_and_calm_needs_no_bearing():
    rows=observations(4,airport=True)
    for i,r in enumerate(rows):r['wind']=dict(speedMph=10,direction=350 if i%2 else 10)
    result=c.analysis(dict(stations=rows,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    assert result['windDirection']<15 or result['windDirection']>345
    for r in rows:r['wind']=dict(speedMph=0,direction=None)
    result=c.analysis(dict(stations=rows,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    assert result['fields']['windMph']['value']==0 and result['windDirection'] is None


def test_rejects_sparse_and_remote_support_instead_of_filling_fake_values():
    for rows in [observations(2),[row(str(i),lat=45.4+i*.01) for i in range(5)]]:
        result=c.analysis(dict(stations=rows,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
        assert not result['available']
    assert not c.analysis(dict(stations=observations(),checkedAt=c.iso(NOW)),40,-100,NOW)['available']


def test_expired_snapshot_is_refiltered_on_read_and_not_held_as_current():
    data=dict(stations=observations(),checkedAt=c.iso(NOW))
    result=c.analysis(data,44.925,-93.463,NOW+timedelta(minutes=21))
    assert not result['available'] and result['stale']


def test_spatial_qc_rejects_isolated_field_without_losing_other_measurements():
    rows=observations(7);rows[0]['tempF']=100
    rows,count=c.spatial_qc(rows)
    assert count==1 and rows[0]['tempF'] is None
    assert rows[0]['dewpointF']==50 and rows[0]['wind']['speedMph']==5


def test_front_or_time_spread_does_not_trigger_simple_quorum_outlier_rejection():
    rows=observations(7)
    for i,r in enumerate(rows):r['tempF']=40+i*6
    assert c.spatial_qc(rows)[1]==0
    rows=observations(7);rows[0]['tempF']=100;rows[0]['time']=c.iso(NOW-timedelta(minutes=29))
    assert c.spatial_qc(rows)[1]==0


def test_collection_crosses_hour_boundary_and_reuses_conditional_regional_rows():
    store=Store();calls=[]
    def download(url,old):calls.append((url,old));return (b'new',{'etag':'v1'}) if not old else (None,old)
    with patch.object(c,'parse_file',return_value=observations(age=30)),patch.object(c,'airport_rows',return_value=[]):
        first=c.collect(store,NOW.replace(minute=5),download)
        second=c.collect(store,NOW.replace(minute=10),download)
    assert len(calls)==14 and any('/mesonet/' in url and '0200.gz' in url for url,_ in calls)
    assert any(old for _,old in calls[7:])
    assert first['stations'] and second['stations']


def test_failed_feeds_preserve_prepared_data_but_successful_empty_batch_clears_expired_rows():
    store=Store();store.write_json(c.KEY,{'sentinel':'unchanged'})
    def fail(*args):raise TimeoutError('offline')
    with pytest.raises(ValueError):c.collect(store,NOW,fail)
    assert store.read_json(c.KEY)=={'sentinel':'unchanged'}
    with patch.object(c,'parse_file',return_value=[]),patch.object(c,'airport_rows',return_value=[]):
        data=c.collect(store,NOW,lambda *a:(b'new',{}))
    assert data['stations']==[]


def test_current_api_requires_no_upstream_requests_and_post_coordinates():
    import app
    store=Store();store.write_json(c.KEY,dict(stations=observations(),checkedAt=c.iso(NOW)))
    app._cache.clear()
    with patch.object(app,'get_store',return_value=store),patch.object(app,'utcnow',return_value=NOW),patch.object(app,'download',side_effect=AssertionError('No visitor downloads')):
        client=app.app.test_client()
        response=client.post('/api/current',json={'latitude':44.925,'longitude':-93.463})
        assert response.status_code==200 and response.json['available']
        assert response.headers['Cache-Control']=='no-store'
        assert response.headers['Permissions-Policy']=='geolocation=(self)'
        assert client.post('/api/current',json={'latitude':'nan','longitude':0}).status_code==400
        assert client.get('/api/current').status_code==405


def test_navigation_has_five_tabs_no_metar_and_only_one_shot_location_calls():
    import re
    html=(Path(__file__).parents[1]/'static/index.html').read_text()
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['current','radar','clouds','satellite','forecast']
    assert 'metar-product' not in html and 'id="metar"' not in html
    location=(Path(__file__).parents[1]/'static/location-choice.js').read_text()
    assert location.count('getCurrentPosition(')==1 and 'watchPosition' not in location


def test_cloud_api_keeps_only_mn_wi_and_sends_no_unused_surface_values():
    import app
    frames=[dict(hour=c.iso(NOW),stations=[dict(row('MN'),reportType='METAR',layers=[dict(cover='BKN',baseFtAGL=2000)]),dict(row('IA',lat=42,lon=-93),reportType='METAR')]) for _ in range(12)]
    prepared=dict(history=frames,checkedAt=c.iso(NOW))
    with patch.object(app,'prepared_hourly_snapshot',return_value=prepared),patch('metar_clouds.current',side_effect=lambda data,now:copy.deepcopy(data)):
        response=app.app.test_client().get('/api/clouds')
    assert response.status_code==200
    assert response.json['region']==['MN','WI']
    assert [s['station'] for s in response.json['history'][0]['stations']]==['MN']
    assert 'tempF' not in response.json['stations'][0] and 'wind' not in response.json['stations'][0]


def test_isolated_collector_publishes_only_shared_data_and_retains_failure_semantics():
    import current_collector as private
    store=Store();client=private.app.test_client()
    with patch.object(private,'get_store',return_value=store),patch.object(private,'collect',return_value={'stations':observations(),'errors':[]}):
        assert client.post('/collect/current-analysis').status_code==200
        assert client.post('/collect/satellite').status_code==404
    with patch.object(private,'get_store',return_value=store),patch.object(private,'collect',side_effect=TimeoutError('offline')):
        assert client.post('/collect/current-analysis').status_code==502
    assert private.lock.acquire(blocking=False)
    private.lock.release()


def test_wind_uses_airports_only_while_temperature_and_dewpoint_keep_nearby_mesonet_weights():
    mesonets=observations(5,speed=0,temp=60,dew=50)
    airports=observations(3,airport=True,speed=12,direction=180,temp=80,dew=65)
    for i,r in enumerate(airports):r.update(station='K'+str(i),lat=45.02+i*.01,lon=-93.50)
    airports[0].update(provider='AWC',network='Airport METAR')
    result=c.analysis(dict(stations=mesonets+airports,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    assert result['windPolicy']=='airports-only-v1'
    assert result['fields']['windMph']['value']==12 and result['windDirection']==180
    assert result['fields']['temperatureF']['value']==60 and result['fields']['dewpointF']['value']==50
    for r in result['stations']:
        if c.airport_wind_site(r):assert set(r['weightsPct'])=={'wind'}
        else:assert set(r['weightsPct'])=={'temperature','dewpoint'}


def test_sheltered_mesonet_winds_and_station_density_cannot_change_airport_wind():
    airports=observations(3,airport=True)
    for i,r in enumerate(airports):r['wind']['speedMph']=5+i*10
    before=c.analysis(dict(stations=airports,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    crowd=[row('meso'+str(i),lat=44.925+(i+1)*.0003,lon=-93.463,speed=100,direction=0) for i in range(15)]
    after=c.analysis(dict(stations=airports+crowd,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    assert after['fields']['windMph']['value']==before['fields']['windMph']['value']
    assert after['windDirection']==before['windDirection']


def test_insufficient_airports_does_not_fall_back_to_mesonet_wind():
    airports=observations(2,airport=True)
    mesonets=observations(5)
    for i,r in enumerate(mesonets):r.update(station='KFAKE'+str(i),lat=44.98+i*.01)
    result=c.analysis(dict(stations=airports+mesonets,checkedAt=c.iso(NOW)),44.925,-93.463,NOW)
    assert result['available'] and result['fields']['temperatureF']['value']==60
    assert result['fields']['windMph']['value'] is None and result['windMessage']
    assert not any('wind' in r['weightsPct'] for r in result['stations'])
