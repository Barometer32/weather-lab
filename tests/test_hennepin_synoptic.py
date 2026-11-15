from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import hennepin_synoptic as direct
import observation_stations as obs
from test_observation_stations import Store, sample

NOW = datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc)


def response():
    return {"SUMMARY":{"RESPONSE_CODE":1},
            "UNITS":{"air_temp":"Fahrenheit","dew_point_temperature":"Fahrenheit","wind_speed":"Miles/hour","wind_direction":"Degrees"},
            "STATION":[{"STID":"HPN20","MNET_ID":"257","NAME":"Hopkins","LATITUDE":"44.95556","LONGITUDE":"-93.41139",
                        "OBSERVATIONS":{"date_time":[obs.iso(NOW-timedelta(minutes=10)),obs.iso(NOW-timedelta(minutes=5))],
                            "air_temp_set_1":[40,39],"dew_point_temperature_set_1d":[30,29],
                            "wind_speed_set_1":[7,8],"wind_direction_set_1":[270,315]}}]}


def test_direct_rows_share_one_actual_timestamp_and_keep_precise_units():
    rows=direct.parse(response(),NOW)
    assert len(rows)==1 and rows[0]['time']==obs.iso(NOW-timedelta(minutes=5))
    assert rows[0]['tempF']==39 and rows[0]['dewpointF']==29
    assert rows[0]['wind']=={'speedMph':8,'direction':315}
    assert rows[0]['source']=='Synoptic direct'
    assert direct.fresh_complete(rows[0],NOW)
    assert not direct.fresh_complete(dict(rows[0],dewpointF=None),NOW)


def test_direct_rejects_wrong_network_excluded_sites_future_times_and_units():
    data=response();data['STATION'][0]['MNET_ID']='1';assert direct.parse(data,NOW)==[]
    data=response();data['STATION'][0]['STID']='HPN04';assert direct.parse(data,NOW)==[]
    data=response();data['UNITS']['wind_speed']='Knots'
    with pytest.raises(ValueError):direct.parse(data,NOW)
    data=response();data['STATION'][0]['OBSERVATIONS']['date_time']=[obs.iso(NOW+timedelta(minutes=5))]*2
    assert direct.parse(data,NOW)==[]


def test_full_fresh_direct_coverage_skips_large_madis_downloads():
    rows=[sample(code,time=obs.iso(NOW-timedelta(minutes=5)),source='Synoptic direct') for code in direct.STATIONS]
    store=Store()
    with patch.dict('os.environ',{'WEATHER_SYNOPTIC_TOKEN':'private-test-token'}),patch('hennepin_synoptic.fetch',return_value=rows),patch('regional_madis.fetch') as fallback:
        result=obs.collect(store,NOW)
    fallback.assert_not_called()
    assert result['directFeedStatus']=='19/19 fresh approved stations'
    assert len(obs.present_map(store.read_json(obs.KEY),NOW)['stations'])==19


def test_direct_failure_preserves_reports_and_does_not_persist_token():
    store=Store({obs.KEY:{'version':obs.VERSION,'stations':[sample(time=obs.iso(NOW-timedelta(minutes=30)))]}})
    with patch.dict('os.environ',{'WEATHER_SYNOPTIC_TOKEN':'private-test-token'}),patch('hennepin_synoptic.fetch',side_effect=RuntimeError('url?token=private-test-token')):
        obs.collect(store,NOW,lambda *args:(None,{}))
    saved=store.read_json(obs.KEY)
    assert 'private-test-token' not in str(saved)
    assert saved['directFeedStatus'].startswith('unavailable')
    assert saved['stations'][0]['time']==obs.iso(NOW-timedelta(minutes=30))


def test_partial_direct_and_fallback_keep_newest_actual_report_per_station():
    store=Store({obs.KEY:{'version':obs.VERSION,'stations':[sample('HPN24',time=obs.iso(NOW-timedelta(minutes=30)))]}})
    fresh=sample(time=obs.iso(NOW-timedelta(minutes=5)),source='Synoptic direct')
    older=sample(time=obs.iso(NOW-timedelta(minutes=20)),tempF=99)
    with patch.dict('os.environ',{'WEATHER_SYNOPTIC_TOKEN':'private-test-token'}),patch('hennepin_synoptic.fetch',return_value=[fresh]),patch('regional_madis.parse_file',return_value=[older]):
        obs.collect(store,NOW,lambda *args:(b'data',{}))
    saved=store.read_json(obs.KEY)
    assert len(saved['stations'])==2
    assert next(r for r in saved['stations'] if r['station']=='HPN20')['time']==fresh['time']
