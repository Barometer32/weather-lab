from unittest.mock import patch

import app
import collector
import verify_weather_release as verify


def test_plots_default_and_retained_clouds_pass_release_layout_check():
    html = app.app.test_client().get('/').text
    with patch.object(verify, 'read', return_value=html):
        verify.check_layout('local')
    assert '<option value="rtmetar">RTMETAR</option>' in html
    assert 'id="metar-history" hidden' not in html
    assert 'id="metar-notice"' not in html


def test_retired_routes_do_not_read_storage_or_download_anything():
    with patch('app.get_store') as store, patch('app.download') as source:
        client = app.app.test_client()
        for path in ['/api/observations', '/api/observations/hourly']:
            assert client.get(path).status_code == 404
        store.assert_not_called()
        source.assert_not_called()
    with patch('collector.get_store') as store:
        client = collector.app.test_client()
        for path in ['/collect/hourly-observations']:
            assert client.post(path).status_code == 404
        store.assert_not_called()
