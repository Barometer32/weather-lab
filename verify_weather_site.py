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
        payload=json.dumps({'latitude':44.925,'longitude':-93.463}).encode() if path=='/api/current' else None
        headers={'User-Agent':'Weather Lab migration check'}
        if payload is not None:headers['Content-Type']='application/json'
        with urlopen(Request(base+path,data=payload,headers=headers),timeout=90) as response:
            return response.read()

    fetch = fetch or download
    html = fetch('/').decode()
    tabs=re.findall(r'<button role="tab" id="tab-([^"]+)"',html)
    current_layout=tabs==['current','radar','clouds','satellite','forecast','air-quality']
    legacy_layout=tabs==['metar','radar','satellite','forecast','air-quality']
    if not (current_layout or legacy_layout):raise ValueError('The saved weather tabs were not verified')
    model=bool(re.search(r'<script\b[^>]*\bsrc="/static/metar-model\.js(?:\?[^"]*)?"',html))
    if not model:raise ValueError('The saved METAR station model is missing')
    if current_layout:
        if 'clouds-views.js?v=' not in html or 'location-choice.js?v=' not in html or 'id="metar-product"' in html:
            raise ValueError('Current and cloud-only layout was not verified')
        point=json.loads(fetch('/api/current'))
        if point.get('windowMinutes')!=30 or point.get('gridSpacingKm')!=5 or not point.get('available'):
            raise ValueError('The prepared 30-minute local analysis is not ready')
    else:
        combined='data-station-model="combined-v1"' in html
        separate=all(f'<option value="{mode}">' in html for mode in ('clouds','wind','dewpoint','temperature'))
        if not (combined or separate):raise ValueError('The saved METAR station model is missing')
    metars = json.loads(fetch('/api/clouds' if current_layout else '/api/station-plots'))
    frames = metars.get('history', [])
    if metars.get('sourcePolicy') != 'airport-routine-only' or metars.get('stationPolicy') != 'all-airports-v1' or len(frames) != 12 or any(not frame.get('stations') for frame in frames):
        raise ValueError('Twelve populated all-airport frames were not verified')
    if any(row.get('reportType') != 'METAR' or not 45 <= int(row['time'][14:16]) <= 59 for frame in frames for row in frame['stations']):
        raise ValueError('An observation outside the routine airport policy reached the map')
    for endpoint in ('radar?site=KMPX', 'satellite/truecolor', 'satellite/dcphase', 'satellite/ntmicro', 'forecast', 'air-quality'):
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
    print('Verified saved weather tabs, current analysis (when enabled), and twelve airport source hours.', flush=True)


if __name__ == '__main__':
    verify(sys.argv[1])
