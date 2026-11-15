from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import app
import collector
import observation_stations as obs

NOW = datetime(2026, 11, 15, 1, 30, tzinfo=timezone.utc)

def test_mesonet_endpoint_uses_only_saved_approved_reports_and_keeps_real_times():
    saved = {"version":obs.VERSION,"coverage":obs.COVERAGE,"checkedAt":obs.iso(NOW),"stations":[
        {"station":"HPN20","name":"Hopkins","network":"Hennepin West","lat":44.95556,"lon":-93.41139,
         "time":obs.iso(NOW-timedelta(minutes=90)),"tempF":40,"dewpointF":25,"wind":{"speedMph":5,"direction":270}},
        {"station":"HPN04","name":"Hanover","network":"Hennepin West","lat":45.1677,"lon":-93.6343,
         "time":obs.iso(NOW-timedelta(minutes=5)),"tempF":40,"dewpointF":25,"wind":{}},
    ]}
    app._cache.clear()
    with patch("app.get_store") as store,patch("app.utcnow",return_value=NOW),patch("app.download") as upstream:
        store.return_value.read_json.return_value=saved
        response=app.app.test_client().get('/api/mesonet')
    assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    assert [s['station'] for s in response.json['stations']]==['HPN20']
    assert response.json['sourceDelayed'] and response.json['sourceAgeMinutes']==90
    assert response.json['newestObservationAt']==saved['stations'][0]['time']
    upstream.assert_not_called()

def test_private_hennepin_route_collects_only_its_own_product():
    with patch('collector.get_store') as store,patch('collector.collect_hennepin_mesonet',return_value={'stations':[]}) as collect:
        response=collector.app.test_client().post('/collect/hennepin-mesonet')
    assert response.status_code==200
    assert collect.call_args.args[0] is store.return_value

def test_page_defaults_to_mesonet_without_an_additional_main_tab_or_device_location():
    html=app.app.test_client().get('/').text
    assert '<option value="mesonet" selected>MESONET</option>' in html
    assert '<option value="plots">PLOTS</option>' in html and '<option value="clouds">CLOUDS</option>' in html
    assert 'id="tab-mesonet"' not in html and 'id="tab-observations"' not in html
    assert app.app.test_client().get('/').headers['Permissions-Policy']=='geolocation=()'
