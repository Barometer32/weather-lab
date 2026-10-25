import re
from unittest.mock import patch
import app


def test_four_product_metar_replaces_observations_and_clouds_and_keeps_other_tabs():
    with patch('app.get_store') as store,patch('app.download') as source:
        response=app.app.test_client().get('/')
    source.assert_not_called();store.assert_not_called()
    html=response.get_data(as_text=True)
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['metar','radar','satellite','forecast','air-quality']
    metar=html.split('<section id="metar"')[1].split('</section>')[0]
    satellite=html.split('<section id="satellite"')[1].split('</section>')[0]
    assert 'id="sun-angle"' in metar and 'sun-angle' not in satellite
    assert html.count('id="sun-angle"')==1
    for mode in ('clouds','wind','dewpoint','temperature'):assert f'<option value="{mode}">' in metar
    assert 'id="metar-timeline"' in metar and ':45–:59' in metar
    assert 'tab-clouds' not in html and 'tab-observations' not in html
    for retired in ('observation-views.js','cloud-height-views.js','current-views.js','model-views.js'):assert retired not in html
    assert 'metar-views.js' in html and 'prepared-data.js' in html
    assert response.headers['Cache-Control']=='no-store'


def test_page_survives_storage_outage_without_source_download():
    with patch('app.get_store',side_effect=RuntimeError('unavailable')),patch('app.download') as source:
        response=app.app.test_client().get('/')
    assert response.status_code==200
    source.assert_not_called()
