from datetime import timedelta
from unittest.mock import patch
import pytest
import collector
import metar_clouds
from test_metar_history_restore import Store,archive,HOUR,xml,xml_report
import metar_history


def saved_store():
    store=Store();metar_history.publish_history(archive(),store,HOUR)
    return store


def fresh(station):
    return metar_clouds.parse_reports(xml(xml_report(HOUR-timedelta(minutes=7),station=station)),HOUR)


def test_partial_hour_is_revisited_every_two_minutes_until_20_and_cached_afterwards():
    store=saved_store()
    with patch('metar_history.fetch_history',side_effect=[{'reports':fresh('KFCM')},{'reports':fresh('KDEH')}]) as source:
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=2))
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=3))
        assert source.call_count==1,'duplicate calls in one two-minute slot reuse the prepared result'
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=20))
        assert source.call_count==2,'a nonempty partial hour must not stop catch-up downloads'
        collector.collect_metar_clouds(store,HOUR+timedelta(minutes=22))
        assert source.call_count==2,'populated frames settle after the catch-up window'
    assert {r['station'] for r in store.data['live/metar-clouds.json']['stations']}=={'KMSP','KFCM','KDEH'}
    assert len(store.data['live/metar-clouds.json']['history'])==12


def test_entire_missing_hour_still_retries_after_20_and_preserves_saved_history():
    store=saved_store();original=store.data['live/metar-clouds.json']
    with patch('metar_history.fetch_history',side_effect=TimeoutError('NOAA unavailable')) as source:
        for minute in [24,26]:
            with pytest.raises(TimeoutError):collector.collect_metar_clouds(store,HOUR+timedelta(hours=1,minutes=minute))
    assert source.call_count==2
    assert store.data['live/metar-clouds.json']==original
    public=metar_clouds.current(original,HOUR+timedelta(hours=1,minutes=26))
    assert public['history'][-1]['stations']==[]
    assert public['history'][-2]['stations'][0]['station']=='KMSP'


def test_empty_source_batch_is_not_published_as_a_new_hour():
    store=saved_store();original=store.data['live/metar-clouds.json']
    with patch('metar_history.fetch_history',return_value={'reports':[]}):
        with pytest.raises(ValueError,match='previous data retained'):
            collector.collect_metar_clouds(store,HOUR+timedelta(hours=1,minutes=2))
    assert store.data['live/metar-clouds.json']==original
