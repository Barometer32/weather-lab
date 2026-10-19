from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from satellite import parse_loop, BASE
import native_radar as radar
import app as weather
from test_realtime import MemoryStore

NOW=datetime(2026,10,19,19,tzinfo=timezone.utc)


def test_satellite_window_keeps_every_available_frame_over_two_hours_not_24_slots():
    prefix=BASE+'/truecolor/S_Minnesota.truecolor.'
    html=' '.join(prefix+(NOW-timedelta(minutes=i)).strftime('%Y%m%d.%H%M%S')+'.jpg' for i in range(-2,125,2))
    data=parse_loop(html,'truecolor',NOW)
    assert len(data['frames'])==61
    assert data['frames'][0]['time']==weather.iso(NOW-timedelta(hours=2))
    assert data['frames'][-1]['time']==weather.iso(NOW)


def test_stream_discovery_failure_still_publishes_latest_and_recovers_old_archive():
    store=MemoryStore()
    volumes=[{'key':'old','time':weather.iso(NOW-timedelta(minutes=115))},
             {'key':'new','time':weather.iso(NOW-timedelta(minutes=5))}]
    def consume(key,site):
        time=next(v['time'] for v in volumes if v['key']==key)
        return [({'id':key,'time':time,'endTime':time,'gateWidthMeters':250,'azimuthSpacing':.5,'vcp':35,'nominalElevation':.5},b'packet')],None
    def fetch(url,header=False):
        if header: raise TimeoutError('stream directory unavailable')
        return url.removeprefix(radar.ARCHIVE)
    with patch('native_radar.archive_volumes',return_value=volumes),patch('native_radar.fetch',side_effect=fetch),patch('native_radar.decode',side_effect=lambda x:x),patch('native_radar.consume',side_effect=consume):
        result=radar.collect_site(store,NOW,'KMPX',[],budget=45)
    frames=store.read_json('live/radar-KMPX.json')['frames']
    assert [f['id'] for f in frames]==['old','new']
    assert result['historyPending']==0
    assert result['errors']==1
    assert store.writes.index('radar/'+radar.VERSION+'/KMPX/new.bin')<store.writes.index('radar/'+radar.VERSION+'/KMPX/old.bin')


def test_forecast_remains_fresh_between_half_hour_collection_times():
    store=MemoryStore()
    store.write_json('live/forecast.json',{'checkedAt':weather.iso(NOW),'periods':[]})
    weather._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW+timedelta(minutes=29)):
        assert weather.prepared_snapshot('forecast',2100)['stale'] is False
    weather._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW+timedelta(minutes=36)):
        assert weather.prepared_snapshot('forecast',2100)['stale'] is True


def test_satellite_public_snapshot_rolls_two_hour_window_without_source_requests():
    store=MemoryStore()
    store.write_json('live/satellite-truecolor.json',{'checkedAt':weather.iso(NOW),'frames':[{'time':weather.iso(NOW-timedelta(minutes=n))} for n in [125,115,5]]})
    weather._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as source:
        data=weather.app.test_client().get('/api/satellite/truecolor').json
    assert len(data['frames'])==2
    assert data['windowStart']==weather.iso(NOW-timedelta(hours=2))
    source.assert_not_called()
