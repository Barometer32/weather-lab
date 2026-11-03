"""Name the municipality containing a selected point, without a street address."""
from functools import lru_cache
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from current_analysis import coordinates, state_for


def place_label(geographies):
    states = geographies.get('States') or []
    state = states[0].get('STUSAB') if states else None
    if not state:
        raise LookupError('No state name returned.')
    # Prefer the actual containing municipality over a nearby city's centre.
    for layer in ('Incorporated Places', 'Census Designated Places', 'County Subdivisions', 'Counties'):
        for place in geographies.get(layer) or []:
            name = place.get('BASENAME') if layer != 'Counties' else place.get('NAME')
            if not name:
                name = place.get('NAME')
            if isinstance(name, str) and name.strip():
                return {'label': f'{name.strip()}, {state}', 'kind': layer,
                        'source': 'US Census Bureau'}
    raise LookupError('No place name returned.')


@lru_cache(maxsize=256)
def _lookup(latitude, longitude):
    params = dict(x=longitude, y=latitude, benchmark='Public_AR_Current',
                  vintage='Current_Current', format='json',
                  layers='States,Incorporated Places,Census Designated Places,County Subdivisions,Counties')
    url = 'https://geocoding.geo.census.gov/geocoder/geographies/coordinates?' + urlencode(params)
    req = Request(url, headers={'User-Agent': 'Weather-Lab (https://github.com/Barometer32/weather-lab)'})
    with urlopen(req, timeout=8) as response:
        data = json.loads(response.read(500_000))
    return place_label(data.get('result', {}).get('geographies', {}))


def location_name(latitude, longitude):
    latitude, longitude = coordinates(latitude, longitude)
    if not state_for(latitude, longitude):
        raise ValueError('Select a location in Minnesota or Wisconsin.')
    return _lookup(latitude, longitude)
