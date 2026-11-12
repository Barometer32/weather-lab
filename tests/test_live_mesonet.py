"""Approved station policy, prepared-only public access and private collection."""
from unittest.mock import patch
from datetime import timedelta
import app
import collector
import observation_stations as obs
from test_observation_stations import Store, sample, NOW


def test_mesonet_endpoint_uses_approved_map_without_upstream_requests():
    saved = {'version':obs.VERSION,'coverage':obs.COVERAGE,'checkedAt':obs.iso(NOW),
             'stations':[sample(),sample('HPN27'),sample('HPN29'),sample('HPN42'),
                         sample('HPN60',lat=45.25,lon=-93.75),sample('HPN47',network='CWOP'),
                         sample('HPN31',lat=45.16,lon=-93.22),
                         sample('HPN39',time=obs.iso(NOW-timedelta(minutes=61)))]}
    store = Store({obs.KEY:saved})
    app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as download:
        response = app.app.test_client().get('/api/mesonet')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    result = response.json
    assert {s['station'] for s in result['stations']} == {'HPN20','HPN31'}
    assert all(s['network']=='Hennepin West' for s in result['stations'])
    assert result['updateIntervalSeconds']==300 and result['temperatureUnit']=='F' and result['windUnit']=='mph'
    assert result['stationPolicy']==obs.MAP_STATION_POLICY and not result['stale']
    assert all(s['time']==sample()['time'] for s in result['stations'])
    download.assert_not_called()
    app._cache.clear()


def test_mesonet_empty_storage_never_downloads_on_page_request():
    app._cache.clear()
    with patch('app.get_store',return_value=None),patch('app.download') as download:
        assert app.app.test_client().get('/api/mesonet').status_code==503
        download.assert_not_called()


def test_private_mesonet_collector_preserves_approved_policy():
    store=Store({obs.KEY:{'version':obs.VERSION,'coverage':obs.COVERAGE,'checkedAt':obs.iso(NOW),'stations':[sample(),sample('HPN27')]}})
    with patch('collector.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('observation_stations.collect') as collect:
        response=collector.app.test_client().post('/collect/mesonet')
    assert response.status_code==200 and response.json['result']['stations']==1
    collect.assert_called_once_with(store,NOW)
