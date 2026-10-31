from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import gzip
import json

import app
import collector
import madis_map as m
from test_regional_madis import payload

NOW=datetime(2026,10,31,4,15,tzinfo=timezone.utc)
START=NOW.replace(hour=3,minute=0)


class Store:
    def __init__(self):self.data={}
    def read_json(self,k):return deepcopy(self.data.get(k))
    def write_json(self,k,v):self.data[k]=deepcopy(v)


def row(identifier='HPN20',at=None,**kwargs):
    return dict(station=identifier,name='Hopkins MN US HENNEPIN',network='Hennepin West',lat=44.95,lon=-93.41,
                time=m.iso(at or START+timedelta(minutes=58)),tempF=52.,dewpointF=40.,wind={'speedMph':5,'direction':180},layers=[],**kwargs)


def test_network_filter_keeps_public_mesonets_and_excludes_airports_and_labeled_nws():
    for identifier,network in [('HPN20','Hennepin West'),('HPN07','Hennepin West'),('MN085','MnDOT'),('C5791','CWOP'),('ABCM5','RAWS')]:
        assert m.allowed({**row(identifier),'network':network})
    for changes in [dict(station='KMSP'),dict(station='CYWG'),dict(name='NWS office'),dict(provider='ASOS'),dict(network='METAR'),dict(name='National Weather Service'),dict(name='Weather Forecast Office'),dict(provider='NWSCOOP')]:
        assert not m.allowed({**row(),**changes})
    assert not m.allowed(row('ABC12'),{'ABC12'})


def test_latest_uses_any_minute_of_hour_not_only_metar_window_and_honors_newer_bad_reading():
    rows=[row(at=START+timedelta(minutes=15)),row(at=START+timedelta(minutes=40)),row(at=START-timedelta(seconds=1)),row('MN085',at=START+timedelta(hours=1))]
    selected=m.latest(rows,START,START+timedelta(hours=1));assert len(selected)==1 and selected[0]['time'].endswith('03:40:00Z')
    bad={**row(),'tempF':None,'dewpointF':None,'wind':{'speedMph':None,'direction':None}}
    assert not m.latest([row(at=START+timedelta(minutes=40)),bad],START,START+timedelta(hours=1))
    assert not m.latest([{**row(),'time':'2026-10-31T03:55:00'}],START,START+timedelta(hours=1))


def test_snapshot_has_twelve_hourly_frames_and_source_timestamps():
    data=m.snapshot([{'hour':m.iso(START+timedelta(hours=1)),'stations':[row()]}],NOW)
    assert len(data['history'])==12 and data['history'][-1]['hour']=='2026-10-31T04:00:00Z'
    assert data['history'][-1]['stations'][0]['time']=='2026-10-31T03:58:00Z'
    assert data['checkMinutes']==[0,15,30,45] and data['frameIntervalMinutes']==60
    assert not m.present(data,NOW)['stale']
    assert m.present(data,NOW+timedelta(minutes=36))['stale']


def test_actual_netcdf_parser_uses_noaa_qc_field_by_field_and_restores_all_mesonet_ids(tmp_path):
    import regional_madis
    b=payload(tmp_path,[{'stationId':'HPN20','stationName':'Hopkins MN US HENNEPIN','observationTime':(START+timedelta(minutes=40)).timestamp(),'temperatureQCR':1},
                        {'stationId':'MN085','stationName':'MNDOT local','dataProvider':'MNDOT','observationTime':(START+timedelta(minutes=40)).timestamp()},
                        {'stationId':'KMSP','stationName':'Airport ASOS','observationTime':(START+timedelta(minutes=40)).timestamp()}])
    rows=regional_madis.parse_file(b,NOW,window_start=START,window_end=START+timedelta(hours=1),include_invalid=True,excluded_stations=())
    selected=m.latest(rows,START,START+timedelta(hours=1))
    assert {r['station'] for r in selected}=={'HPN20','MN085'}
    h=next(r for r in selected if r['station']=='HPN20');assert h['tempF'] is None and h['dewpointF'] is not None


def test_regular_collection_fetches_only_two_recent_hours_and_reuses_unchanged_files():
    store=Store();calls=[];parses=[]
    def download(url,meta):calls.append((url,meta));return (None if meta else b'data'),{'etag':'v1'}
    def parse(b,now,**kw):parses.append(kw);return [row(at=kw['window_start']+timedelta(minutes=40))]
    r=m.collect(store,NOW,download=download,parse=parse);assert r['latestStations']==1 and len(calls)==2
    m.collect(store,NOW+timedelta(minutes=15),download=download,parse=parse)
    assert len(calls)==4 and len(parses)==2
    assert set(store.data)=={m.KEY} and all(c[0].endswith(('_0300.gz','_0200.gz')) for c in calls)
    assert all(k['include_invalid'] and k['excluded_stations']==() for k in parses)


def test_qc_reissue_replaces_the_hour_instead_of_resurrecting_old_good_values():
    store=Store()
    m.collect(store,NOW,hours=1,download=lambda *a:(b'v1',{}),parse=lambda *a,**k:[row(),row('MN085')])
    m.collect(store,NOW+timedelta(minutes=15),hours=1,download=lambda *a:(b'v2',{}),parse=lambda *a,**k:[row('MN085')])
    assert [r['station'] for r in store.data[m.KEY]['history'][-1]['stations']]==['MN085']


def test_api_reads_prepared_objects_only_and_supports_compression(monkeypatch):
    store=Store();data=m.snapshot([{'hour':m.iso(START+timedelta(hours=1)),'stations':[row()]}],NOW);store.data[m.KEY]=data
    monkeypatch.setattr(app,'get_store',lambda:store);monkeypatch.setattr(app,'utcnow',lambda:NOW);app._cache.clear()
    monkeypatch.setattr(m,'collect',lambda *a:(_ for _ in ()).throw(AssertionError('No source collection on page views')))
    result=app.app.test_client().get('/api/madis-map');assert result.status_code==200
    assert result.json['history'][-1]['stations'][0]['station']=='HPN20' and 'files' not in result.json
    assert result.headers['Cache-Control']=='no-store'
    store.data.clear();app._cache.clear();assert app.app.test_client().get('/api/madis-map').status_code==503


def test_collector_has_an_independent_quarter_hour_product(monkeypatch):
    store=Store();monkeypatch.setattr(collector,'get_store',lambda:store)
    monkeypatch.setattr(m,'collect',lambda *a:{'latestStations':1831})
    result=collector.app.test_client().post('/collect/madis-map')
    assert result.status_code==200 and result.json['result']['latestStations']==1831


def test_all_rejected_reissue_clears_old_bad_hour_but_download_failure_retains_previous_map():
    import pytest
    store=Store()
    m.collect(store,NOW,hours=1,download=lambda *a:(b'v1',{}),parse=lambda *a,**k:[row()])
    m.collect(store,NOW,hours=1,download=lambda *a:(b'v2',{}),parse=lambda *a,**k:[])
    assert not store.data[m.KEY]['history'][-1]['stations']
    before=deepcopy(store.data)
    def fail(*a):raise OSError('Network unavailable')
    with pytest.raises(ValueError):m.collect(store,NOW,hours=1,download=fail)
    assert store.data==before
