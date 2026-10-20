import re
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
import app

NOW = datetime(2026, 10, 20, 12, 2, tzinfo=timezone.utc)

class CurrentHomePageTests(unittest.TestCase):
    def test_current_is_initial_view_with_prepared_summary_and_sun(self):
        summary = app.observations([], NOW)
        summary.update(checkedAt=app.iso(NOW), stale=False)
        with patch('app.download') as upstream, patch('app.observation_payload', return_value=summary) as average:
            response = app.app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        upstream.assert_not_called()
        average.assert_called_once_with(saved_only=True)
        tabs = re.findall(r'<button role="tab" id="tab-([^"]+)"', html)
        self.assertEqual(tabs, ['current', 'radar', 'metar-clouds', 'satellite', 'models', 'forecast', 'air-quality'])
        self.assertIn('/static/model-views.js',html)
        self.assertIn('P01 is inches of liquid-equivalent precipitation',html)
        air=html.split('<section id="air-quality"')[1].split('</section>')[0]
        self.assertIn('title="MPCA current air quality conditions map"',air)
        self.assertIn('data-src="https://gis-ext-aqi.pca.mn.gov/aqi/aqi-current-conditions.html"',air)
        self.assertIn('Open map directly if it does not display',air)
        self.assertIn('id="tab-current" aria-selected="true"', html)
        self.assertIn('<section id="metar-clouds" role="tabpanel" aria-labelledby="tab-metar-clouds" hidden>', html)
        current = html.split('<section id="current"')[1].split('</section>')[0]
        self.assertNotIn('id="sun-angle"',current)
        satellite=html.split('<section id="satellite"')[1].split('</section>')[0]
        self.assertIn('<p class="satellite-sun">Sun angle <strong id="sun-angle"',satellite)
        self.assertNotIn('current-sun',html)
        self.assertNotIn('Hopkins',current)
        self.assertNotIn('class="metric',current)
        for tile in ['temperature','dewpoint','wind']:
            self.assertNotIn(f'id="{tile}"',current)
        self.assertNotIn('id="metar-view"',html)
        self.assertIn('data-ceiling-unit="hundreds-ft"',html)
        self.assertEqual(html.count('id="sun-angle"'), 1)
        self.assertEqual(current.count('class="hour-line"'), 12)
        self.assertIn('KFCM + KMSP + KMIC', current)
        self.assertIn('initial-current-data', html)
        clouds=html.split('<section id="metar-clouds"')[1].split('</section>')[0]
        self.assertNotIn('cloud-height-scale',clouds)
        self.assertNotIn('data-cloud-height-palette',clouds)
        self.assertIn('27 = 2,700 ft',clouds)
        self.assertIn('250 = 25,000 ft',clouds)
        self.assertNotIn('metar-model.js',html)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_default_page_survives_storage_outage_without_upstream_download(self):
        with patch('app.get_store', side_effect=RuntimeError('storage unavailable')), patch('app.download') as upstream:
            response = app.app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        upstream.assert_not_called()
        self.assertIn('Loading hourly observations', response.get_data(as_text=True))
