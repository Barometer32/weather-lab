from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

import verify_weather_release as verify


def test_transient_503_is_retried_without_hiding_a_permanent_404():
    unavailable = HTTPError('https://example.test/', 503, 'Unavailable', {}, None)
    with patch.object(verify, 'urlopen', side_effect=[unavailable, BytesIO(b'healthy')]) as request, patch.object(verify.time, 'sleep'):
        assert verify.read('https://example.test', '/') == 'healthy'
        assert request.call_count == 2
    missing = HTTPError('https://example.test/', 404, 'Missing', {}, None)
    with patch.object(verify, 'urlopen', side_effect=missing) as request:
        with pytest.raises(HTTPError): verify.read('https://example.test', '/')
        assert request.call_count == 1
