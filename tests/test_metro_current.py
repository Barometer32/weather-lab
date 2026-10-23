from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest
import app
import metar_clouds
from test_realtime import MemoryStore

NOW = datetime(2026, 10, 20, 12, 2, tzinfo=timezone.utc)

def reports(hour=12):
    stamp=NOW.replace(hour=hour,minute=0)-timedelta(minutes=7)
    return [dict(station=station, lat=44.9, lon=-93.4, time=app.iso(stamp),
                 reportType='METAR',temp=20,dewp=10,wspd=10,wdir=direction,
                 rawOb=f'{station} 201153Z 20/10 RMK T0{temp}0{dew}',
                 layers=[dict(cover='BKN',baseFtAGL=height)])
            for station,temp,dew,direction,height in [
                ('KFCM','201','101',350,1000),('KMIC','202','102',10,2000),('KMSP','206','106',0,2700)]]

class MetroCurrentTests(unittest.TestCase):
    def test_exact_precision_and_circular_wind_clouds_remain_real_kmsp(self):
        data=metar_clouds.current(metar_clouds.snapshot(reports(),NOW),NOW)
        metro=data['metro']
        self.assertTrue(metro['available'])
        self.assertAlmostEqual(metro['tempF'],68.5)
        self.assertAlmostEqual(metro['dewpointF'],50.5)
        self.assertIn(metro['wind']['direction'],[0,360])
        self.assertEqual(metro['wind']['speedMph'],11.5)
        self.assertEqual(metro['cloudSource'],'KMSP')
        self.assertEqual(metro['ceiling']['baseFtAGL'],2700)
        self.assertEqual(metro['skyCover']['code'],'BKN')
        self.assertEqual([s['station'] for s in data['stations']],['KFCM','KMIC','KMSP'])
        self.assertEqual(len(data['history']),12)
        self.assertTrue(all(h['metro']['lat']==metro['lat'] and h['metro']['lon']==metro['lon'] for h in data['history']))

    def test_missing_or_bad_source_stays_blank_no_previous_hour_substitution(self):
        items=reports()+reports(hour=11)
        items=[r for r in items if not (r['station']=='KMIC' and r['time']==reports()[0]['time'])]
        result=metar_clouds.current(metar_clouds.snapshot(items,NOW),NOW)
        self.assertFalse(result['metro']['available'])
        self.assertEqual(result['metro']['qa']['stationsUsed'],2)
        self.assertIsNone(result['metro']['tempF'])
        self.assertIsNone(result['metro']['cloudSource'])
        self.assertTrue(result['history'][-2]['metro']['available'])
        bad=reports();bad[0].update(dewp=50,rawOb='KFCM 201153Z')
        result=metar_clouds.current(metar_clouds.snapshot(bad,NOW),NOW)
        self.assertFalse(result['metro']['available'])
        self.assertEqual(result['metro']['qa']['checks']['dewpoint'],2)

    def test_local_current_average_is_separate_from_legacy_hourly_cloud_history(self):
        import local_current
        app._cache.clear()
        saved=metar_clouds.snapshot(reports(),NOW)
        store=MemoryStore();store.write_json('live/metar-clouds.json',saved)
        raw=[dict(station='LOCAL'+str(i),name='Local Test Site',lat=44.925,lon=-93.463,
                  time=app.iso(NOW-timedelta(minutes=i*5)),tempF=68.,dewpointF=50.,
                  wind={'speedMph':10.,'direction':225},network='Hennepin West') for i in range(3)]
        latest=local_current.candidate(raw,NOW)
        store.write_json('live/current.json',dict(version=local_current.VERSION,reports=raw,lastGood=latest,
            checkedAt=app.iso(NOW),sourceFailures=[]))
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as download:
            client=app.app.test_client()
            metro=client.get('/api/metar-clouds').json['metro']
            summary=client.get('/api/observations').json
            page=client.get('/').get_data(as_text=True)
        download.assert_not_called()
        self.assertEqual(metro['tempF'],68.5)
        self.assertEqual(summary['current']['tempF'],68.0)
        self.assertAlmostEqual(summary['current']['wind']['direction'],225.)
        self.assertEqual(summary['current']['wind']['speedMph'],10.)
        self.assertIn('>68.0°F<',page)
        self.assertNotIn('tab-metar-clouds',page)
        self.assertNotIn('history',summary)
