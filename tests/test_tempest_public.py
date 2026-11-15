import copy
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
import app,collector
import tempest_public as t

NOW=datetime(2026,11,15,15,0,tzinfo=timezone.utc)
class Store:
    def __init__(self):self.data={}
    def read_json(self,k):return copy.deepcopy(self.data.get(k))
    def write_json(self,k,v):self.data[k]=copy.deepcopy(v)

def panel(index=0,temp='30.4 °F',dew='24.0 °F',wind='3.4 mph',bearing='N',minutes=1):
    stamp=NOW-timedelta(minutes=minutes)
    from zoneinfo import ZoneInfo
    return {'stationId':t.STATIONS[index][0],'fields':{'Air Temperature':temp,'Dew Point':dew,'Wind Speed':wind,'Wind Direction':bearing,
            'Timestamp':stamp.astimezone(ZoneInfo('America/Chicago')).strftime('%m/%d/%Y %I:%M:%S %p'),'Timezone':'America/Chicago'}}

def snapshot(panels):
    return {'version':t.VERSION,'checkedAt':t.iso(NOW),'lastSuccessAt':t.iso(NOW),'stations':[t.parse_panel(p,NOW) for p in panels]}

def test_exact_approved_roster_and_source_times():
    expected={'211793','238063','180161','135859','139463','236779','143206','138562','177349','21964','178958','81475','216957','216676','109584'}
    assert {s[0] for s in t.STATIONS}==expected
    result=t.present(snapshot([panel(i) for i in range(15)]),NOW)
    assert len(result['stations'])==15 and result['summary']['stationCount']==15
    assert all(r['observedAt']==t.iso(NOW-timedelta(minutes=1)) for r in result['stations'])
    assert all('tempestwx.com/' in r['url'] for r in result['stations'])

def test_averages_original_decimal_values_and_rounds_once():
    rows=[panel(0,bearing='350'),panel(1,bearing='10'),panel(2,temp='31.4 °F',wind='4.4 mph',bearing='0')]
    result=t.present(snapshot(rows),NOW)['summary']
    assert result['tempF']==31  # Rounding each station first would give 30.
    assert result['wind']['speedMph']==4 and result['wind']['cardinal']=='N'
    assert result['stationCount']==3

def test_variable_wind_speed_included_bearing_omitted_and_calm_threshold():
    rows=[panel(0,wind='18 mph',bearing='VARIABLE'),panel(1,wind='9 mph',bearing='W'),panel(2,wind='9 mph',bearing='W')]
    wind=t.present(snapshot(rows),NOW)['summary']['wind']
    assert wind['speedMph']==12 and wind['cardinal']=='W'
    for speed in ('0 mph','3 mph','3.49 mph'):
        assert t.present(snapshot([panel(wind=speed)]),NOW)['summary']['wind']['cardinal']=='CALM'
    for r in rows:r['fields']['Wind Direction']='VRB'
    assert t.present(snapshot(rows),NOW)['summary']['wind']['cardinal']=='Variable'

def test_missing_or_stale_reports_are_listed_but_never_averaged():
    rows=[panel(0),panel(1,temp='Unknown'),panel(2,minutes=11)]
    result=t.present(snapshot(rows),NOW)
    assert result['summary']['stationCount']==1 and len(result['stations'])==15
    assert [r['status'] for r in result['stations'][:4]]==['Included','Incomplete','Stale','Unavailable']
    assert t.present(snapshot([panel()]),NOW+timedelta(minutes=10))['summary']['tempF'] is None

def test_missing_wind_does_not_remove_valid_temperature_or_invent_wind():
    result=t.present(snapshot([panel(wind='Unknown')]),NOW)['summary']
    assert result['stationCount']==1 and result['tempF']==30
    assert result['wind']['speedMph'] is None and result['wind']['stationCount']==0

def test_units_station_identity_and_timestamp_validation():
    row=t.parse_panel(panel(temp='0 °C',dew='-5 °C',wind='10 knots',bearing='ENE'),NOW)
    assert row['tempF']==32 and row['dewpointF']==23 and abs(row['wind']['speedMph']-11.50779448)<1e-6
    assert row['wind']['direction']==67.5
    assert t.temperature('32') is None and t.wind_speed('10') is None
    for key,value in [('stationId','999999'),('fields',{'Timestamp':'not a time','Timezone':'America/Chicago'})]:
        p=panel();p[key]=value
        with pytest.raises(ValueError):t.parse_panel(p,NOW)
    p=panel();p['fields']['Timezone']='UTC'
    with pytest.raises(ValueError):t.parse_panel(p,NOW)

def test_failed_poll_keeps_original_report_time_and_marks_age_out():
    store=Store();t.collect(store,NOW,capture=lambda:([panel()],[]))
    original=store.data[t.KEY]['stations'][0]['observedAt']
    def offline():raise OSError('Offline')
    with pytest.raises(ValueError):t.collect(store,NOW+timedelta(minutes=5),capture=offline)
    assert store.data[t.KEY]['stations'][0]['observedAt']==original
    assert t.present(store.data[t.KEY],NOW+timedelta(minutes=5))['summary']['stationCount']==1
    assert t.present(store.data[t.KEY],NOW+timedelta(minutes=11))['summary']['stationCount']==0

def test_later_incomplete_report_does_not_reuse_older_good_temperature():
    store=Store();t.collect(store,NOW,capture=lambda:([panel()],[]))
    t.collect(store,NOW,capture=lambda:([panel(temp='Unknown',minutes=0)],[]))
    assert t.present(store.data[t.KEY],NOW)['summary']['stationCount']==0

def test_prepared_api_never_opens_browser_and_private_job_dispatches():
    store=Store();store.data[t.KEY]=snapshot([panel()]);app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('tempest_public.browser_capture') as browser:
        response=app.app.test_client().get('/api/tempest')
    assert response.status_code==200 and len(response.json['stations'])==15
    assert response.headers['Cache-Control']=='no-store';browser.assert_not_called()
    with patch('collector.get_store',return_value=store),patch('collector.collect_tempest',return_value={'stationsRead':15}) as collect:
        assert collector.app.test_client().post('/collect/tempest').status_code==200
    collect.assert_called_once()
