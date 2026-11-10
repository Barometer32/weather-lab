import re
from unittest.mock import patch
import app


def test_observations_is_the_hourly_home_page():
    with patch('app.get_store') as store,patch('app.download') as source:
        response=app.app.test_client().get('/')
    source.assert_not_called();store.assert_not_called()
    html=response.get_data(as_text=True)
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['observations','metar','radar','satellite','forecast','air-quality']
    assert 'id="tab-observations" aria-selected="true"' in html
    metar=html.split('<section id="metar"')[1].split('</section>')[0]
    satellite=html.split('<section id="satellite"')[1].split('</section>')[0]
    assert 'id="sun-angle"' in metar and 'sun-angle' not in satellite
    assert html.count('id="sun-angle"')==1
    observations=html.split('<section id="observations"')[1].split('</section>')[0]
    assert ' hidden' not in observations.split('>',1)[0]
    assert ' hidden' in metar.split('>',1)[0]
    assert 'id="observations-sun"' in observations and 'observations-temperature' not in observations
    assert '<table' in observations and 'Last 12 hours' in observations and 'count toward the following hour' not in observations
    assert '/api/observations/hourly' in html
    assert re.findall(r'<option value="([^"]+)"( selected)?>([^<]+)</option>',metar)==[
        ('clouds',' selected','CLOUDS'),('plots','','METARS')
    ]
    assert 'id="metar-timeline"' in metar and ':45–:59' in metar
    assert 'tab-clouds' not in html
    for retired in ('observation-views.js','cloud-height-views.js','current-views.js','model-views.js'):assert '/static/'+retired not in html
    assert 'metar-views.js' in html and 'prepared-data.js' in html
    assert response.headers['Cache-Control']=='no-store'


def test_page_survives_storage_outage_without_source_download():
    with patch('app.get_store',side_effect=RuntimeError('unavailable')),patch('app.download') as source:
        response=app.app.test_client().get('/')
    assert response.status_code==200
    source.assert_not_called()
