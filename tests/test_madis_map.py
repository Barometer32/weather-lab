from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
import pytest

import app
import collector
import madis_map as m
from test_regional_madis import payload

NOW=datetime(2026,10,31,4,15,tzinfo=timezone.utc)

class Store:
    def __init__(self):self.data={}
    def read_json(self,k):return deepcopy(self.data.get(k))
    def write_json(self,k,v):self.data[k]=deepcopy(v)


def row(identifier='HPN20',at=None,**kwargs):
    return dict(station=identifier,name='Hopkins MN US HENNEPIN',network='Hennepin West',lat=44.95,lon=-93.41,
                time=m.iso(at or NOW-timedelta(minutes=10)),tempF=52.,dewpointF=40.,wind={'speedMph':5,'direction':180},layers=[],**kwargs)


def test_network_filter_keeps_public_mesonets_and_excludes_airports_and_labeled_nws():
    for identifier,network in [('HPN20','Hennepin West'),('HPN07','Hennepin West'),('MN085','MnDOT'),('C5791','CWOP'),('ABCM5','RAWS')]:
        assert m.allowed({**row(identifier),'network':network})
    for changes in [dict(station='KMSP'),dict(station='CYWG'),dict(name='NWS office'),dict(provider='ASOS'),dict(network='METAR'),dict(name='National Weather Service'),dict(name='Weather Forecast Office'),dict(provider='NWSCOOP')]:
        assert not m.allowed({**row(),**changes})
    assert not m.allowed(row('ABC12'),{'ABC12'})


def test_current_window_is_inclusive_25_minutes_and_newest_per_station_wins():
    start=NOW-timedelta(minutes=25)
    rows=[row(at=NOW-timedelta(minutes=18)),row(at=NOW-timedelta(minutes=10)),
          row('MN085',at=NOW-timedelta(minutes=18)),row('EDGE',at=start),row('NOW',at=NOW),
          row('OLD',at=start-timedelta(seconds=1)),row('FUTURE',at=NOW+timedelta(seconds=1))]
    data=m.snapshot(rows,NOW)
    assert {r['station']:r['time'] for r in data['stations']}=={
        'HPN20':m.iso(NOW-timedelta(minutes=10)),'MN085':m.iso(NOW-timedelta(minutes=18)),
        'EDGE':m.iso(start),'NOW':m.iso(NOW)}
    assert data['windowStart']=='2026-10-31T03:50:00Z' and data['windowEnd']=='2026-10-31T04:15:00Z'
    assert data['checkMinutes']==[0,15,30,45] and data['windowMinutes']==25 and 'history' not in data


def test_newer_qc_rejected_record_suppresses_older_good_values():
    bad={**row(),'tempF':None,'dewpointF':None,'wind':{'speedMph':None,'direction':None}}
    assert not m.snapshot([row(at=NOW-timedelta(minutes=20)),bad],NOW)['stations']
    assert not m.snapshot([{**row(),'time':'2026-10-31T04:05:00'}],NOW)['stations']


def test_actual_netcdf_parser_uses_noaa_qc_field_by_field(tmp_path):
    import regional_madis
    b=payload(tmp_path,[{'stationId':'HPN20','stationName':'Hopkins MN US HENNEPIN','observationTime':(NOW-timedelta(minutes=10)).timestamp(),'temperatureQCR':1},
                        {'stationId':'MN085','stationName':'MNDOT local','dataProvider':'MNDOT','observationTime':(NOW-timedelta(minutes=18)).timestamp()},
                        {'stationId':'KMSP','stationName':'Airport ASOS','observationTime':(NOW-timedelta(minutes=10)).timestamp()}])
    rows=regional_madis.parse_file(b,NOW,window_start=NOW-timedelta(minutes=25),window_end=NOW+timedelta(microseconds=1),include_invalid=True,excluded_stations=())
    selected=m.snapshot(rows,NOW)['stations']
    assert {r['station'] for r in selected}=={'HPN20','MN085'}
    h=next(r for r in selected if r['station']=='HPN20');assert h['tempF'] is None and h['dewpointF'] is not None


def test_hour_boundary_reads_both_files_and_selects_latest_across_them():
    store=Store();calls=[]
    def download(url,meta):calls.append(url);return (b'previous' if '_0300.gz' in url else b'current'),{'etag':'v1'}
    def parse(b,now,**kw):
        return [row(at=NOW-timedelta(minutes=18)),row('MN085',at=NOW-timedelta(minutes=20))] if b==b'previous' else [row()]
    result=m.collect(store,NOW,download=download,parse=parse)
    assert result['latestStations']==2 and len(calls)==2
    assert {r['station']:r['time'] for r in store.data[m.KEY]['stations']}=={'HPN20':m.iso(NOW-timedelta(minutes=10)),'MN085':m.iso(NOW-timedelta(minutes=20))}
    assert set(store.data)=={m.KEY} # Never changes airport history.


def test_half_hour_uses_only_current_file_and_304_is_refiltered_to_new_window():
    store=Store();calls=[];parses=[]
    def download(url,meta):calls.append((url,meta));return (None if meta else b'v1'),{'etag':'v1'}
    def parse(b,now,**kw):parses.append(kw);return [row('HPN20',at=NOW+timedelta(minutes=5)),row('MN085',at=NOW-timedelta(minutes=10))]
    m.collect(store,NOW+timedelta(minutes=15),download=download,parse=parse)
    assert len(calls)==1 and calls[0][0].endswith('_0400.gz')
    m.collect(store,NOW+timedelta(minutes=30),download=download,parse=parse)
    assert len(calls)==2 and len(parses)==1 and calls[-1][1]=={'etag':'v1'}
    assert [r['station'] for r in store.data[m.KEY]['stations']]==['HPN20'] # :20 is exactly 25 minutes old.


def test_missing_new_hour_file_at_top_of_hour_still_uses_previous_hour():
    store=Store();now=NOW.replace(minute=0)
    def download(url,meta):
        if url.endswith('_0400.gz'):raise HTTPError(url,404,'Not ready',{},None)
        return b'previous',{}
    m.collect(store,now,download=download,parse=lambda *a,**k:[row(at=now-timedelta(minutes=7))])
    assert len(store.data[m.KEY]['stations'])==1 and not store.data[m.KEY]['errors']


def test_qc_reissue_replaces_file_and_bad_latest_cannot_revive_old_good_record():
    store=Store()
    def download(url,meta):return (b'old' if url.endswith('_0300.gz') else b'new'),{}
    bad={**row(),'tempF':None,'dewpointF':None,'wind':{'speedMph':None}}
    m.collect(store,NOW,download=download,parse=lambda b,*a,**k:[row(at=NOW-timedelta(minutes=18))] if b==b'old' else [bad,row('MN085')])
    assert [r['station'] for r in store.data[m.KEY]['stations']]==['MN085']
    m.collect(store,NOW,download=download,parse=lambda *a,**k:[])
    assert not store.data[m.KEY]['stations']


def test_download_failure_retains_prior_snapshot_without_advancing_timestamp():
    store=Store();m.collect(store,NOW,download=lambda *a:(b'v1',{}),parse=lambda *a,**k:[row()])
    before=deepcopy(store.data)
    def fail(*a):raise OSError('Network unavailable')
    with pytest.raises(ValueError):m.collect(store,NOW+timedelta(minutes=15),download=fail)
    assert store.data==before
    assert m.present(before[m.KEY],NOW+timedelta(minutes=40))['stale']


def test_api_reads_prepared_current_snapshot_only_and_exposes_source_times(monkeypatch):
    store=Store();store.data[m.KEY]=m.snapshot([row()],NOW)
    monkeypatch.setattr(app,'get_store',lambda:store);monkeypatch.setattr(app,'utcnow',lambda:NOW);app._cache.clear()
    monkeypatch.setattr(m,'collect',lambda *a:(_ for _ in ()).throw(AssertionError('No source collection on page views')))
    result=app.app.test_client().get('/api/madis-map');assert result.status_code==200
    assert result.json['stations'][0]['station']=='HPN20' and result.json['stations'][0]['time']==row()['time']
    assert 'files' not in result.json and 'history' not in result.json
    assert result.headers['Cache-Control']=='no-store'
    store.data.clear();app._cache.clear();assert app.app.test_client().get('/api/madis-map').status_code==503


def test_collector_has_an_independent_quarter_hour_product(monkeypatch):
    store=Store();monkeypatch.setattr(collector,'get_store',lambda:store)
    monkeypatch.setattr(m,'collect',lambda *a:{'latestStations':1831})
    result=collector.app.test_client().post('/collect/madis-map')
    assert result.status_code==200 and result.json['result']['latestStations']==1831
