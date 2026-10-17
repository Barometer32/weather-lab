from datetime import datetime,timezone,timedelta
import gzip,json,unittest
from unittest.mock import patch
from flask import Response
import app as weather
import airport_plots
from test_support import MemoryStore

class LoadingTests(unittest.TestCase):
    def test_json_history_is_compressed_and_q_zero_is_respected(self):
        now=datetime(2026,10,16,18,5,tzinfo=timezone.utc)
        rows=[{'station':f'K{i:03d}','lat':44.9,'lon':-93.3,
               'time':weather.iso(now.replace(minute=0)-timedelta(hours=h,minutes=7)),
               'reportType':'METAR','tempF':60.,'dewpointF':45.,'wind':{'speedMph':10.,'direction':270.}}
              for h in range(12) for i in range(20)]
        data=airport_plots.collect(None,now,airport_rows=rows)
        store=MemoryStore();store.write_json('live/station-plots.json',data);weather._cache.clear()
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=now):
            client=weather.app.test_client()
            response=client.get('/api/station-plots',headers={'Accept-Encoding':'gzip'})
            self.assertEqual(response.headers['Content-Encoding'],'gzip')
            self.assertIn('Accept-Encoding',response.headers['Vary'])
            decoded=gzip.decompress(response.data)
            self.assertEqual(len(json.loads(decoded)['history']),12)
            self.assertLess(len(response.data),len(decoded)/2)
            plain=client.get('/api/station-plots',headers={'Accept-Encoding':'gzip;q=0'})
            self.assertNotIn('Content-Encoding',plain.headers)
            self.assertEqual(plain.data,decoded)
        weather._cache.clear()

    def test_already_compressed_payload_is_not_compressed_again(self):
        packed=gzip.compress(b'{"saved":"'+b'x'*3000+b'"}')
        with weather.app.test_request_context(headers={'Accept-Encoding':'gzip'}):
            response=Response(packed,mimetype='application/json',headers={'Content-Encoding':'gzip'})
            self.assertEqual(weather.compress_json(response).data,packed)
