from datetime import timedelta
from io import BytesIO
import json
from unittest.mock import patch
import pytest
import app
import selected_forecast as selected
from test_forecast import document, NOW
from nws_forecast import normalize_forecast, point_urls


def payload(city='Shakopee MN'):
    result=document();result['location']={'areaDescription':city}
    return json.dumps(result).encode()


@pytest.fixture(autouse=True)
def clear_points():
    selected._documents.clear()
    yield
    selected._documents.clear()


def test_selected_coordinates_reach_nws_and_do_not_rewrite_the_narrative():
    with patch.object(selected,'urlopen',return_value=BytesIO(payload())) as fetch:
        result=selected.point_forecast(44.782,-93.484,NOW)
    assert result['location']=='Shakopee MN'
    assert (result['latitude'],result['longitude'])==(44.782,-93.484)
    assert fetch.call_args.args[0].full_url==point_urls(44.782,-93.484)[0]
    assert 'lat=44.782&lon=-93.484' in result['sourceUrl']
    assert result['periods'][1]['detailedForecast']==document()['data']['text'][1].strip()
    assert result['updatedAt']=='2026-10-09T21:56:41Z'


def test_cache_separates_points_and_refreshes_after_30_minutes():
    with patch.object(selected.time,'monotonic',return_value=100),patch.object(selected,'urlopen',side_effect=lambda *a,**k:BytesIO(payload())) as fetch:
        selected.point_forecast(44.782,-93.484,NOW)
        selected.point_forecast(44.782,-93.484,NOW+timedelta(minutes=1))
        assert fetch.call_count==1
        selected.point_forecast(44.98,-93.26,NOW)
        assert fetch.call_count==2
        with patch.object(selected.time,'monotonic',return_value=1900):
            selected.point_forecast(44.782,-93.484,NOW+timedelta(minutes=30))
        assert fetch.call_count==3


def test_force_refresh_is_limited_to_one_upstream_request_per_minute():
    with patch.object(selected.time,'monotonic',return_value=100),patch.object(selected,'urlopen',side_effect=lambda *a,**k:BytesIO(payload())) as fetch:
        selected.point_forecast(44.782,-93.484,NOW)
        selected.point_forecast(44.782,-93.484,NOW,force=True)
        assert fetch.call_count==1
        with patch.object(selected.time,'monotonic',return_value=161):
            selected.point_forecast(44.782,-93.484,NOW,force=True)
        assert fetch.call_count==2


def test_failed_point_never_falls_back_to_another_city():
    with patch.object(selected,'urlopen',return_value=BytesIO(payload())):
        selected.point_forecast(44.782,-93.484,NOW)
    with patch.object(selected,'urlopen',side_effect=TimeoutError),pytest.raises(TimeoutError):
        selected.point_forecast(44.98,-93.26,NOW)
    assert len(selected._documents)==1


def test_cache_is_bounded_and_invalid_documents_are_not_cached():
    with patch.object(selected,'urlopen',side_effect=lambda *a,**k:BytesIO(payload())):
        for i in range(selected.MAX_POINTS+1):selected.point_forecast(44.5+i*.001,-93.4,NOW)
    assert len(selected._documents)==selected.MAX_POINTS
    with patch.object(selected,'urlopen',return_value=BytesIO(b'{}')),pytest.raises(KeyError):
        selected.point_forecast(45.,-92.,NOW)
    assert (45.,-92.) not in selected._documents


def test_location_post_has_no_store_and_does_not_use_fixed_snapshot():
    client=app.app.test_client()
    with patch.object(app,'prepared_snapshot') as fixed,patch.object(app,'utcnow',return_value=NOW),patch.object(selected,'urlopen',return_value=BytesIO(payload())):
        response=client.post('/api/forecast',json={'latitude':44.782,'longitude':-93.484})
        assert response.status_code==200 and response.json['latitude']==44.782
        assert response.headers['Cache-Control']=='no-store'
        fixed.assert_not_called()
    for bad in (None,[],{}, {'latitude':True,'longitude':-93.4}):
        assert client.post('/api/forecast',json=bad).status_code==400
    with patch.object(selected,'urlopen',side_effect=TimeoutError):
        response=client.post('/api/forecast',json={'latitude':45,'longitude':-92})
        assert response.status_code==502 and response.headers['Cache-Control']=='no-store'
