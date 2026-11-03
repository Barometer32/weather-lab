"""NWS forecasts keyed to the explicitly selected location, cached for 30 minutes."""
from collections import OrderedDict
from datetime import datetime, timezone
import json
from threading import Lock
import time
from urllib.request import Request, urlopen

from current_analysis import coordinates
from nws_forecast import normalize_forecast, point_urls

_documents = OrderedDict()
_lock = Lock()
MAX_POINTS = 64
CACHE_SECONDS = 1800


def point_forecast(latitude, longitude, now=None, force=False):
    lat, lon = coordinates(latitude, longitude)
    lat, lon = round(lat, 4), round(lon, 4)
    key = (lat, lon)
    now = now or datetime.now(timezone.utc)
    with _lock:
        entry = _documents.get(key)
        age = time.monotonic() - entry[0] if entry else CACHE_SECONDS
        # Limit repeated refresh clicks to one upstream lookup per minute.
        usable = entry and age < CACHE_SECONDS and (not force or age < 60)
        if usable:
            _documents.move_to_end(key)
    if not usable:
        url, _ = point_urls(lat, lon)
        req = Request(url, headers={'User-Agent': 'Weather-Lab (https://github.com/Barometer32/weather-lab)'})
        with urlopen(req, timeout=20) as response:
            document = json.loads(response.read(2_000_000))
        # Validate before caching; a failed lookup must not poison the selected point.
        location = document.get('location', {}).get('areaDescription') or 'Selected location'
        normalize_forecast(document, now, latitude=lat, longitude=lon, location=location)
        entry = (time.monotonic(), document, now)
        with _lock:
            _documents[key] = entry
            _documents.move_to_end(key)
            while len(_documents) > MAX_POINTS:
                _documents.popitem(last=False)
    document = entry[1]
    location = document.get('location', {}).get('areaDescription') or 'Selected location'
    result = normalize_forecast(document, now, latitude=lat, longitude=lon, location=location)
    result['fetchedAt'] = entry[2].isoformat().replace('+00:00', 'Z')
    return result
