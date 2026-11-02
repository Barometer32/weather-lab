from datetime import timedelta
import copy
import gzip
import json
from unittest.mock import patch

import pytest
import point_history as h
import point_weather as w
from test_test_weather import row, cluster, data, NOW


class Store:
    def __init__(self):self.objects={};self.json={};self.deleted=[]
    def read(self,key):return self.objects.get(key)
    def write(self,key,value,content_type):self.objects[key]=value
    def read_json(self,key):return copy.deepcopy(self.json.get(key))
    def write_json(self,key,value):self.json[key]=copy.deepcopy(value)
    def exists(self,key):return key in self.objects
    def list_keys(self,prefix):return [key for key in self.objects if key.startswith(prefix)]
    def delete(self,key):self.deleted.append(key);self.objects.pop(key,None)


def report_hour(target,value=50):
    return [{**r,'time':w.iso(target-timedelta(minutes=5)),'tempF':value} for r in cluster()]


def test_archive_retains_each_observation_and_filters_by_actual_time_and_location():
    store=Store();hour=NOW.replace(minute=0)
    rows=report_hour(NOW)+report_hour(NOW-timedelta(minutes=5),45)+[row('REMOTE',lon=-110)]
    h.save_archive(store,'mesonet',hour,rows)
    result=h.nearby_archive(store.read(h.archive_key('mesonet',hour)),44.92,-93.42,NOW-timedelta(minutes=12),NOW)
    assert len(result)==8,'Do not collapse all five-minute reports into one per hour'
    assert {r['tempF'] for r in result}=={45,50}
    assert all(r['station']!='REMOTE' for r in result)
    assert h.nearby_archive(None,44,-93,NOW,NOW)==[]


def test_twelve_hour_point_history_uses_30_minute_windows_without_future_or_stale_fill():
    store=Store();hour=NOW.replace(minute=0)
    for offset in range(14):
        target=NOW-timedelta(hours=offset)
        rows=report_hour(target,50-offset)
        if offset==4:rows=[] # A missing hour stays a gap, never a carried reading.
        if offset==5:rows=[{**r,'time':w.iso(target-timedelta(minutes=31))} for r in rows]
        h.save_archive(store,'mesonet',hour-timedelta(hours=offset),rows)
    result=h.history(store,data(cluster()),44.925,-93.415,NOW)
    assert len(result['frames'])==13
    assert result['windowStart']==w.iso(NOW-timedelta(hours=12)) and result['windowEnd']==w.iso(NOW)
    by_time={frame['time']:frame for frame in result['frames']}
    for offset in (4,5):assert not by_time[w.iso(NOW-timedelta(hours=offset))]['available']
    assert by_time[w.iso(NOW-timedelta(hours=3))]['fields']['temperatureF']['value']==47
    assert result['frames'][-1]['historical'] is False and result['frames'][-1]['fields']['temperatureF']['value']==50
    for frame in result['frames']:
        if frame.get('observationStart'):
            assert w.stamp(frame['time'])-timedelta(minutes=30)<=w.stamp(frame['observationStart'])
            assert w.stamp(frame['observationEnd'])<=w.stamp(frame['time'])


def test_backfill_downloads_missing_archives_once_but_never_runs_from_regular_collection():
    store=Store();calls=[]
    with patch.object(h,'parse_file',return_value=cluster()):
        h.backfill(store,NOW,hours=2,download=lambda url:(calls.append(url) or b'file'))
    assert len(calls)==6
    with patch.object(h,'parse_file',side_effect=AssertionError('No second bulk backfill')):
        h.backfill(store,NOW,hours=2,download=lambda url:pytest.fail('Already archived'))
    with patch.object(h,'backfill',side_effect=AssertionError('No backfill in five-minute collector')):
        with patch.object(w,'parse_file',return_value=cluster()),patch.object(w,'airport_rows',return_value=[]):
            w.collect(store,NOW,download=lambda url,meta:(b'fresh',{'etag':'new'}))
    assert len(store.objects)==6


def test_reissued_archive_replaces_rejected_reports_and_retention_is_scoped():
    store=Store();hour=NOW.replace(minute=0)
    h.save_archive(store,'mesonet',hour,cluster())
    h.save_archive(store,'mesonet',hour,cluster()[1:])
    assert len(h.nearby_archive(store.read(h.archive_key('mesonet',hour)),44.92,-93.42,NOW-timedelta(hours=1),NOW))==3
    old=h.archive_key('rwis',hour-timedelta(hours=25));store.objects[old]=b'old'
    keep=h.archive_key('rwis',hour-timedelta(hours=12));store.objects[keep]=b'keep'
    unrelated=h.PREFIX+'unrelated.json';store.objects[unrelated]=b'leave'
    store.objects['radar/old.bin']=b'leave'
    h.prune(store,NOW)
    assert store.deleted==[old] and keep in store.objects and unrelated in store.objects and 'radar/old.bin' in store.objects
    h.prune(store,NOW);assert store.deleted==[old]


def test_history_route_is_read_only_and_separate_from_forecast(monkeypatch):
    import app
    store=Store();store.json[w.KEY]=data(cluster())
    monkeypatch.setattr(app,'get_store',lambda:store)
    monkeypatch.setattr(app,'prepared_snapshot',lambda *a:data(cluster()))
    monkeypatch.setattr(app,'utcnow',lambda:NOW)
    monkeypatch.setattr(w,'fetch',lambda *a,**k:pytest.fail('No source downloads on history page view'))
    h._history_cache.clear()
    client=app.app.test_client()
    assert client.get('/api/test/history?lat=nan&lon=0').status_code==400
    result=client.get('/api/test/history?lat=44.925&lon=-93.415').get_json()
    assert len(result['frames'])==13 and result['observationWindowMinutes']==30
    assert result['frames'][-1]['available'] and not result['frames'][0]['available']
    assert not store.objects and not store.json.get('locations'),'No location tracking or writes from page views'


def test_current_sample_uses_request_time_not_the_start_of_a_five_minute_bucket():
    store=Store();h._history_cache.clear()
    request_time=NOW+timedelta(minutes=2,seconds=10)
    latest_time=NOW+timedelta(minutes=1)
    observations=[{**r,'time':w.iso(latest_time)} for r in cluster()]
    saved=data(observations);saved['checkedAt']=w.iso(latest_time);store.json[w.KEY]=saved
    result=h.get_history(store,44.925,-93.415,request_time,saved['checkedAt'])
    assert result['frames'][-1]['time']==w.iso(request_time)
    assert result['frames'][-1]['available']
    assert result['frames'][-1]['observationEnd']==w.iso(latest_time)
    assert h.get_history(store,44.925,-93.415,request_time+timedelta(seconds=10),saved['checkedAt']) is result
