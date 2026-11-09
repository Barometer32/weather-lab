"""Verify prepared weather pages and warm their newest assets before cutover."""
from datetime import datetime, timedelta
import json
import re
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def ready_metar_loop(data, hours):
    frames = data.get('history', [])
    if data.get('sourcePolicy') != 'airport-routine-only' or data.get('stationPolicy') not in ('all-airports-v1', 'airport-exclude-kcfe-v1'):
        return False
    if any(row.get('reportType') != 'METAR' or not 45 <= int(row['time'][14:16]) <= 59 for frame in frames for row in frame['stations']):
        raise ValueError('An observation outside the routine airport policy reached the map')
    if hours == 12:
        return len(frames) == 12 and all(frame.get('stations') for frame in frames)
    # Match the four-hour viewer, including its coverage hold and airport rule.
    for end in range(len(frames), hours-1, -1):
        window = frames[end-hours:end]
        if not all(frame.get('stations') for frame in window):
            continue
        times = [datetime.fromisoformat(frame['hour'].replace('Z', '+00:00')) for frame in window]
        if any(b - a != timedelta(hours=1) for a, b in zip(times, times[1:])):
            continue
        stations = [{row['station'] for row in frame['stations']} for frame in window]
        prior = set.intersection(*stations[:-1])
        kept = prior & stations[-1]
        if kept and (len(prior) < 20 or len(kept) / len(prior) >= .90) and not ({'KFCM', 'KMIC', 'KMSP'} & (prior - kept)):
            return True
    return False


def verify(base, fetch=None, *, metar_hours=12):
    base = base.rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Expected an HTTPS website origin')

    def download(path):
        with urlopen(Request(base + path, headers={'User-Agent': 'Weather Lab migration check'}), timeout=90) as response:
            return response.read()

    fetch = fetch or download
    html = fetch('/').decode()
    expected = ['metar', 'radar', 'satellite', 'forecast', 'air-quality']
    if re.findall(r'<button role="tab" id="tab-([^"]+)"', html) not in (expected, [expected[0], 'observations', *expected[1:]]):
        raise ValueError('The saved weather tabs were not verified')
    combined = 'data-station-model="combined-v1"' in html and bool(re.search(r'<script\b[^>]*\bsrc="/static/metar-model\.js(?:\?[^"]*)?"', html))
    separate = all(f'<option value="{mode}">' in html for mode in ('clouds', 'wind', 'dewpoint', 'temperature'))
    if not (combined or separate):
        raise ValueError('The saved METAR station model is missing')
    picker = re.search(r'<select id="metar-product"[^>]*>(.*?)</select>', html)
    if picker and re.findall(r'<option value="([^"]+)"[^>]*>', picker[1]) not in (['plots', 'clouds'], ['plots', 'clouds', 'hrmetar'], ['mesonet', 'plots', 'clouds']):
        raise ValueError('Unexpected observation dropdown options')
    metars = json.loads(fetch('/api/station-plots'))
    if not ready_metar_loop(metars, metar_hours):
        raise ValueError(f'{metar_hours} usable all-airport METAR frames were not verified')
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
    print(f'Verified saved tabs, the METAR station model and {metar_hours} airport hours.', flush=True)


if __name__ == '__main__':
    verify(sys.argv[1])
