import copy
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

import app
import airport_feed
import airport_observations as obs

NOW=datetime(2026,11,15,3,30,tzinfo=timezone.utc)

def report(station,temp=1,dew=-3,speed=3.4,direction=0,minutes=5):
    site=airport_feed.inventory()[station]
    return {'station':station,'state':site['state'],'time':airport_feed.iso(NOW-timedelta(minutes=minutes)),
            'tempC':temp,'dewpointC':dew,'reportType':'HFMETAR','temperatureBasis':'decoded-HF-ASOS-Celsius',
            'wind':{'speedMph':speed,'direction':direction}}

def saved(rows):
    return {'version':airport_feed.VERSION,'metroReports':rows,'stations':rows,'checkedAt':airport_feed.iso(NOW),'feed':'NOAA direct HF-ASOS'}

def test_average_celsius_then_convert_and_round_once_and_scalar_mph_once():
    rows=[report('KMSP',direction=350),report('KFCM',direction=10),report('KMIC',temp=2,dew=-2,speed=4.4)]
    result=obs.present(saved(rows),NOW)
    assert result['current']['tempC']==4/3
    assert result['current']['tempF']==34  # Rounding individual F first would yield 35.
    assert result['current']['dewpointF']==27
    assert result['current']['wind']['speedMph']==4  # Individual mph rounding would yield 3.
    assert result['current']['wind']['cardinal']=='N'
    assert {r['station'] for r in result['stations']}==set(obs.STATIONS)

def test_latest_common_time_uses_all_three_and_never_mixes_newer_partial_batch():
    rows=[report(s,minutes=10) for s in obs.STATIONS]+[report('KMSP',temp=10,minutes=5)]
    result=obs.present(saved(rows),NOW)
    assert result['current']['observedAt']==airport_feed.iso(NOW-timedelta(minutes=10))
    assert len({r['time'] for r in result['stations']})==1
    incomplete=obs.present(saved(rows[-1:]+[report('KFCM',minutes=10)]),NOW)
    assert incomplete['current'] is None and incomplete['waiting']

def test_missing_temperature_no_two_station_average_expiration_and_old_source_age():
    rows=[report(s,minutes=25) for s in obs.STATIONS]
    result=obs.present(saved(rows),NOW)
    assert result['sourceDelayed'] and result['ageMinutes']==25
    rows[0]['tempC']=None
    assert obs.present(saved(rows),NOW)['current'] is None
    assert obs.present(saved([report(s,minutes=61) for s in obs.STATIONS]),NOW)['current'] is None

def test_missing_wind_never_invents_speed_but_temperature_still_uses_three():
    rows=[report(s) for s in obs.STATIONS];rows[0]['wind']['speedMph']=None
    value=obs.present(saved(rows),NOW)['current']
    assert value['tempF']==34 and value['wind']['speedMph'] is None
    assert obs.wind_average([report(s,speed=0) for s in obs.STATIONS])['cardinal']=='CALM'

def test_shared_history_keeps_exact_time_corrections_and_all_five_minute_slots():
    rows=[report(s,minutes=10) for s in obs.STATIONS]
    previous=saved(rows)
    pool=airport_feed.metro_history(previous,[report('KMSP',minutes=5),report('KMIC',temp=None,minutes=10)],NOW)
    assert len(pool)==4
    assert next(r for r in pool if r['station']=='KMIC')['tempC'] is None

def test_api_uses_only_shared_prepared_snapshot_and_home_tab_is_first():
    snapshot=saved([report(s) for s in obs.STATIONS]);app._cache.clear()
    class Store:
        def read_json(self,key):assert key==airport_feed.KEY;return copy.deepcopy(snapshot)
    with patch('app.get_store',return_value=Store()),patch('app.utcnow',return_value=NOW),patch('app.download') as source:
        r=app.app.test_client().get('/api/airport-observations')
    assert r.status_code==200 and r.json['current']['tempF']==34
    assert r.headers['Cache-Control']=='no-store';source.assert_not_called()
    html=app.app.test_client().get('/').text
    assert html.index('id="tab-observations"')<html.index('id="tab-metar"')
    assert 'id="tab-observations" aria-selected="true"' in html


def test_calm_display_uses_rounded_average_threshold():
    for speed in [0, 2.9, 3, 3.49]:
        wind=obs.wind_average([report(s,speed=speed) for s in obs.STATIONS])
        assert wind['cardinal']=='CALM' and wind['direction'] is None
    assert obs.wind_average([report(s,speed=3.5) for s in obs.STATIONS])['cardinal']=='N'


def test_variable_wind_keeps_speed_but_excludes_direction_with_one_or_two_fixed_bearings():
    rows=[report(s,speed=9,direction=270) for s in obs.STATIONS]
    rows[0]['wind'].update(variable=True,speedMph=18,direction=90)
    wind=obs.wind_average(rows)
    assert wind['speedMph']==12 and wind['cardinal']=='W'
    rows[1]['wind'].update(variable=True,direction=90)
    assert obs.wind_average(rows)['cardinal']=='W'
    rows[2]['wind'].update(variable=True)
    wind=obs.wind_average(rows)
    assert wind['speedMph']==12 and wind['direction'] is None and wind['cardinal']=='Variable'


def test_missing_bearing_does_not_discard_other_fixed_directions_or_scalar_speeds():
    rows=[report(s,speed=8,direction=350) for s in obs.STATIONS]
    rows[0]['wind']['direction']=None
    rows[1]['wind']['direction']=10
    assert obs.wind_average(rows)['cardinal']=='N'
    for r in rows:r['wind']['direction']=None
    assert obs.wind_average(rows)['cardinal']=='Unknown'


def test_mobile_card_positions_and_no_summary_celsius_subtitles():
    html=app.app.test_client().get('/').text
    css=app.app.test_client().get('/static/style.css').text
    assert 'observations-temperature-c' not in html and 'observations-dewpoint-c' not in html
    assert 'grid-template-areas:"temperature wind" "dewpoint sun"' in css
    assert all('observation-'+name in html for name in ['temperature','dewpoint','wind','sun'])
