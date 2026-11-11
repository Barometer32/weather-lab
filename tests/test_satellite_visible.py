from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest

import app
from extend_satellite_lifecycle import extend
from satellite import BASE, DEFAULT_PRODUCT, PRODUCTS, page_url, parse_loop
from test_realtime import MemoryStore

NOW = datetime(2026, 11, 11, 19, 45, tzinfo=timezone.utc)


def test_visible_source_uses_band_02_and_keeps_other_band_images_out():
    prefix = BASE + '/02/S_Minnesota.02.'
    images = [prefix + (NOW-timedelta(minutes=i*5+4)).strftime('%Y%m%d.%H%M%S') + '.jpg' for i in range(48)]
    html = ' '.join(images) + ' ' + BASE + '/truecolor/S_Minnesota.truecolor.20261111.194100.jpg'
    data = parse_loop(html, '02', NOW)
    assert len(data['frames']) == 24
    assert data['product'] == data['defaultProduct'] == DEFAULT_PRODUCT == '02'
    assert [p['id'] for p in data['products']] == list(PRODUCTS)
    assert all('/02/S_Minnesota.02.' in f['url'] for f in data['frames'])
    assert 'local-S_Minnesota-02-' in page_url('02')
    assert 'Requires sunlight' in data['description']


def test_default_visible_api_reads_prepared_data_without_upstream_calls():
    store = MemoryStore()
    saved = parse_loop(BASE+'/02/S_Minnesota.02.20261111.194100.jpg', '02', NOW)
    saved.update(checkedAt=NOW.isoformat())
    store.write_json('live/satellite-02.json', saved)
    app._cache.clear()
    with patch('app.get_store', return_value=store), patch('app.utcnow', return_value=NOW), patch('app.download') as upstream:
        response = app.app.test_client().get('/api/satellite/02')
    assert response.status_code == 200 and response.json['product'] == '02'
    upstream.assert_not_called()


def test_visible_lifecycle_extension_preserves_custom_rules_and_is_idempotent():
    metadata = {'name':'weather-data', 'lifecycle': {'rule':[
        {'action':{'type':'SetStorageClass','storageClass':'COLDLINE'}, 'condition':{'age':365,'matchesPrefix':['custom/']}},
        {'action':{'type':'Delete'},'condition':{'age':1,'matchesPrefix':['radar/','satellite/truecolor/']}}
    ]}}
    original = deepcopy(metadata)
    result = extend(metadata, 'weather-data')
    assert metadata == original
    assert result['rule'][:-1] == metadata['lifecycle']['rule']
    assert result['rule'][-1]['condition'] == {'age':1,'matchesPrefix':['satellite/02/']}
    assert extend({'name':'weather-data','lifecycle':result}, 'weather-data') == result
    assert len(extend({'name':'weather-data'}, 'weather-data')['rule']) == 1


def test_lifecycle_extension_rejects_wrong_bucket_and_unrecognized_policy():
    with pytest.raises(ValueError, match='Unexpected data bucket'):
        extend({'name':'unrelated-data'}, 'weather-data')
    with pytest.raises(ValueError, match='Unexpected bucket lifecycle'):
        extend({'name':'weather-data','lifecycle':{'rule':'unrecognized'}}, 'weather-data')
