import re
from unittest.mock import patch
import app


def test_airport_metar_map_replaces_current_and_keeps_other_tabs():
    with patch('app.get_store') as store,patch('app.download') as source:
        response=app.app.test_client().get('/')
    source.assert_not_called();store.assert_not_called()
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['metar-clouds','radar','satellite','forecast','air-quality']
    metars=html.split('<section id="metar-clouds"')[1].split('</section>')[0]
    satellite=html.split('<section id="satellite"')[1].split('</section>')[0]
    assert 'id="sun-angle"' in metars and 'sun-angle' not in satellite
    assert html.count('id="sun-angle"')==1
    assert 'id="metar-cloud-timeline"' in metars
    assert 'current-views.js' not in html and 'tab-current' not in html and 'initial-current-data' not in html
    assert 'model-views.js' not in html
    assert 'metar-model.js' in html and 'cloud-views.js' in html and 'map-fullscreen.js' in html
    assert ':45–:59' in metars and ':00' in metars and 'KCFE, KFCE, KSGS and KDEH' in metars
    assert 'id="clouds-timeline"' not in html and 'data-ceiling-unit="thousands-ft"' in metars
    assert 'cloud-height-views.js' not in html and 'id="clouds"' not in html
    assert '>AIR Q</button>' in html and 'id="airq-timeline"' in html
    assert 'id="metar-timeline-description"' not in html
    assert '<iframe id="air-quality-map"' not in html
    assert response.headers['Cache-Control']=='no-store'


def test_page_survives_storage_outage_without_source_download():
    with patch('app.get_store',side_effect=RuntimeError('unavailable')),patch('app.download') as source:
        response=app.app.test_client().get('/')
    assert response.status_code==200
    source.assert_not_called()
