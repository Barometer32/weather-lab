from datetime import datetime,timedelta,timezone
from io import BytesIO
from unittest.mock import patch
import json
from PIL import Image
import pytest
import collector
from satellite import BASE,latest_frames,parse_loop
from test_realtime import MemoryStore

NOW=datetime(2026,10,24,15,tzinfo=timezone.utc)


def source(stamp=NOW,broken=None,count=48):
    prefix=BASE+'/truecolor/S_Minnesota.truecolor.'
    urls=[prefix+(stamp-timedelta(minutes=10+i*5)).strftime('%Y%m%d.%H%M%S')+'.jpg' for i in range(count)]
    data=BytesIO();Image.new('RGB',(1600,900),(60,80,100)).save(data,format='JPEG');jpeg=data.getvalue();calls=[]
    def fetch(url):
        calls.append(url)
        if 'satrad' in url:return ' '.join(urls).encode()
        return b'broken' if url==broken else jpeg
    return fetch,calls,urls,jpeg


class AtomicStore(MemoryStore):
    def write_json(self,key,data):
        if key.startswith('live/satellite-'):
            assert len(data['frames'])<=24
            assert all(self.read(f['url'].removeprefix('/api/prepared/')) is not None for f in data['frames'])
        super().write_json(key,data)


def test_cold_backfill_has_24_images_and_reuses_all_bytes_on_repeat():
    store=AtomicStore();fetch,calls,_,jpeg=source()
    with patch('app.download',side_effect=fetch):
        result=collector.collect_product(store,'truecolor',NOW)
        data=store.read_json('live/satellite-truecolor.json')
        assert result['frames']==24 and len(data['frames'])==24
        assert data['frames'][0]['time']=='2026-10-24T12:55:00Z'
        assert data['frames'][-1]['time']=='2026-10-24T14:50:00Z'
        assert store.read(data['frames'][0]['url'].removeprefix('/api/prepared/'))==jpeg
        assert len(calls)==25
        collector.collect_product(store,'truecolor',NOW+timedelta(minutes=2))
        assert len(calls)==26,'a repeated source check never redownloads saved imagery'


def test_bad_recent_image_is_replaced_by_next_older_available_source_image():
    store=AtomicStore();_,_,urls,_=source();fetch,calls,_,_=source(broken=urls[0])
    with patch('app.download',side_effect=fetch):collector.collect_product(store,'truecolor',NOW)
    data=store.read_json('live/satellite-truecolor.json')
    assert len(data['frames'])==24 and data['unavailableImages']==1
    assert data['frames'][0]['time']=='2026-10-24T12:50:00Z'
    assert data['frames'][-1]['time']=='2026-10-24T14:45:00Z'
    assert len(calls)==26


def test_new_image_replaces_oldest_slot_and_keeps_24():
    store=AtomicStore();first,_,_,_=source()
    with patch('app.download',side_effect=first):collector.collect_product(store,'truecolor',NOW)
    fetch,calls,_,_=source(NOW+timedelta(minutes=5))
    with patch('app.download',side_effect=fetch):collector.collect_product(store,'truecolor',NOW+timedelta(minutes=5))
    data=store.read_json('live/satellite-truecolor.json')
    assert len(data['frames'])==24 and len(calls)==2
    assert data['frames'][0]['time']=='2026-10-24T13:00:00Z'
    assert data['frames'][-1]['time']=='2026-10-24T14:55:00Z'


def test_fewer_images_are_reported_truthfully_and_source_failures_preserve_history():
    store=AtomicStore();fetch,_,_,_=source(count=7)
    with patch('app.download',side_effect=fetch):collector.collect_product(store,'truecolor',NOW)
    before=store.read_json('live/satellite-truecolor.json')
    assert len(before['frames'])==7 and before['historyPending']==17
    with patch('app.download',side_effect=TimeoutError('unavailable')),pytest.raises(TimeoutError):
        collector.collect_product(store,'truecolor',NOW+timedelta(minutes=5))
    assert store.read_json('live/satellite-truecolor.json')==before


def test_future_expired_duplicate_and_malformed_frames_do_not_count_as_history():
    frames=[{'time':'not-a-time'}, {'time':'2026-10-24T15:05:00Z'}, {'time':'2026-10-22T15:00:00Z'},
            {'time':'2026-10-24T14:50:00Z','url':'one'}, {'time':'2026-10-24T14:50:00Z','url':'two'}]
    selected=latest_frames(frames,NOW)
    assert len(selected)==1 and selected[0]['url']=='two'


def test_infrared_has_24_original_images_and_public_prepared_asset_access():
    import app as weather
    from satellite import PRODUCTS
    assert PRODUCTS['13']['label']=='Infrared'
    old,_,urls,jpeg=source()
    infrared=[url.replace('/truecolor/','/13/').replace('.truecolor.','.13.') for url in urls]
    def fetch(url):return ' '.join(infrared).encode() if 'satrad' in url else jpeg
    store=AtomicStore()
    with patch('app.download',side_effect=fetch):result=collector.collect_product(store,'13',NOW)
    data=store.read_json('live/satellite-13.json');assert result['frames']==24
    key=data['frames'][-1]['url'];assert '/satellite/13/' in key
    assert store.read(key.removeprefix('/api/prepared/'))==jpeg
    weather._cache.clear();weather.prepared_image.cache_clear()
    with patch('app.get_store',return_value=store):response=weather.app.test_client().get(key)
    assert response.status_code==200 and response.mimetype=='image/jpeg'
