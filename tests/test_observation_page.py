import re
import unittest
from unittest.mock import patch
import app

class MetarHomePageTests(unittest.TestCase):
    def test_metar_is_the_only_initial_view_and_observations_are_removed(self):
        with patch('app.download') as upstream,patch('app.observation_payload') as average:
            response=app.app.test_client().get('/')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        upstream.assert_not_called();average.assert_not_called()
        self.assertNotIn('tab-observations',html)
        self.assertNotIn('initial-observations',html)
        self.assertNotIn('sun-angle',html)
        tabs=re.findall(r'<button role="tab" id="tab-([^"]+)"',html)
        self.assertEqual(tabs,['metar-clouds','radar','satellite','forecast'])
        self.assertIn('id="tab-metar-clouds" aria-selected="true"',html)
        self.assertIn('<section id="metar-clouds" role="tabpanel" aria-labelledby="tab-metar-clouds">',html)
        self.assertIn('<option value="plots">METAR plots</option>',html)
        self.assertIn('wind speed in mph',html)
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_default_page_does_not_depend_on_any_saved_observation_data(self):
        with patch('app.get_store',side_effect=RuntimeError('storage unavailable')):
            self.assertEqual(app.app.test_client().get('/').status_code,200)
