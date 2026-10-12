import json
import re
import unittest
from datetime import timedelta
from unittest.mock import patch
import app
from test_realtime import MemoryStore
from test_hourly_observations import NOW, reports

class ObservationPageTests(unittest.TestCase):
    def setUp(self):app._cache.clear()

    def page(self,store,now=NOW):
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=now),patch('app.download') as upstream:
            response=app.app.test_client().get('/')
            upstream.assert_not_called()
        self.assertEqual(response.status_code,200)
        return response,response.get_data(as_text=True)

    def test_first_html_has_actual_values_history_and_matching_json_without_upstream(self):
        store=MemoryStore();store.write_json('live/observations.json',dict(reports=reports(),checkedAt=app.iso(NOW)))
        response,html=self.page(store)
        self.assertIn('id="temperature">75°F</div>',html)
        self.assertIn('id="dewpoint">54°F</div>',html)
        self.assertEqual(re.search(r'id="wind">([^<]+)</div>',html)[1],'N 6 mph')
        heading=re.search(r'id="updated">([^<]+)</p>',html)[1]
        self.assertEqual(heading,'Oct 12, 11:00 AM CDT hourly observation')
        self.assertNotIn('METAR',heading)
        history=re.search(r'<tbody id="history">(.*?)</tbody>',html,re.S)[1]
        self.assertEqual(history.count('<tr>'),12)
        self.assertNotIn('Loading observations',history)
        bootstrap=json.loads(re.search(r'id="initial-observations">(.*?)</script>',html,re.S)[1])
        self.assertEqual(bootstrap['current']['tempF'],75.2)
        self.assertEqual(bootstrap['current']['tempF'],bootstrap['history'][0]['tempF'])
        self.assertFalse(bootstrap['stale'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_first_html_retains_missing_site_and_stale_warnings(self):
        store=MemoryStore();store.write_json('live/observations.json',dict(reports=reports()[:2],checkedAt=app.iso(NOW-timedelta(hours=2))))
        _,html=self.page(store)
        self.assertIn('id="temperature">—</div>',html)
        notice=re.search(r'id="observation-status"[^>]*>(.*?)</p>',html,re.S)[1]
        self.assertIn('KMIC',notice);self.assertIn('Background observation checks are delayed',notice)
        self.assertIn('qa-dot incomplete',html)

    def test_missing_saved_snapshot_still_loads_the_page_without_triggering_collection(self):
        _,html=self.page(MemoryStore())
        self.assertIn('id="initial-observations">null</script>',html)
        self.assertIn('Loading hourly observations',html)
        _,local=self.page(None)
        self.assertIn('id="initial-observations">null</script>',local)

    def test_bootstrap_safely_escapes_untrusted_metar_text(self):
        rows=reports();rows[0]['rawOb']='KFCM 121553Z RMK </script><script>alert(1)</script>'
        store=MemoryStore();store.write_json('live/observations.json',dict(reports=rows,checkedAt=app.iso(NOW)))
        _,html=self.page(store)
        self.assertNotIn('</script><script>alert(1)</script>',html)
        initial=json.loads(re.search(r'id="initial-observations">(.*?)</script>',html,re.S)[1])
        self.assertEqual(initial['current']['stations'][0]['rawMetar'],rows[0]['rawOb'])
