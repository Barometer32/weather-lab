import copy
import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
import pytest
import app
import collector
import five_minute_observations as obs

NOW=datetime(2026,11,13,16,12,tzinfo=timezone.utc)

class Store:
    def __init__(self): self.data={}
    def read_json(self,key): return copy.deepcopy(self.data.get(key))
    def write_json(self,key,value): self.data[key]=copy.deepcopy(value)

def row(station='KFCM',minute=10,temp='04/01',wind='27003KT',remarks='T00990088 MADISHF',raw=None):
    return [station[1:],f'2026-11-13 16:{minute:02}',raw or f'{station} 1316{minute:02}Z AUTO {wind} 10SM CLR {temp} A3000 RMK {remarks}']

def payload(*rows):
    out=StringIO();writer=csv.writer(out);writer.writerow(['station','valid','metar']);writer.writerows(rows);return out.getvalue().encode()

def batch(minute=10):
    return [row('KFCM',minute,'04/01','27003G30KT'),row('KMSP',minute,'05/02','VRB06KT'),row('KMIC',minute,'06/00','00009KT')]

def collect(store,rows=None,now=NOW):
    return obs.collect(store,now,lambda _:payload(*(batch() if rows is None else rows)))

def test_raw_whole_celsius_mean_then_fahrenheit_and_scalar_mph_wind():
    store=Store();collect(store);data=obs.present(store.data[obs.KEY],NOW);value=data['current']
    assert value['temperatureC']==5 and value['dewpointC']==1
    assert value['temperatureF']==41 and value['dewpointF']==33.8
    assert value['windSpeedMph']==pytest.approx(6*1852/1609.344)
    assert value['observedAt']=='2026-11-13T16:10:00Z'
    assert {s['station'] for s in value['stations']}==set(obs.STATIONS)
    assert all(s['time']==value['observedAt'] for s in value['stations'])
    assert data['available'] and not data['waiting'] and not data['sourceDelayed']


def test_only_madishf_five_minute_reports_no_routine_speci_or_t_remark_fallback():
    entries=[row(),row('KMSP',53),row('KMIC',remarks='AO2 T01000100'),
             row('KFCM',raw=row()[2].replace('KFCM','SPECI KFCM',1)),row('KSTP'),
             row('KFCM',minute=15),row('KMIC',raw=row('KMIC')[2].replace('131610Z','131605Z'))]
    reports=obs.parse_reports(payload(*entries),NOW)
    assert [r['station'] for r in reports]==['KFCM']
    missing=obs.parse_reports(payload(row(temp='10///'),row('KMIC',temp='')),NOW)
    assert missing[0]['tempC']==10 and missing[0]['dewpointC'] is None
    assert missing[1]['tempC'] is missing[1]['dewpointC'] is None
    negative=obs.parse_reports(payload(row(temp='M02/M05')),NOW)[0]
    assert (negative['tempC'],negative['dewpointC'])==(-2,-5)


def test_request_only_three_airports_and_five_minute_report_type():
    query=parse_qs(urlparse(obs.source_url(NOW)).query)
    assert set(query['station'])=={'FCM','MSP','MIC'}
    assert query['report_type']==['1'] and query['data']==['metar']


def test_two_station_or_mixed_timestamp_average_is_never_published():
    store=Store();collect(store,batch()[:2]);assert not obs.present(store.data[obs.KEY],NOW)['available']
    store=Store();collect(store,[row(),row('KMSP',5),row('KMIC',0)])
    assert not obs.present(store.data[obs.KEY],NOW)['available']


def test_partial_arrival_retains_real_common_time_then_advances_when_all_arrive():
    store=Store();collect(store);later=NOW+timedelta(minutes=5)
    collect(store,[row('KFCM',15)],later)
    waiting=obs.present(store.data[obs.KEY],later)
    assert waiting['current']['observedAt']=='2026-11-13T16:10:00Z' and waiting['waiting']
    collect(store,[row('KMSP',15),row('KMIC',15)],later)
    ready=obs.present(store.data[obs.KEY],later)
    assert ready['current']['observedAt']=='2026-11-13T16:15:00Z' and not ready['waiting']


def test_incomplete_new_batch_holds_previous_but_same_time_correction_invalidates():
    store=Store();collect(store);later=NOW+timedelta(minutes=5)
    collect(store,[row('KFCM',15,temp='10///'),row('KMSP',15),row('KMIC',15)],later)
    data=obs.present(store.data[obs.KEY],later)
    assert data['available'] and data['waiting'] and data['current']['observedAt'].endswith('16:10:00Z')
    store=Store();collect(store)
    collect(store,[row('KFCM',temp='10///')])
    assert not obs.present(store.data[obs.KEY],NOW)['available']


def test_source_failure_retains_timestamp_and_expired_data_does_not_look_current():
    store=Store();collect(store);before=copy.deepcopy(store.data)
    with pytest.raises(OSError):obs.collect(store,NOW,lambda _:(_ for _ in ()).throw(OSError('offline')))
    assert store.data==before
    delayed=obs.present(store.data[obs.KEY],NOW+timedelta(minutes=20))
    assert delayed['stale'] and delayed['sourceDelayed'] and delayed['current']['observedAt'].endswith('16:10:00Z')
    assert not obs.present(store.data[obs.KEY],NOW+timedelta(minutes=59))['available']


def test_wrong_legacy_version_and_out_of_order_reports_do_not_contaminate_average():
    store=Store();store.data[obs.KEY]={'version':'legacy-mixed-mesonet','current':{'temperatureF':99}}
    collect(store,batch()[:2]);assert not obs.present(store.data[obs.KEY],NOW)['available']
    collect(store);collect(store,batch(5));assert obs.present(store.data[obs.KEY],NOW)['current']['observedAt'].endswith('16:10:00Z')


def test_public_endpoint_only_reads_prepared_data_and_private_route_collects():
    store=Store();collect(store);app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as download:
        response=app.app.test_client().get('/api/observations/current')
        assert response.status_code==200 and response.json['available']
        assert response.headers['Cache-Control']=='no-store';download.assert_not_called()
    app._cache.clear()
    with patch('app.get_store',return_value=None),patch('app.download') as download:
        assert app.app.test_client().get('/api/observations/current').status_code==503
        download.assert_not_called()
    with patch('collector.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('five_minute_observations.collect',return_value={'available':True}) as run:
        assert collector.app.test_client().post('/collect/rapid-observations').status_code==200
        run.assert_called_once_with(store,NOW)
    app._cache.clear()
