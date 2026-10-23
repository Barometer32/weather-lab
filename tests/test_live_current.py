from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError

import app
import collector
import live_current as live
from test_realtime import MemoryStore
from test_madis_observations import fixture

NOW=datetime(2026,10,21,3,45,tzinfo=timezone.utc)


def reports(now=NOW, minutes=(0,5,15)):
    return [dict(icaoId=s,obsTime=(now-timedelta(minutes=m)).timestamp(),temp=t,dewp=d,wspd=5,wdir=350,
                 source=live.SOURCE_NAME,metarType='HFMETAR')
            for s,m,t,d in zip(app.STATIONS,minutes,[10,11,12],[5,6,7])]


def saved(rows, now=NOW):
    return dict(version=live.VERSION,reports=rows,lastGood=live.candidate(rows,now),checkedAt=app.iso(now),sourceFailures=[])


def binary(qc_failure=False):
    with patch('test_madis_observations.NOW',NOW.replace(minute=55)):
        return fixture(qc_failure=qc_failure)


def test_mean_celsius_and_mean_actual_timestamps():
    c=live.candidate(reports(),NOW)
    assert c['available'] and c['observedAt']=='2026-10-21T03:38:20Z'
    assert c['tempC']==11 and c['tempF']==51.8 and c['dewpointF']==42.8
    assert [s['tempC'] for s in c['stations']]==[10,11,12]


def test_only_madis_hfmetar_at_five_minute_marks_is_eligible():
    good=reports(minutes=(0,0,0))
    for bad in [dict(source='NOAA Aviation Weather Center'),dict(source='IEM airport METAR/5-minute archive'),
                dict(metarType='METAR'),dict(metarType='SPECI'),dict(obsTime=NOW.timestamp()-60)]:
        assert not live.candidate([{**r,**bad} for r in good],NOW)['available']
    # A newer routine report cannot displace a qualifying MADIS report.
    other=[{**r,'source':'NOAA Aviation Weather Center','metarType':'METAR','obsTime':NOW.timestamp()+60,'temp':50} for r in good]
    assert live.candidate(good+other,NOW+timedelta(minutes=1))['tempC']==11


def test_timestamp_spread_hold_preserves_whole_mean_and_original_time_then_resumes():
    doc=saved(reports(minutes=(0,5,10)));original=deepcopy(doc['lastGood'])
    doc['reports'][0].update(obsTime=NOW.timestamp()+600,temp=20)
    doc['checkedAt']=app.iso(NOW+timedelta(minutes=10))
    state=live.present(doc,NOW+timedelta(minutes=10))
    assert state['held'] and state['current']==original
    assert state['candidate']['timestampSpreadSeconds']==1200
    for row in doc['reports']:row['obsTime']=NOW.timestamp()+600
    state=live.present(doc,NOW+timedelta(minutes=10))
    assert not state['held'] and state['current']['observedAt']==app.iso(NOW+timedelta(minutes=10))


def test_bad_latest_madis_report_holds_instead_of_using_older_good_report():
    doc=saved(reports(minutes=(0,0,0)))
    doc['reports'].append({**doc['reports'][0],'obsTime':NOW.timestamp()+300,'dewp':40})
    state=live.present(doc,NOW+timedelta(minutes=5))
    assert state['held'] and state['candidate']['invalidStations']==['KFCM']
    assert state['current']['observedAt']==app.iso(NOW)


def test_missing_station_is_not_a_two_station_average_and_old_reports_do_not_expire():
    assert not live.candidate(reports()[:2],NOW)['available']
    for hours in [1,3,24]:
        state=live.present(saved(reports()),NOW+timedelta(hours=hours))
        assert state['available'] and not state['held']
        assert state['current']['observedAt']=='2026-10-21T03:38:20Z'
    assert live.present(None,NOW)['current'] is None


def test_user_delayed_example_boundary_and_cross_midnight():
    now=NOW.replace(hour=4,minute=0)
    c=live.candidate(reports(now,minutes=(20,25,35)),now)
    assert c['available'] and c['timestampSpreadSeconds']==900
    assert c['observedAt']=='2026-10-21T03:33:20Z'
    assert not live.candidate(reports(now,minutes=(20,25,40)),now)['available']
    now=NOW.replace(hour=0,minute=5)
    assert live.candidate(reports(now,minutes=(0,5,10)),now)['observedAt']=='2026-10-21T00:00:00Z'
    variable=reports(now,minutes=(0,5,10));variable[0]['wdir']='VRB'
    assert live.candidate(variable,now)['wind']['direction'] is None


def test_collection_only_fetches_madis_files_and_decodes_whole_celsius():
    now=NOW.replace(hour=4,minute=5);calls=[];payload=binary()
    def download(url):
        calls.append(url)
        assert url.startswith('https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/hfmetar/netCDF/')
        if '20261021_0400' in url:raise HTTPError(url,404,'not ready',{},None)
        return payload
    data=live.collect(MemoryStore(),now,download)
    assert len(calls)==2 and data['available'] and not data['held'] and data['sourceFailures']==[]
    assert data['current']['observedAt']=='2026-10-21T03:48:20Z'
    assert [s['tempC'] for s in data['current']['stations']]==[24,24,25]
    assert data['current']['tempF']==75.8
    assert all(s['source']==live.SOURCE_NAME for s in data['current']['stations'])


def test_no_madis_data_never_falls_back_to_old_mixed_feed_cache():
    store=MemoryStore();doc=saved(reports());doc['version']='latest-three-airports-celsius-spread-v2'
    store.write_json('live/current.json',doc)
    assert live.present(doc,NOW)['current'] is None
    calls=[]
    def fail(url):calls.append(url);raise TimeoutError()
    state=live.collect(store,NOW,fail)
    assert state['current'] is None and not state['available']
    assert state['sourceFailures']==[live.SOURCE_NAME]
    assert len(calls)==1 and 'madis-data' in calls[0]
    assert store.read_json('live/current.json')['lastGood'] is None


def test_source_outage_keeps_last_madis_mean_and_its_observation_time():
    store=MemoryStore();doc=saved(reports());store.write_json('live/current.json',doc)
    def fail(url):raise TimeoutError()
    state=live.collect(store,NOW+timedelta(minutes=20),fail)
    assert state['current']==doc['lastGood']
    assert state['sourceFailures']==[live.SOURCE_NAME]
    assert state['checkedAt']==app.iso(NOW+timedelta(minutes=20))
    assert state['current']['observedAt']=='2026-10-21T03:38:20Z'


def test_failed_noaa_qc_in_newer_report_holds_last_madis_average():
    now=NOW.replace(hour=4,minute=5);store=MemoryStore()
    doc=saved(reports(now,minutes=(35,35,35)),now);store.write_json('live/current.json',doc)
    state=live.collect(store,now,lambda url:binary(qc_failure=True))
    assert state['held'] and state['current']==doc['lastGood']
    assert state['candidate']['invalidStations']==[list(app.STATIONS)[1]]


def test_collector_routes_current_to_the_local_madis_product():
    store=MemoryStore()
    with patch('local_current.collect',return_value={'available':True,'held':False,'sourceFailures':[]}) as local,patch('app.download') as other:
        result=collector.collect_current(store,NOW)
    assert result['available']
    local.assert_called_once_with(store,NOW)
    other.assert_not_called()


def test_api_does_not_reuse_the_retired_three_airport_average():
    store=MemoryStore();store.write_json('live/current.json',saved(reports(minutes=(0,0,0))))
    app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as upstream,patch('regional_madis.fetch') as binary_fetch:
        client=app.app.test_client();data=client.get('/api/observations').json
        assert data['current'] is None and 'history' not in data
        assert data['version']=='madis-hopkins-ten-mile-v1'
        html=client.get('/').get_data(as_text=True)
        assert 'tab-current' not in html and 'current-views.js' not in html
        assert 'id="sun-angle"' in html and 'tab-metar-clouds' in html
        assert client.get('/api/models').status_code==404
        upstream.assert_not_called();binary_fetch.assert_not_called()


def test_airport_wind_details_use_each_stations_own_report_without_changing_mean():
    rows=reports(minutes=(0,0,0))
    rows[0].update(wspd=5,wdir=225)
    rows[1].update(wspd=0,wdir=None)
    rows[2].update(wspd=10,wdir='VRB')
    result=live.candidate(rows,NOW)
    assert result['available']
    winds=[s['wind'] for s in result['stations']]
    assert winds[0]['speedMph']==5.8 and winds[0]['direction']==225
    assert winds[1]['speedMph']==0
    assert winds[2]['speedMph']==11.5 and winds[2]['variable']
    assert result['wind']['speedMph']==5.8
    missing=live.candidate(rows[:1],NOW)['stations'][1]['wind']
    assert missing['speedMph'] is None
