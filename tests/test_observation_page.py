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
        self.assertEqual(tabs, ['current', 'metar-clouds', 'radar', 'satellite', 'forecast'])
        self.assertIn('id="tab-current" aria-selected="true"', html)
        self.assertIn('<section id="metar-clouds" role="tabpanel" aria-labelledby="tab-metar-clouds" hidden>', html)
        current = html.split('<section id="current"')[1].split('</section>')[0]
        self.assertIn('Hopkins sun elevation', current)
        self.assertEqual(html.count('id="hopkins-sun-angle"'), 1)
        self.assertEqual(current.count('class="hour-line"'), 12)
        self.assertIn('KFCM + KMSP + KMIC', current)
        self.assertIn('initial-current-data', html)
        self.assertIn('cloud cover and ceiling come from KMSP', html)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_default_page_survives_storage_outage_without_upstream_download(self):
        with patch('app.get_store', side_effect=RuntimeError('storage unavailable')), patch('app.download') as upstream:
            response = app.app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        upstream.assert_not_called()
        self.assertIn('Loading hourly observations', response.get_data(as_text=True))
