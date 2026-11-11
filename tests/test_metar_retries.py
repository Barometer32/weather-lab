from datetime import timedelta
from unittest.mock import patch
import pytest
import collector
import metar_clouds
from test_metar_history_restore import Store,archive,HOUR,xml,xml_report
import metar_history


@pytest.fixture(autouse=True)
def archive_fallback_only():
    # These tests exercise archive retry behavior when bulk data is unavailable.
    with patch('collector.weather.download',return_value=xml()):
        yield


def saved_store():
    store=Store();metar_history.publish_history(archive(),store,HOUR)
    return store


def fresh(station):
    return metar_clouds.parse_reports(xml(xml_report(HOUR-timedelta(minutes=7),station=station)),HOUR)


def test_hour_is_revisited_every_two_minutes_including_after_20():
    store=saved_store()
    with patch('metar_history.fetch_history',side_effect=[{'reports':fresh('KFCM')},{'reports':fresh('KDEH')},{'reports':fresh('KSTP')}]) as source:
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=2))
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=3))
        assert source.call_count==1,'duplicate calls in one two-minute slot reuse the prepared result'
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=20))
        assert source.call_count==2,'a nonempty partial hour must not stop catch-up downloads'
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=22))
        assert source.call_count==3,'later corrections still update on two-minute checks'
    assert {r['station'] for r in store.data['live/metar-clouds.json']['stations']}=={'KMSP','KFCM','KDEH','KSTP'}
    assert len(store.data['live/metar-clouds.json']['history'])==12


def test_entire_missing_hour_still_retries_after_20_and_preserves_saved_history():
    store=saved_store();original=store.data['live/metar-clouds.json']
    with patch('metar_history.fetch_history',side_effect=TimeoutError('NOAA unavailable')) as source:
        for minute in [24,26]:
            with pytest.raises(TimeoutError):collector.collect_metar_clouds(store,HOUR+timedelta(hours=1,minutes=minute))
    assert source.call_count==2
    assert store.data['live/metar-clouds.json']==original
    public=metar_clouds.current(original,HOUR+timedelta(hours=1,minutes=26))
    assert public['history'][-1]['stations'][0]['station']=='KMSP'
    assert public['history'][-1]['hour']==metar_clouds.iso(HOUR)
    assert public['pendingHour']==metar_clouds.iso(HOUR+timedelta(hours=1))


def test_empty_source_batch_is_not_published_as_a_new_hour():
    store=saved_store();original=store.data['live/metar-clouds.json']
    with patch('metar_history.fetch_history',return_value={'reports':[]}):
        with pytest.raises(ValueError,match='previous data retained'):
            collector.collect_metar_clouds(store,HOUR+timedelta(hours=1,minutes=2))
    assert store.data['live/metar-clouds.json']==original


def test_api_read_at_hour_boundary_keeps_twelve_real_frames_and_actual_times():
    saved=saved_store().data['live/metar-clouds.json']
    for minute in [0,2,10,35]:
        public=metar_clouds.current(saved,HOUR+timedelta(hours=1,minutes=minute))
        assert len(public['history'])==12
        assert all(f['stations'] for f in public['history'])
        assert public['history'][-1]['hour']==metar_clouds.iso(HOUR)
        assert public['stations'][0]['time']==metar_clouds.iso(HOUR-timedelta(minutes=7))
        assert public['checkedAt']==saved['checkedAt']
        assert public['pendingHour']==metar_clouds.iso(HOUR+timedelta(hours=1))


def test_api_advances_to_a_successfully_collected_hour():
    store=saved_store()
    next_hour=HOUR+timedelta(hours=1)
    reports=metar_clouds.parse_reports(xml(xml_report(next_hour-timedelta(minutes=7))),next_hour)
    with patch('metar_history.fetch_history',return_value={'reports':reports}):
        collector.collect_metar_clouds(store,next_hour+timedelta(minutes=5))
    public=metar_clouds.current(store.data['live/metar-clouds.json'],next_hour+timedelta(minutes=6))
    assert public['history'][-1]['hour']==metar_clouds.iso(next_hour)
    assert public['pendingHour'] is None
