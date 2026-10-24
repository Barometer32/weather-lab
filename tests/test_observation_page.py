import re
from unittest.mock import patch
import app


def test_observation_list_replaces_metar_and_keeps_cloud_history_and_other_tabs():
    with patch('app.get_store') as store,patch('app.download') as source:
        response=app.app.test_client().get('/')
    source.assert_not_called();store.assert_not_called()
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['observations','radar','clouds','satellite','forecast','air-quality']
    observations=html.split('<section id="observations"')[1].split('</section>')[0]
    satellite=html.split('<section id="satellite"')[1].split('</section>')[0]
    assert 'id="sun-angle"' in observations and 'sun-angle' not in satellite
    assert html.count('id="sun-angle"')==1
    assert 'id="observations-rows"' in observations and 'HENNEPIN WEST' in observations
    assert 'timeline' not in observations and 'tab-metar-clouds' not in html
    assert '/static/cloud-views.js' not in html and 'current-views.js' not in html
    assert 'observation-views.js' in html
    assert 'model-views.js' not in html
    assert 'metar-model.js' in html and 'map-fullscreen.js' in html
    clouds=html.split('<section id="clouds"')[1].split('</section>')[0]
    assert 'id="clouds-timeline"' in clouds and 'data-ceiling-unit="thousands-ft"' in clouds
    assert 'cloud-height-views.js' in html and 'id="clouds"' in html
    assert '>AIR Q</button>' in html and 'id="airq-timeline"' in html
    assert response.headers['Cache-Control']=='no-store'


def test_page_survives_storage_outage_without_source_download():
    with patch('app.get_store',side_effect=RuntimeError('unavailable')),patch('app.download') as source:
        response=app.app.test_client().get('/')
    assert response.status_code==200
    source.assert_not_called()
