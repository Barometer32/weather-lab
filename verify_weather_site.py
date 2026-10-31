"""Verify prepared weather pages and warm their newest assets before cutover."""
import json
import re
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def verify(base, fetch=None):
    base = base.rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Expected an HTTPS website origin')

    def download(path):
        with urlopen(Request(base + path, headers={'User-Agent': 'Weather Lab migration check'}), timeout=90) as response:
            return response.read()

    fetch = fetch or download
    html = fetch('/').decode()
    if re.findall(r'<button role="tab" id="tab-([^"]+)"', html) != ['metar', 'radar', 'satellite', 'forecast', 'air-quality']:
        raise ValueError('The five saved tabs were not verified')
    combined = 'data-station-model="combined-v1"' in html and 'metar-model.js?v=metar-combined-' in html
    separate = all(f'<option value="{mode}">' in html for mode in ('clouds', 'wind', 'dewpoint', 'temperature'))
    if not (combined or separate):
        raise ValueError('The saved METAR station model is missing')
    metars = json.loads(fetch('/api/station-plots'))
    frames = metars.get('history', [])
    if metars.get('sourcePolicy') != 'airport-routine-only' or metars.get('stationPolicy') != 'all-airports-v1' or len(frames) != 12 or any(not frame.get('stations') for frame in frames):
        raise ValueError('Twelve populated all-airport frames were not verified')
    if any(row.get('reportType') != 'METAR' or not 45 <= int(row['time'][14:16]) <= 59 for frame in frames for row in frame['stations']):
        raise ValueError('An observation outside the routine airport policy reached the map')
    if '<option value="madis">' in html:
        from datetime import timedelta
        from madis_map import VERSION, POLICY, allowed, stamp
        madis = json.loads(fetch('/api/madis-map'))
        if (madis.get('version') != VERSION or madis.get('stationPolicy') != POLICY
                or madis.get('checkMinutes') != [0, 15, 30, 45] or madis.get('windowMinutes') != 25
                or not isinstance(madis.get('stations'), list) or 'history' in madis):
            raise ValueError('The separate current mesonet snapshot was not verified')
        end = stamp(madis['checkedAt'])
        if any(not allowed(row) or not end-timedelta(minutes=25) <= stamp(row['time']) <= end for row in madis['stations']):
            raise ValueError('An excluded station or out-of-window report reached the mesonet map')
        print('MADIS: ready (current 25-minute snapshot; quarter-hour checks)', flush=True)
    for endpoint in ('radar?site=KMPX', 'satellite/13', 'satellite/truecolor', 'satellite/dcphase', 'satellite/ntmicro', 'forecast', 'air-quality'):
        data = json.loads(fetch('/api/' + endpoint))
        if endpoint == 'forecast':
            if not data.get('periods'):
                raise ValueError('The prepared forecast is empty')
        else:
            if not data.get('frames'):
                raise ValueError('No prepared frames for ' + endpoint)
            asset = data['frames'][-1].get('url', '')
            if not asset.startswith('/api/prepared/') or '..' in asset.split('/'):
                raise ValueError('Missing or invalid prepared asset for ' + endpoint)
            if not fetch(asset):
                raise ValueError('Empty prepared asset for ' + endpoint)
        print(endpoint + ': ready', flush=True)
    print('Verified five tabs, the saved METAR station model and twelve airport hours.', flush=True)


if __name__ == '__main__':
    verify(sys.argv[1])
