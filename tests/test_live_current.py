from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import json

import app
import collector
import live_current as live
from rapid_observations import parse_reports
from test_realtime import MemoryStore

NOW=datetime(2026,10,21,3,45,tzinfo=timezone.utc)


def reports(now=NOW, minutes=(0,5,15)):
    return [dict(icaoId=s,obsTime=(now-timedelta(minutes=m)).timestamp(),temp=t,dewp=d,wspd=5,wdir=350,
                 rawOb=f'{s} {(now-timedelta(minutes=m)):%d%H%M}Z 35005KT {t:02d}/{d:02d} RMK T09990999')
            for s,m,t,d in zip(app.STATIONS,minutes,[10,11,12],[5,6,7])]


def saved(rows, now=NOW):
    return dict(version=live.VERSION,reports=rows,lastGood=live.candidate(rows,now),checkedAt=app.iso(now),sourceFailures=[],allSourcesFailed=False)


def csv_for(rows):
    return ('station,valid,metar\n'+'\n'.join(f'{r["icaoId"]},{datetime.fromtimestamp(r["obsTime"],timezone.utc).isoformat()},{r["rawOb"]}' for r in rows)).encode()


def test_user_example_equal_celsius_means_and_mean_epoch_time():
    c=live.candidate(reports(),NOW)
    assert c['available'] and c['observedAt']=='2026-10-21T03:38:20Z'
    assert c['tempC']==11 and c['tempF']==51.8 and c['dewpointF']==42.8
    assert len(c['stations'])==3
    assert [s['tempC'] for s in c['stations']]==[10,11,12]


def test_body_celsius_used_even_if_t_remark_decoded_or_fahrenheit_disagrees():
    rows=reports(minutes=(0,0,0))
    parsed=parse_reports(csv_for(rows),app.STATIONS,NOW)
    assert [r['temp'] for r in parsed]==[10,11,12]
    assert live.candidate(parsed,NOW)['tempF']==51.8
    rows=[{**r,'temp':99,'tempF':999} for r in rows]
    store=MemoryStore()
    def download(url):return json.dumps(rows).encode() if 'aviationweather' in url else csv_for(reports(minutes=(0,0,0)))
    data=live.collect(store,NOW,download)
    assert data['current']['tempF']==51.8


def test_spread_or_failed_new_report_holds_entire_last_good_and_its_time():
    doc=saved(reports(minutes=(0,5,10)))
    original=deepcopy(doc['lastGood'])
    doc['reports'][0].update(obsTime=(NOW+timedelta(minutes=7)).timestamp(),temp=20)
    doc['checkedAt']=app.iso(NOW+timedelta(minutes=7))
    state=live.present(doc,NOW+timedelta(minutes=7))
    assert state['held'] and state['current']==original
    assert list(app.STATIONS)[-1] in state['candidate']['outOfSyncStations']
    doc=saved(reports(minutes=(0,0,0)))
    doc['reports'].append({**doc['reports'][0],'obsTime':NOW.timestamp()+60,'dewp':40})
    state=live.present(doc,NOW+timedelta(minutes=1))
    assert state['held'] and state['candidate']['invalidStations']==['KFCM']
    assert state['current']['observedAt']==app.iso(NOW)


def test_missing_station_never_becomes_two_station_current_and_age_does_not_reject():
    assert not live.candidate(reports()[:2],NOW)['available']
    state=live.present(saved(reports(minutes=(0,0,0))),NOW+timedelta(minutes=16))
    assert not state['held'] and state['current']['count']==3
    assert state['candidate']['outOfSyncStations']==[]
    assert state['collectorDelayed']
    assert live.present(None,NOW)['current'] is None


def test_roll_latest_one_per_station_cross_midnight_and_wrap_wind():
    now=NOW.replace(hour=0,minute=5)
    rows=reports(now,minutes=(0,5,10))
    c=live.candidate(rows,now)
    assert c['observedAt']=='2026-10-21T00:00:00Z'
    newer={**rows[2],'obsTime':now.timestamp(),'temp':15,'wdir':10}
    c=live.candidate(rows+[newer],now)
    assert c['count']==3 and c['tempC']==12
    assert c['observedAt']=='2026-10-21T00:03:20Z'
    variable=deepcopy(rows);variable[0]['wdir']='VRB'
    assert live.candidate(variable,now)['wind']['direction'] is None


def test_sources_queried_once_together_retention_and_failures_never_fake_freshness():
    store=MemoryStore();calls=[]
    def download(url):
        calls.append(url)
        return json.dumps(reports(minutes=(0,0,0))).encode() if 'aviationweather' in url else csv_for(reports(minutes=(0,0,0)))
    first=live.collect(store,NOW,download)
    assert len(calls)==3 and first['available'] and not first['held']
    from urllib.parse import urlparse, parse_qs
    iem=next(url for url in calls if 'iastate' in url)
    assert parse_qs(urlparse(iem).query)['report_type']==['1,3,4']  # documented HFMETAR, routine, SPECI
    original=first['current']
    def fail(url):raise TimeoutError('unavailable')
    state=live.collect(store,NOW+timedelta(minutes=2),fail)
    assert not state['held'] and state['current']==original and len(state['sourceFailures'])==3
    state=live.collect(store,NOW+timedelta(minutes=4),lambda url:csv_for(reports(NOW+timedelta(minutes=4),minutes=(0,0,0))) if 'iastate' in url else fail(url))
    assert not state['held'] and state['current']['observedAt']==app.iso(NOW+timedelta(minutes=4))


def test_api_and_initial_html_are_saved_only_no_history_and_models_removed():
    store=MemoryStore();store.write_json('live/current.json',saved(reports(minutes=(0,0,0))))
    app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as upstream:
        client=app.app.test_client();data=client.get('/api/observations').json
        assert data['current']['available'] and 'history' not in data
        html=client.get('/').get_data(as_text=True)
        assert '>52°F<' in html
        assert client.get('/api/models').status_code==404
        assert client.post('/collect/current').status_code==404
        upstream.assert_not_called()
    assert collector.app.test_client().post('/collect/models').status_code==404


def test_user_delayed_example_uses_report_spread_inclusive_not_wall_clock_age():
    # 11 p.m. CDT, reports 10:40, 10:35, 10:25 -> mean 10:33:20 p.m.
    now=datetime(2026,10,21,4,0,tzinfo=timezone.utc)
    rows=reports(now,minutes=(20,25,35))
    c=live.candidate(rows,now)
    assert c['available'] and c['timestampSpreadSeconds']==900
    assert c['observedAt']=='2026-10-21T03:33:20Z'
    assert not live.present(saved(rows,now),now)['held']
    # An hour/day passing cannot change report-to-report coherence.
    for hours in [1,3,24]:
        state=live.present(saved(rows,now),now+timedelta(hours=hours))
        assert state['available'] and not state['held']
        assert state['current']['observedAt']==c['observedAt']
    rows[-1]['obsTime']-=1
    assert not live.candidate(rows,now)['available']
    assert live.candidate(rows,now)['timeSpreadExceeded']


def test_existing_v1_data_migrates_and_older_station_reports_never_expire():
    rows=reports(NOW-timedelta(hours=2),minutes=(0,5,15))
    doc=saved(rows);doc['version']='latest-three-airports-celsius-v1';doc['lastGood']=None
    assert live.present(doc,NOW)['current']['count']==3
    store=MemoryStore();store.write_json('live/current.json',doc)
    def fail(url):raise TimeoutError()
    result=live.collect(store,NOW,fail)
    assert result['available'] and not result['held']
    assert result['current']['observedAt']==live.candidate(rows,NOW)['observedAt']
    assert store.read_json('live/current.json')['version']==live.VERSION
    assert len(store.read_json('live/current.json')['reports'])==3


def test_initial_backfill_accepts_older_reports_then_uses_small_query_window():
    from urllib.parse import urlparse,parse_qs
    store=MemoryStore();calls=[]
    old=reports(NOW-timedelta(hours=2),minutes=(0,5,15))
    def download(url):
        calls.append(url)
        return json.dumps(old).encode() if 'aviationweather' in url else csv_for(old)
    first=live.collect(store,NOW,download)
    assert first['available'] and not first['held']
    awc=next(url for url in calls if 'aviationweather' in url)
    assert parse_qs(urlparse(awc).query)['hours']==['24']
    calls.clear()
    second=live.collect(store,NOW+timedelta(minutes=2),download)
    assert second['current']==first['current'] and not second['held']
    awc=next(url for url in calls if 'aviationweather' in url)
    assert parse_qs(urlparse(awc).query)['hours']==['1']


def test_direct_noaa_five_minute_data_beats_older_hourly_metars_and_rounds_celsius():
    from test_madis_observations import fixture
    from urllib.error import HTTPError
    now=NOW.replace(hour=4,minute=5)
    older=reports(now,minutes=(35,35,35))
    calls=[]
    with patch('test_madis_observations.NOW',NOW.replace(hour=3,minute=55)):
        payload=fixture()
    def download(url):
        calls.append(url)
        if 'madis-data' in url:
            if '20261021_0400' in url:raise HTTPError(url,404,'hour not ready',{},None)
            return payload
        return json.dumps(older).encode() if 'aviationweather' in url else csv_for(older)
    data=live.collect(MemoryStore(),now,download)
    assert data['available'] and not data['held'] and data['sourceFailures']==[]
    assert data['current']['observedAt']=='2026-10-21T03:48:20Z'
    assert [s['tempC'] for s in data['current']['stations']]==[24,24,25]
    assert all(s['source']=='NOAA MADIS five-minute ASOS' for s in data['current']['stations'])
    assert all('station=' not in url for url in calls if 'madis-data' in url)
    assert data['current']['tempF']==75.8


def test_failed_noaa_qc_in_newer_rapid_report_holds_instead_of_hiding_it_with_hourly():
    from test_madis_observations import fixture
    now=NOW.replace(hour=4,minute=5)
    older=reports(now,minutes=(35,35,35));store=MemoryStore()
    doc=saved(older,now);store.write_json('live/current.json',doc)
    with patch('test_madis_observations.NOW',NOW.replace(hour=3,minute=55)):
        payload=fixture(qc_failure=True)
    def download(url):
        if 'madis-data' in url:return payload
        return json.dumps(older).encode() if 'aviationweather' in url else csv_for(older)
    data=live.collect(store,now,download)
    assert data['held'] and data['current']==doc['lastGood']
    assert data['candidate']['invalidStations']==[list(app.STATIONS)[1]]


def test_newer_metar_wins_over_older_direct_asos_and_collector_uses_conditional_fetch():
    store=MemoryStore();now=NOW.replace(hour=4,minute=5)
    newer=reports(now,minutes=(12,12,12))
    from test_madis_observations import fixture
    with patch('test_madis_observations.NOW',NOW.replace(hour=3,minute=55)):
        payload=fixture()
    def text_download(url):return json.dumps(newer).encode() if 'aviationweather' in url else csv_for(newer)
    with patch('madis_observations.fetch_file',return_value=payload) as binary,patch('app.download',side_effect=text_download):
        result=collector.collect_current(store,now)
    assert result['available'] and binary.call_count==2
    state=store.read_json('live/current.json')
    assert all(s['source']=='NOAA Aviation Weather Center' for s in state['lastGood']['stations'])
    assert state['lastGood']['observedAt']=='2026-10-21T03:53:00Z'


def test_direct_asos_wins_tied_archive_copy_and_sun_sublabel_is_removed():
    rows=reports(minutes=(0,0,0));store=MemoryStore()
    with patch('live_current.direct_asos',return_value=[{**r,'source':'NOAA MADIS five-minute ASOS'} for r in rows]):
        data=live.collect(store,NOW,lambda url:b'[]' if 'aviationweather' in url else csv_for(rows))
    assert all(s['source']=='NOAA MADIS five-minute ASOS' for s in data['current']['stations'])
    app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW):
        html=app.app.test_client().get('/').get_data(as_text=True)
    assert 'Hopkins · now' not in html
    assert '>52°F<' in html and 'id="sun-angle"' in html
