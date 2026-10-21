import re
from unittest.mock import patch
import app


def test_current_summary_sun_and_other_tabs_without_history_or_models():
    with patch('app.get_store',return_value=None),patch('app.download') as source:
        response=app.app.test_client().get('/')
    source.assert_not_called()
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['current','radar','metar-clouds','satellite','forecast','air-quality']
    current=html.split('<section id="current"')[1].split('</section>')[0]
    satellite=html.split('<section id="satellite"')[1].split('</section>')[0]
    assert 'id="sun-angle"' in current and 'sun-angle' not in satellite
    assert html.count('id="sun-angle"')==1
    assert 'id="history"' not in current and 'Last 12 hours' not in current
    for reading in ['temperature','dewpoint','wind']:assert f'id="{reading}"' in current
    assert 'KFCM + KMIC + KMSP' in current and 'initial-current-data' in html
    assert 'model-views.js' not in html
    assert 'data-ceiling-unit="hundreds-ft"' in html and 'Last 12 routine hourly snapshots' in html
    assert 'map-fullscreen.js' in html and 'id="metar-fullscreen"' in html
    assert 'data-src="https://gis-ext-aqi.pca.mn.gov/aqi/aqi-current-conditions.html"' in html
    assert response.headers['Cache-Control']=='no-store'


def test_page_survives_storage_outage_without_source_download():
    with patch('app.get_store',side_effect=RuntimeError('unavailable')),patch('app.download') as source:
        response=app.app.test_client().get('/')
    assert response.status_code==200
    source.assert_not_called()
