from pathlib import Path
import re


def test_location_is_same_origin_only_and_retired_test_routes_stay_removed():
    import app
    client=app.app.test_client()
    for path in ['/', '/static/app.js', '/healthz', '/not-a-page']:
        assert client.get(path).headers['Permissions-Policy']=='geolocation=(self)'
    assert client.get('/api/test/location?q=Shakopee').status_code==404
    assert client.get('/static/radar-location.js').status_code==404


def test_all_device_location_reads_live_in_the_click_only_selection_module():
    root=Path(__file__).parents[1]/'static'
    calls=[]
    for path in root.glob('*.js'):
        source=path.read_text()
        assert not re.search(r'watchPosition\s*\(|\.locate\s*\(',source),path.name
        calls.extend([path.name]*len(re.findall(r'getCurrentPosition\s*\(',source)))
    assert calls==['location-choice.js']
