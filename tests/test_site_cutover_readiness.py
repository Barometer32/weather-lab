import json
from pathlib import Path
import pytest
from verify_weather_site import verify


def fixture():
    html = (Path(__file__).resolve().parents[1] / 'static/index.html').read_bytes()
    row = {'station': 'KMSP', 'reportType': 'METAR', 'time': '2026-10-27T01:53:00Z'}
    data = {'/': html, '/api/station-plots': json.dumps({'sourcePolicy': 'airport-routine-only', 'stationPolicy': 'all-airports-v1', 'history': [{'stations': [row]}] * 12}).encode()}
    from hennepin_current import VERSION, STATIONS
    data['/api/hennepin-current'] = json.dumps({'version': VERSION, 'selectedStations': STATIONS, 'collectionMinutes': 5,
        'available': True, 'held': False, 'current': {'observedAt': '2026-10-31T02:40:00Z', 'counts': dict.fromkeys(('tempF','dewpointF','wind'),12)}}).encode()
    for endpoint in ('radar?site=KMPX', 'satellite/13', 'satellite/truecolor', 'satellite/dcphase', 'satellite/ntmicro', 'air-quality'):
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


def test_pinned_earlier_four_view_restore_is_still_verified():
    data = fixture()
    html = data['/'].decode().replace('data-station-model="combined-v1"', '').replace('metar-combined-v1', 'metar-products-v1')
    html += '<select>' + ''.join(f'<option value="{mode}">{mode}</option>' for mode in ('clouds', 'wind', 'dewpoint', 'temperature')) + '</select>'
    data['/'] = html.encode()
    verify('https://weather.example.run.app', data.__getitem__)


@pytest.mark.parametrize('case', ['empty-metars', 'speci', 'outside-window', 'empty-radar', 'empty-forecast', 'missing-asset', 'missing-tab'])
def test_invalid_weather_page_or_unavailable_asset_prevents_cutover(case):
    data = fixture()
    metars = json.loads(data['/api/station-plots'])
    if case == 'empty-metars': metars['history'][0]['stations'] = []
    if case == 'speci': metars['history'][0]['stations'][0]['reportType'] = 'SPECI'
    if case == 'outside-window': metars['history'][0]['stations'][0]['time'] = '2026-10-27T01:40:00Z'
    data['/api/station-plots'] = json.dumps(metars).encode()
    if case == 'empty-radar': data['/api/radar?site=KMPX'] = b'{"frames":[]}'
    if case == 'empty-forecast': data['/api/forecast'] = b'{"periods":[]}'
    if case == 'missing-asset': data.pop('/api/prepared/satellite-truecolor')
    if case == 'missing-tab': data['/'] = data['/'].replace(b'id="tab-metar"', b'id="tab-old"')
    with pytest.raises((ValueError, KeyError)):
        verify('https://weather.example.run.app', data.__getitem__)


@pytest.mark.parametrize('case',['held','missing-station','insufficient-fields','wrong-cadence'])
def test_incomplete_selected_average_prevents_observations_cutover(case):
    data=fixture();current=json.loads(data['/api/hennepin-current'])
    if case=='held':current['held']=True
    if case=='missing-station':current['selectedStations'].pop('HPN20')
    if case=='insufficient-fields':current['current']['counts']['wind']=8
    if case=='wrong-cadence':current['collectionMinutes']=15
    data['/api/hennepin-current']=json.dumps(current).encode()
    with pytest.raises(ValueError,match='twelve-station observations average'):
        verify('https://weather.example.run.app',data.__getitem__)
