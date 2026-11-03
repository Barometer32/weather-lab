import json
from pathlib import Path
import pytest
from verify_weather_site import verify


def fixture():
    html = (Path(__file__).resolve().parents[1] / 'static/index.html').read_bytes()
    row = {'station': 'KMSP', 'reportType': 'METAR', 'time': '2026-10-27T01:53:00Z'}
    data = {'/': html, '/api/clouds': json.dumps({'sourcePolicy': 'airport-routine-only', 'stationPolicy': 'all-airports-v1', 'history': [{'stations': [row]}] * 12}).encode()}
    data['/api/local-air-quality']=b'{"aqi":{"value":25}}'
    data['/api/current']=json.dumps({'windowMinutes':30,'gridSpacingKm':5,'available':True}).encode()
    for endpoint in ('radar?site=KMPX', 'satellite/truecolor', 'satellite/dcphase', 'satellite/ntmicro'):
        asset = '/api/prepared/' + endpoint.replace('?', '-').replace('/', '-')
        data['/api/' + endpoint] = json.dumps({'frames': [{'url': asset}]}).encode()
        data[asset] = b'image or radar bytes'
    data['/api/forecast'] = b'{"periods":[{"name":"Tonight"}]}'
    return data


def test_checks_every_page_and_downloads_each_newest_asset():
    data = fixture(); calls = []
    def fetch(path):
        calls.append(path)
        return data[path]
    verify('https://weather.example.run.app', fetch)
    assert set(calls) == set(data)


@pytest.mark.parametrize('version', ['metar-combined-v14', 'metar-barb-staff-plus5-v1', 'future-cache-version'])
def test_station_model_cache_version_does_not_change_readiness(version):
    data=fixture()
    html=data['/'].decode()
    import re
    html=re.sub(r'metar-model\.js\?v=[^"]+', 'metar-model.js?v='+version, html)
    data['/']=html.encode()
    verify('https://weather.example.run.app', data.__getitem__)


def test_missing_station_model_script_prevents_cutover():
    data=fixture()
    data['/']=data['/'].replace(b'/static/metar-model.js', b'/static/missing-model.js')
    with pytest.raises(ValueError, match='station model is missing'):
        verify('https://weather.example.run.app', data.__getitem__)


def test_legacy_five_tab_layout_remains_accepted():
    data=fixture()
    html=data['/'].decode()
    import re
    html=re.sub(r'<nav.*?</nav>', '<nav>'+''.join(f'<button role="tab" id="tab-{name}"></button>' for name in ['metar','radar','satellite','forecast','air-quality'])+'</nav>',html,flags=re.S)
    html=html.replace('<div id="clouds-map"','<div data-station-model="combined-v1" id="clouds-map"')
    data['/']=html.encode();data['/api/station-plots']=data['/api/clouds']
    data['/api/air-quality']=b'{"frames":[{"url":"/api/prepared/air"}]}'
    data['/api/prepared/air']=b'air map'
    verify('https://weather.example.run.app',data.__getitem__)


@pytest.mark.parametrize('case', ['empty-current', 'empty-metars', 'speci', 'outside-window', 'empty-radar', 'empty-forecast', 'missing-asset', 'missing-tab'])
def test_invalid_weather_page_or_unavailable_asset_prevents_cutover(case):
    data = fixture()
    metars = json.loads(data['/api/clouds'])
    if case == 'empty-current': data['/api/current']=b'{"available":false}'
    if case == 'empty-metars': metars['history'][0]['stations'] = []
    if case == 'speci': metars['history'][0]['stations'][0]['reportType'] = 'SPECI'
    if case == 'outside-window': metars['history'][0]['stations'][0]['time'] = '2026-10-27T01:40:00Z'
    data['/api/clouds'] = json.dumps(metars).encode()
    if case == 'empty-radar': data['/api/radar?site=KMPX'] = b'{"frames":[]}'
    if case == 'empty-forecast': data['/api/forecast'] = b'{"periods":[]}'
    if case == 'missing-asset': data.pop('/api/prepared/satellite-truecolor')
    if case == 'missing-tab': data['/'] = data['/'].replace(b'id="tab-current"', b'id="tab-old"')
    with pytest.raises((ValueError, KeyError)):
        verify('https://weather.example.run.app', data.__getitem__)
