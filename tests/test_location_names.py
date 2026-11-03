from io import BytesIO
import json
from unittest.mock import patch

import pytest
import location_names as names


GEOGRAPHIES = {'States': [{'STUSAB': 'MN'}],
               'Incorporated Places': [{'BASENAME': 'Shakopee', 'NAME': 'Shakopee city'}],
               'Counties': [{'NAME': 'Scott County'}]}


def test_actual_city_has_priority_over_county_and_township():
    assert names.place_label(GEOGRAPHIES)['label'] == 'Shakopee, MN'
    rural = {'States': [{'STUSAB': 'WI'}], 'County Subdivisions': [{'BASENAME': 'Dane'}]}
    assert names.place_label(rural)['kind'] == 'County Subdivisions'
    with pytest.raises(LookupError):
        names.place_label({})


def test_lookup_is_cached_and_does_not_request_device_location():
    names._lookup.cache_clear()
    payload = json.dumps({'result': {'geographies': GEOGRAPHIES}}).encode()
    with patch.object(names, 'urlopen', return_value=BytesIO(payload)) as get:
        assert names.location_name(44.782, -93.484)['label'] == 'Shakopee, MN'
        assert names.location_name(44.782, -93.484)['label'] == 'Shakopee, MN'
        assert get.call_count == 1
        assert get.call_args.kwargs['timeout'] == 8
    names._lookup.cache_clear()


def test_endpoint_uses_post_and_retains_no_store_on_success_and_failures():
    import app
    client = app.app.test_client()
    body = {'latitude': 44.782, 'longitude': -93.484}
    with patch.object(names, 'location_name', return_value={'label': 'Shakopee, MN'}) as lookup:
        response = client.post('/api/location-name', json=body)
        assert response.status_code == 200 and response.json['label'] == 'Shakopee, MN'
        assert response.headers['Cache-Control'] == 'no-store'
        lookup.assert_called_once_with(44.782, -93.484)
        assert client.get('/api/location-name').status_code == 405
        for bad in ([], 'wrong'):
            assert client.post('/api/location-name', json=bad).status_code == 400
    with patch.object(names, 'location_name', side_effect=TimeoutError):
        response = client.post('/api/location-name', json=body)
        assert response.status_code == 502 and response.headers['Cache-Control'] == 'no-store'
    for bad in ({'latitude': True, 'longitude': -93}, {'latitude': 40, 'longitude': -93}, {}):
        assert client.post('/api/location-name', json=bad).status_code == 400
