from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from urllib.error import HTTPError

import app
import collector
import hennepin_current as hc

NOW = datetime(2026, 10, 31, 2, 50, tzinfo=timezone.utc)


def rows(at=None):
    return [{"station": k, "name": name, "network": "Hennepin West", "time": hc.iso(at or NOW-timedelta(minutes=20)),
             "lat": 44.95+i*.001, "lon": -93.4, "tempF": 50+i*.1, "dewpointF": 40+i*.1,
             "wind": {"speedMph": 5, "direction": 350 if i<6 else 10}}
            for i, (k, name) in enumerate(hc.STATIONS.items())]


class Store:
    def __init__(self): self.data = {}
    def read_json(self, key): return deepcopy(self.data.get(key))
    def write_json(self, key, value): self.data[key] = deepcopy(value)


def test_exact_selection_equal_means_circular_wind_and_timestamp():
    data = rows(); data[-1]["time"] = hc.iso(NOW-timedelta(minutes=21))
    state, _ = hc.candidate(data, NOW)
    assert set(r['station'] for r in state['stations']) == set(hc.STATIONS)
    assert len(hc.STATIONS) == 12 and 'HPN21' in hc.STATIONS and 'HPN07' in hc.STATIONS
    assert state['available'] and state['counts'] == dict.fromkeys(hc.FIELDS, 12)
    assert abs(state['tempF']-50.55) < 1e-9 and abs(state['dewpointF']-40.55) < 1e-9
    assert state['wind']['direction'] < .01 or state['wind']['direction'] > 359.99
    assert state['wind']['speedMph'] == 5
    assert hc.stamp(state['observedAt']) == NOW-timedelta(minutes=20, seconds=5)
    assert state['timestampSpreadSeconds'] == 60


def test_unselected_sites_wrong_network_future_and_naive_times_never_enter_average():
    data = rows(); extra = deepcopy(data[0]);extra['station'] = 'KMSP';extra['tempF'] = 130
    data += [extra, {**data[0], 'time': '2026-10-31T02:45:00'}, {**data[1], 'time': hc.iso(NOW+timedelta(minutes=1))}]
    data[2]['network'] = 'CWOP'
    state, _ = hc.candidate(data, NOW)
    assert state['counts']['tempF'] == 11
    assert next(r for r in state['stations'] if r['station']==data[2]['station'])['time'] is None
    assert state['tempF'] < 52


def test_qc_is_per_measurement_missing_wind_keeps_temperature_and_dewpoint():
    data = rows();data[0]['qc'] = {'windSpeed': {'descriptor': 'Q', 'results': 2}}
    data[1]['qc'] = {'temperature': {'descriptor': 'X', 'results': 1}}
    data[2]['dewpointF'] = 60
    state, _ = hc.candidate(data, NOW)
    assert state['counts'] == {'tempF': 11, 'dewpointF': 11, 'wind': 11}
    a = state['stations'][0]
    assert a['includedFields'] == ['tempF', 'dewpointF']
    assert 'wind' in a['reasons']


def test_zero_wind_valid_and_opposing_wind_direction_variable():
    data = rows()
    for r in data: r['wind'] = {'speedMph': 0, 'direction': None}
    state, _ = hc.candidate(data, NOW)
    assert state['available'] and state['wind'] == {'speedMph': 0, 'direction': None}
    for i,r in enumerate(data):r['wind'] = {'speedMph': 5, 'direction': 0 if i<6 else 180}
    state, _ = hc.candidate(data, NOW)
    assert state['wind']['direction'] is None and state['wind']['speedMph'] == 5


def test_delayed_reports_allowed_but_time_spread_and_age_are_bounded():
    data = rows(NOW-timedelta(minutes=30))
    state, _ = hc.candidate(data, NOW); assert state['available']
    for r in data[:4]:r['time'] = hc.iso(NOW-timedelta(minutes=41))
    state, _ = hc.candidate(data, NOW)
    assert not state['available'] and state['counts']['tempF'] == 8
    assert 'Over 10 minutes' in state['stations'][0]['reasons']['tempF']
    state, _ = hc.candidate(rows(NOW-timedelta(minutes=46)), NOW)
    assert not state['available'] and not state['stationCount']


def test_persistent_isolated_temperature_excluded_after_three_new_reports_not_three_reads():
    data = rows();data[0]['tempF'] = 70
    state, watch = hc.candidate(data, NOW)
    for _ in range(6):state, same = hc.candidate(data, NOW, watch);assert same == watch
    assert state['counts']['tempF'] == 12
    for minutes in [5, 10]:
        data = [{**r, 'time': hc.iso(hc.stamp(r['time'])+timedelta(minutes=5))} for r in data]
        state, watch = hc.candidate(data, NOW+timedelta(minutes=minutes), watch)
    assert state['counts']['tempF'] == 11 and state['counts']['dewpointF'] == 12
    assert 'Persistent' in state['stations'][0]['reasons']['tempF']
    data[0]['tempF'] = 50
    state, watch = hc.candidate(data, NOW+timedelta(minutes=10), watch)
    assert state['counts']['tempF'] == 12


def test_widespread_front_change_not_treated_as_one_bad_sensor():
    data = rows();
    for r in data: r['tempF'] += 20
    state, watch = hc.candidate(data, NOW)
    assert state['available'] and not any(v['count'] for v in watch.values())


def test_collect_conditional_files_no_hourly_products_and_holds_last_good():
    store = Store(); calls = []; parsed = []
    def download(url, old=None):
        calls.append((url, old)); return (None if old else b'data'), {'etag': 'one'}
    def parse(payload, now, **kwargs):
        parsed.append(kwargs);return rows()
    result = hc.collect(store, NOW, download, parse)
    assert result['available'] and result['counts']['tempF'] == 12 and len(calls) == 1
    assert parsed[0]['station_ids'] == set(hc.STATIONS) and parsed[0]['include_qc']
    hc.collect(store, NOW+timedelta(minutes=5), download, parse)
    assert len(calls) == 2 and len(parsed) == 1 and calls[-1][1] == {'etag': 'one'}
    good = store.data[hc.KEY]['lastGood']
    def fail(*args): raise OSError('Feed unavailable')
    result = hc.collect(store, NOW+timedelta(minutes=40), fail, parse)
    assert result['available'] and result['held']
    assert store.data[hc.KEY]['lastGood'] == good
    assert set(store.data) == {hc.KEY}


def test_new_hour_missing_file_reads_previous_hour():
    store = Store(); calls = []
    now = NOW.replace(hour=3,minute=0)
    def download(url, old=None):
        calls.append(url)
        if '_0300' in url:raise HTTPError(url,404,'not ready',{},None)
        return b'data', {}
    result = hc.collect(store, now, download, lambda *args, **kwargs: rows(now-timedelta(minutes=20)))
    assert result['available'] and len(calls) == 2 and not result['sourceFailures']


def test_api_only_reads_prepared_state_and_does_not_contact_madis(monkeypatch):
    store = Store();good,watch = hc.candidate(rows(),NOW)
    store.write_json(hc.KEY, {'version': hc.VERSION, 'reports': rows(), 'lastGood': good, 'watch': watch, 'checkedAt': hc.iso(NOW)})
    monkeypatch.setattr(app,'get_store',lambda:store);monkeypatch.setattr(app,'utcnow',lambda:NOW)
    app._cache.clear()
    monkeypatch.setattr(hc,'collect',lambda *a: (_ for _ in ()).throw(AssertionError('No source collection on API reads')))
    response = app.app.test_client().get('/api/hennepin-current')
    assert response.status_code == 200 and response.json['current']['counts']['tempF'] == 12
    assert response.headers['Cache-Control'] == 'no-store'
    store.data.clear();app._cache.clear()
    assert app.app.test_client().get('/api/hennepin-current').json['available'] is False


def test_collector_route_runs_the_selected_collector(monkeypatch):
    store = Store();monkeypatch.setattr(collector,'get_store',lambda:store)
    monkeypatch.setattr(hc,'collect',lambda s,n: {'counts':{'tempF':12}})
    response = collector.app.test_client().post('/collect/hennepin-current')
    assert response.status_code == 200 and response.json['result']['counts']['tempF'] == 12
