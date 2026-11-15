import copy
import csv
from datetime import datetime,timedelta,timezone
from io import StringIO
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse
from urllib.error import HTTPError

import app
import collector
import airport_feed as feed

NOW=datetime(2026,11,15,2,30,tzinfo=timezone.utc)

class Store:
    def __init__(self):self.data={}
    def read_json(self,k):return copy.deepcopy(self.data.get(k))
    def write_json(self,k,v):self.data[k]=copy.deepcopy(v)

def raw_collect(store,now,download):
    def fail(_):raise OSError('NOAA unavailable in raw fallback fixture')
    return feed.collect(store,now,download=fail,raw_download=download)

def csv_data(*rows):
    s=StringIO();w=csv.writer(s);w.writerow(['station','valid','metar']);w.writerows(rows);return s.getvalue().encode()

def report(station='KMSP',minute=25,group='M02/M05',remarks='T00990088 MADISHF',prefix=''):
    return [station[1:],f'2026-11-15 02:{minute:02}',f'{prefix}{station} 1502{minute:02}Z AUTO 31508KT 10SM CLR {group} A3030 RMK {remarks}']

def test_only_raw_five_minute_reports_and_main_celsius_are_eligible():
    entries=[report(),report('KFCM',group='04/01'),report('KMIC',group='03/00'),report('KSTP'),
             report('KMSN',prefix='SPECI '),report('KDSM',remarks='AO2 T01000050'),report('KFAR',minute=23),
             report('KABR',group='10///'),report('KGRB',group='',remarks='T01000050 MADISHF'),report('KORD')]
    all_rows=feed.parse_reports(csv_data(*entries),NOW)
    rows=feed.selected(all_rows,NOW)
    assert {r['station'] for r in rows}=={'KMSP','KFCM','KMIC'}
    msp=next(r for r in rows if r['station']=='KMSP')
    assert (msp['tempC'],msp['dewpointC'])==(-2,-5)
    assert msp['temperatureBasis']=='main-XX/XX' and msp['wind']['direction']==315
    assert msp['wind']['speedMph']>8  # Knots converted to mph.

def test_only_three_airports_supported_and_future_or_official_reports_rejected():
    rows=feed.selected(feed.parse_reports(csv_data(*(report(s) for s in ['KFAR','KABR','KDSM','KMSP','KMSN'])),NOW),NOW)
    assert {r['station'] for r in rows}=={'KMSP'}
    assert not feed.parse_reports(csv_data(report(minute=35)),NOW)
    assert not feed.parse_reports(csv_data(report(minute=25,remarks='AO2 T00200000')),NOW)

def test_later_missing_value_omits_station_instead_of_backfilling_old_number():
    store=Store()
    raw_collect(store,NOW,lambda _:csv_data(report()))
    raw_collect(store,NOW+timedelta(minutes=5),lambda _:csv_data(report(minute=30,group='10///')))
    assert not feed.selected(store.data[feed.KEY]['stations'],NOW+timedelta(minutes=5))

def test_source_failure_retains_original_time_and_source_age_then_expires():
    store=Store();raw_collect(store,NOW,lambda _:csv_data(report(minute=0)))
    def fail(_):raise OSError('offline')
    raw_collect(store,NOW+timedelta(minutes=5),fail)
    rows=feed.selected(store.data[feed.KEY]['stations'],NOW+timedelta(minutes=5))
    assert rows[0]['time']=='2026-11-15T02:00:00Z'
    assert not feed.selected(store.data[feed.KEY]['stations'],NOW+timedelta(hours=1))

def test_sources_select_only_report_type_one_and_exact_requested_state_stations():
    for label,url,station in feed.source_urls(NOW):
        q=parse_qs(urlparse(url).query)
        if station is None:
            assert q['report_type']==['1'] and q['data']==['metar']
            assert 1<=len(q['station'])<=25
            state=q['network'][0].split('_')[0]
            assert all(feed.inventory()['K'+s]['state']==state for s in q['station'])
            assert 'STP' not in q['station']

def test_provider_cooldown_is_respected_across_poll_runs_without_retries():
    store=Store();raw_collect(store,NOW,lambda _:csv_data(report()))
    calls=[]
    def limited(url):
        calls.append(url)
        raise HTTPError(url,429,'Slow down',{'Retry-After':'900'},None)
    raw_collect(store,NOW,limited)
    count=len(calls)
    result=raw_collect(store,NOW+timedelta(minutes=5),limited)
    assert len(calls)==count and result['status']=='raw source rate limited'
    assert store.data[feed.KEY]['retryAfter']==NOW.timestamp()+900

def test_prepared_api_and_private_collector_never_fetch_on_page_view():
    store=Store();raw_collect(store,NOW,lambda _:csv_data(report()))
    app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as source:
        r=app.app.test_client().get('/api/airport-observations')
    assert r.status_code==200 and r.json['stationIds']==['KMSP','KFCM','KMIC']
    assert r.headers['Cache-Control']=='no-store';source.assert_not_called()
    with patch('collector.get_store',return_value=store),patch('collector.collect_airport_observations',return_value={'stations':1}) as collect:
        assert collector.app.test_client().post('/collect/airport-observations').status_code==200
    collect.assert_called_once()

def test_direct_feed_uses_hf_type_five_minute_times_celsius_and_mph():
    def decoded(station='KMSP',**extra):
        return dict({'icaoId':station,'obsTime':(NOW-timedelta(minutes=5)).timestamp(),'metarType':'HFMETAR',
                     'temp':3.0000061,'dewp':-5.0000061,'wspd':10,'wdir':270},**extra)
    with patch('madis_observations.parse_file',return_value=[decoded(),decoded('KSTP'),decoded('KORD'),decoded('KFCM',metarType='METAR'),decoded('KMIC',obsTime=(NOW-timedelta(minutes=3)).timestamp())]) as parse:
        rows=feed.from_madis(b'netcdf',NOW)
    assert [r['station'] for r in rows]==['KMSP']
    assert (rows[0]['tempC'],rows[0]['dewpointC'])==(3,-5)
    assert rows[0]['wind']['speedMph']>10
    assert rows[0]['temperatureBasis']=='decoded-HF-ASOS-Celsius'
    assert parse.call_args.kwargs['high_frequency_only'] is True

def test_direct_primary_skips_raw_service_and_is_not_blocked_by_raw_cooldown():
    store=Store();raw_collect(store,NOW,lambda _:csv_data(report()))
    store.data[feed.KEY]['retryAfter']=NOW.timestamp()+900
    row=copy.deepcopy(store.data[feed.KEY]['stations'][0]);row.update(time=feed.iso(NOW),temperatureBasis='decoded-HF-ASOS-Celsius')
    with patch('airport_feed.from_madis',return_value=[row]),patch('app.download') as raw:
        result=feed.collect(store,NOW,download=lambda _:b'netcdf')
    raw.assert_not_called()
    assert result['feed']=='NOAA direct HF-ASOS'
    assert store.data[feed.KEY]['stations'][0]['time']==feed.iso(NOW)
