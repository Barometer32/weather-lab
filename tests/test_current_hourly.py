from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import app
import collector
import current_hourly as current

NOW = datetime(2026,11,10,2,3,tzinfo=timezone.utc)
HOUR = NOW.replace(minute=0)



class Store(dict):
    read_json = dict.get
    write_json = dict.__setitem__


def report(code, hour=HOUR, minute=53, *, remark="T00101005", kind="METAR", receipt=None):
    observed = hour - timedelta(minutes=60-minute)
    raw = f"{kind} {code} {observed:%d%H%M}Z 35010KT 10SM CLR 20/05 A2998 RMK AO2 {remark}"
    return {"icaoId": code, "obsTime": observed.timestamp(), "metarType": kind,
            "receiptTime": app.iso(receipt or observed), "rawOb": raw,
            "temp": 20, "dewp": 5, "wspd": 10, "wdir": 350 if code == "KFCM" else 10}

def trio(hour=HOUR):
    return [report(c,hour=hour) for c in current.STATIONS]


def test_only_official_50_through_59_and_precise_remarks_with_latest_correction():
    rows=trio()+[report('KMSP',minute=49,remark='T01900050'),
                 report('KMSP',minute=0,remark='T01900050'),
                 report('KMSP',minute=55,kind='SPECI',remark='T01900050'),
                 report('KMSP',hour=HOUR+timedelta(hours=1)),
                 report('KSTP',remark='T01900050')]
    rows+=[report('KMSP',receipt=HOUR,remark='T00201005')]
    data=current.present({'reports':rows},NOW)
    assert len(data['history'])==1 and data['current']['complete']
    assert data['current']['tempF']==34 and data['current']['dewpointF']==31
    assert data['current']['tempC']==4/3
    assert data['pendingHour'] is None
    assert all(':53:' in s['observedAt'] for s in data['current']['stations'])
    assert current.present({'reports':[report(c,minute=50) for c in current.STATIONS]},NOW)['current']
    assert current.present({'reports':[report(c,minute=59) for c in current.STATIONS]},NOW)['current']


def test_average_native_values_before_rounding_and_negative_t_signs():
    rows=[report('KMSP',remark='T01130005'),report('KFCM',remark='T01140005'),report('KMIC',remark='T01140005')]
    rows[0]['wspd']=7
    latest=current.present({'reports':rows},NOW)['current']
    assert latest['tempF']==52 and latest['wind']['speedMph']==10
    rows=[report(c,remark='T10011057') for c in current.STATIONS]
    latest=current.present({'reports':rows},NOW)['current']
    assert latest['tempF']==32 and latest['dewpointF']==22
    # Do not round a station's 38.48 F through 38.5 F before whole-degree display.
    rows=[report(c,remark='T00360005') for c in current.STATIONS]
    latest=current.present({'reports':rows},NOW)['current']
    assert latest['tempF']==38 and all(s['tempF']==38 for s in latest['stations'])


def test_missing_precision_or_station_never_creates_partial_average_and_keeps_previous_hour():
    prior=trio(HOUR-timedelta(hours=1))
    for broken in [trio()[:2], [report('KMSP',remark=''),*trio()[1:]], [report('KMSP',remark='T0010'),*trio()[1:]]]:
        data=current.present({'reports':[*prior,*broken]},NOW)
        assert data['pendingHour']==app.iso(HOUR)
        assert data['current']['hour']==app.iso(HOUR-timedelta(hours=1))
        assert data['history'][0]['hour']==data['current']['hour']
        assert data['pending']['tempF'] is None or data['pending']['dewpointF'] is None
        assert len(data['history'])==1
    incomplete=trio();incomplete[0]['wspd']=None
    assert not current.present({'reports':incomplete},NOW)['pending']['complete']


def test_speed_uses_variable_report_but_direction_uses_only_known_bearings():
    rows=trio();rows[0].update(wspd=10,wdir='VRB');rows[1].update(wspd=10,wdir=350);rows[2].update(wspd=10,wdir=10)
    wind=current.present({'reports':rows},NOW)['current']['wind']
    assert wind['speedMph']==12 and wind['direction'] in (0,360)
    assert wind['speedCount']==3


def test_exact_twelve_hours_and_midnight_rollover():
    now=datetime(2026,11,16,0,0,tzinfo=timezone.utc);hour=now
    rows=[r for i in range(14) for r in trio(hour-timedelta(hours=i))]
    data=current.present({'reports':rows},now)
    assert len(data['history'])==12
    assert data['history'][0]['hour']==app.iso(hour)
    assert data['history'][-1]['hour']==app.iso(hour-timedelta(hours=11))


def test_collect_backfills_then_retries_at_two_minutes_and_stops_upstream_when_ready():
    store=Store();prior=[r for i in range(1,13) for r in trio(HOUR-timedelta(hours=i))]
    with patch('app.download',side_effect=[json.dumps([*prior,*trio()[:2]]).encode(),json.dumps(trio()[2:]).encode()]) as download:
        current.collect(store,NOW)
        assert current.present(store[current.KEY],NOW)['pendingHour']
        assert len(current.present(store[current.KEY],NOW)['history'])==12
        current.collect(store,NOW+timedelta(minutes=2))
        assert current.present(store[current.KEY],NOW)['pendingHour'] is None
        assert current.collect(store,NOW+timedelta(minutes=4))['status']=='already prepared'
        assert download.call_count==2
        query=[parse_qs(urlparse(call.args[0]).query) for call in download.call_args_list]
        assert query[0]['hours']==['14'] and query[1]['hours']==['2']
        assert query[0]['date']==[app.iso(HOUR)]


def test_source_failure_does_not_erase_history_and_public_api_never_downloads():
    store=Store({current.KEY:{'reports':trio(HOUR-timedelta(hours=1)),'checkedAt':app.iso(NOW-timedelta(hours=1))}})
    before=dict(store)
    with patch('app.download',side_effect=TimeoutError):
        try:current.collect(store,NOW)
        except TimeoutError:pass
    assert store==before
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as download:
        app._cache.clear();response=app.app.test_client().get('/api/current')
        assert response.status_code==200
        assert response.json['current']['complete'] and response.json['pendingHour']
        download.assert_not_called()
    with patch('collector.get_store',return_value=store),patch('collector.collect_current_hourly',return_value={'status':'already prepared'}) as collect:
        assert collector.app.test_client().post('/collect/current-hourly').status_code==200
        collect.assert_called_once()


def test_incomplete_middle_hour_is_omitted_and_never_replaced_with_partial_values():
    missing_hour=HOUR-timedelta(hours=4)
    reports=[r for i in range(12) for r in trio(HOUR-timedelta(hours=i))
             if not (i==4 and r['icaoId']=='KMIC')]
    data=current.present({'reports':reports},NOW)
    assert len(data['history'])==11
    assert all(h['complete'] and h['count']==3 for h in data['history'])
    assert app.iso(missing_hour) not in [h['hour'] for h in data['history']]
    assert data['current']['hour']==app.iso(HOUR)
    empty=current.present({},NOW)
    assert empty['history']==[] and empty['current'] is None
