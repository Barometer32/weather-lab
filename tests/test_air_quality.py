from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

from PIL import Image
import pytest
import air_quality as aq
import app as weather
import collector
from test_realtime import MemoryStore

NOW=datetime(2026,10,24,0,5,tzinfo=timezone.utc)


def png(color):
    out=BytesIO();Image.new('RGBA',(aq.WIDTH,aq.HEIGHT),color).save(out,format='PNG');return out.getvalue()


def feature_data():
    ring=lambda w,s,e,n:[aq.mercator(w,s),aq.mercator(w,n),aq.mercator(e,n),aq.mercator(e,s),aq.mercator(w,s)]
    contours=[dict(attributes=dict(gridcode=2,Timestamp=(NOW-timedelta(hours=1)).timestamp()*1000),
                   geometry=dict(rings=[ring(-98,42,-90,49),ring(-94,44,-93,45)]))]
    x,y=aq.mercator(-95,46)
    monitors=[dict(attributes=dict(OZONEPM_AQI_SORT=127,ValidTime=(NOW-timedelta(hours=1)).timestamp()*1000),geometry=dict(x=x,y=y))]
    return contours,monitors


def fetcher():
    contours,monitors=feature_data();base=png('white');overlay=png((0,0,0,0));calls=[]
    def fetch(url):
        calls.append(url)
        if '/query?' in url:return json.dumps(dict(features=contours if aq.CONTOURS in url else monitors)).encode()
        return base if aq.BASE in url else overlay
    return fetch,calls


def test_snapshot_is_atomic_and_records_capture_and_distinct_source_times():
    store=MemoryStore();fetch,calls=fetcher();result=aq.collect(store,NOW,fetch)
    data=store.read_json('live/air-quality.json');frame=data['frames'][0]
    assert result['frames']==1 and result['monitors']==1
    assert frame['time']==aq.iso(NOW)
    assert frame['sourceTime']==aq.iso(NOW-timedelta(hours=1))
    assert frame['monitorOldest']==frame['sourceTime']
    assert len(data['frames'])==1,'never invent the eleven hours before collection started'
    key=frame['url'].removeprefix('/api/prepared/')
    assert store.writes.index(key)<store.writes.index('live/air-quality.json')
    with Image.open(BytesIO(store.read(key))) as image:
        assert image.size==(aq.WIDTH,aq.HEIGHT)
        x,y=aq.xy(aq.mercator(-93.5,44.5));assert image.getpixel((round(x),round(y)))==(255,255,255),'contour holes remain unfilled'
        x,y=aq.xy(aq.mercator(-92,46));assert image.getpixel((round(x),round(y)))==(255,255,0)
    aq.collect(store,NOW+timedelta(minutes=20),fetch);assert len(calls)==4,'same-hour retries do not duplicate snapshots'


def test_rolling_twelve_hours_and_static_basemap_cache():
    store=MemoryStore();fetch,calls=fetcher()
    for hours in range(14):aq.collect(store,NOW+timedelta(hours=hours),fetch)
    frames=store.read_json('live/air-quality.json')['frames'];assert len(frames)==12
    assert frames[0]['time']==aq.iso(NOW+timedelta(hours=2))
    assert sum('/export?' in url for url in calls)==2,'static geography is downloaded only once'
    assert len(aq.public_manifest(store.read_json('live/air-quality.json'),NOW+timedelta(hours=16))['frames'])==9


def test_source_failure_preserves_saved_manifest_and_images():
    store=MemoryStore();fetch,_=fetcher();aq.collect(store,NOW,fetch);old=dict(store.objects)
    def failed(url):raise TimeoutError('source unavailable')
    with pytest.raises(TimeoutError):aq.collect(store,NOW+timedelta(hours=1),failed)
    assert store.objects==old


def test_empty_contours_never_replace_previous_snapshot():
    store=MemoryStore();fetch,_=fetcher();aq.collect(store,NOW,fetch);before=store.read('live/air-quality.json')
    def empty(url):return b'{"features":[]}' if aq.CONTOURS in url else fetch(url)
    with pytest.raises(ValueError,match='contours'):aq.collect(store,NOW+timedelta(hours=1),empty)
    assert store.read('live/air-quality.json')==before


def test_query_pages_and_reports_upstream_errors():
    calls=[]
    def fetch(url):
        params=parse_qs(urlsplit(url).query);calls.append(params)
        return json.dumps(dict(features=[{}],exceededTransferLimit=len(calls)==1)).encode()
    assert len(aq.query(aq.CONTOURS,'gridcode',fetch))==2
    assert calls[1]['resultOffset']==['2000']
    with pytest.raises(ValueError,match='query failed'):aq.query(aq.CONTOURS,'gridcode',lambda url:b'{"error":{"code":500}}')


def test_history_api_reads_only_saved_data_and_preserves_actual_history_length():
    store=MemoryStore();fetch,_=fetcher();aq.collect(store,NOW,fetch);weather._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('air_quality.download') as source:
        response=weather.app.test_client().get('/api/air-quality')
    assert response.status_code==200 and len(response.json['frames'])==1
    assert response.json['historyPending'] is True and response.headers['Cache-Control']=='no-store'
    source.assert_not_called()


def test_unprepared_api_has_clear_state_and_assets_are_allowlisted():
    weather._cache.clear();weather.prepared_image.cache_clear();store=MemoryStore()
    with patch('app.get_store',return_value=store):
        client=weather.app.test_client();assert client.get('/api/air-quality').status_code==503
        assert client.get('/api/prepared/air-quality/maps/mn-region-v1-base.png').status_code==404
        assert client.get('/api/prepared/live/air-quality.json').status_code==404
        key='air-quality/mn-region-v1/20261024000500.png';store.write(key,png('red'),'image/png')
        response=client.get('/api/prepared/'+key);assert response.status_code==200 and response.mimetype=='image/png'


def test_private_collector_routes_air_quality_and_keeps_failures_non_destructive():
    with patch('collector.get_store',return_value=MemoryStore()),patch('collector.weather.utcnow',return_value=NOW),patch('air_quality.collect',return_value={'frames':1}) as collect:
        result=collector.app.test_client().post('/collect/air-quality')
    assert result.status_code==200 and result.json['result']['frames']==1
    collect.assert_called_once()


def test_snapshot_lifecycle_does_not_expire_cached_geography():
    rules=json.load(open('data-lifecycle.json'))['rule']
    prefixes=[p for rule in rules for p in rule['condition'].get('matchesPrefix',[])]
    assert 'air-quality/mn-region-v1/' in prefixes
    assert not any('air-quality/maps/'.startswith(p) for p in prefixes)
