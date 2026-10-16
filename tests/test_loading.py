from datetime import datetime,timezone,timedelta
import gzip,json,unittest
from unittest.mock import patch
from flask import Response
import app as weather
from surface_analysis import VERSION
from test_support import MemoryStore

class LoadingTests(unittest.TestCase):
    def test_json_history_is_compressed_and_q_zero_is_respected(self):
        now=datetime(2026,10,16,18,5,tzinfo=timezone.utc)
        data={'version':VERSION,'hour':weather.iso(now.replace(minute=0)), 'checkedAt':weather.iso(now),
              'history':[{'hour':weather.iso(now-timedelta(hours=i)), 'stationCount':600,
                          'analysisUrl':'/api/prepared/analysis/'+VERSION+'/202610161800/'+'a'*16+'/manifest.json'} for i in range(12)]}
        store=MemoryStore();store.write_json('live/maps.json',data);weather._cache.clear()
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=now):
            client=weather.app.test_client()
            response=client.get('/api/maps',headers={'Accept-Encoding':'gzip'})
            self.assertEqual(response.headers['Content-Encoding'],'gzip')
            self.assertIn('Accept-Encoding',response.headers['Vary'])
            decoded=gzip.decompress(response.data)
            self.assertEqual(len(json.loads(decoded)['history']),12)
            self.assertLess(len(response.data),len(decoded)/2)
            plain=client.get('/api/maps',headers={'Accept-Encoding':'gzip;q=0'})
            self.assertNotIn('Content-Encoding',plain.headers)
            self.assertEqual(plain.data,decoded)
        weather._cache.clear()

    def test_already_compressed_payload_is_not_compressed_again(self):
        packed=gzip.compress(b'{"saved":"'+b'x'*3000+b'"}')
        with weather.app.test_request_context(headers={'Accept-Encoding':'gzip'}):
            response=Response(packed,mimetype='application/json',headers={'Content-Encoding':'gzip'})
            self.assertEqual(weather.compress_json(response).data,packed)
