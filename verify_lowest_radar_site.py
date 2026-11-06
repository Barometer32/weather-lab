"""Verify the original five-tab viewer, four METAR frames and lowest radar only."""
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from verify_weather_site import verify


def verify_lowest(base, fetch=None, *, metar_hours=12):
    def download(path):
        for attempt in range(8):
            try:
                with urlopen(Request(base.rstrip('/')+path, headers={'User-Agent':'Weather Lab lowest-radar restore'}), timeout=90) as response:
                    return response.read()
            except HTTPError as error:
                if error.code not in (429,500,502,503,504) or attempt==7:
                    raise
            except (URLError,TimeoutError):
                if attempt==7:
                    raise
            time.sleep(min(5*(attempt+1),30))

    fetch=fetch or download
    verify(base,fetch,metar_hours=metar_hours)
    html=fetch('/').decode()
    if 'id="radar-product"' in html or 'id="tab-current"' in html:
        raise ValueError('Experimental radar selector or CURRENT tab is still present')
    data=json.loads(fetch('/api/radar?site=KMPX'))
    if data.get('products') or not 0 < data.get('elevationDegrees',99) <= .6:
        raise ValueError('Expected only lowest base reflectivity')
    if any(not 0 < frame.get('elevationDegrees',99) <= .6 for frame in data['frames']):
        raise ValueError('A higher-elevation frame reached the lowest-only loop')
    # Verify the served viewer rather than relying on a historical cache label.
    from re import search
    match=search(r'src="(/static/metar-views\.js(?:\?[^\"]*)?)"',html)
    if not match or b'const historyHours=4;' not in fetch(match[1]):
        raise ValueError('The current-plus-three-hour METAR viewer is missing')
    print('Verified: original five tabs, four displayed METAR frames, lowest base radar only.',flush=True)


if __name__=='__main__':
    verify_lowest(sys.argv[1], metar_hours=int(sys.argv[2]) if len(sys.argv) > 2 else 12)
