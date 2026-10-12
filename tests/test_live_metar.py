from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import math
import gzip
import json
from pathlib import Path
import app
import collector
from metar_clouds import parse_reports, snapshot, current, collect, metro_position
from test_realtime import MemoryStore

NOW=datetime(2026,10,11,23,58,tzinfo=timezone.utc)
def row(station='KAAA',minute=53,**values):
    return {'station':station,'time':NOW.replace(minute=minute).isoformat().replace('+00:00','Z'),
            'lat':44.9,'lon':-93.4,'layers':[{'cover':'BKN','baseFtAGL':6000,'heightType':'cloudBase'}],
            'temp':24,'dewp':12,'wspd':5,'wdir':350,'reportType':'METAR',**values}

class HourlyMetarViewTests(unittest.TestCase):
    def setUp(self):app._cache.clear()

    def test_xml_decodes_hourly_weather_values_and_precise_t_remarks(self):
        payload=b'<response><data><METAR><station_id>KMKT</station_id><latitude>44.2</latitude><longitude>-93.9</longitude><observation_time>2026-10-11T23:53:00Z</observation_time><temp_c>24</temp_c><dewpoint_c>12</dewpoint_c><wind_speed_kt>7</wind_speed_kt><wind_dir_degrees>180</wind_dir_degrees><raw_text>KMKT 112353Z 24/12 RMK T02440122</raw_text><sky_condition sky_cover="SCT" cloud_base_ft_agl="3000"/></METAR></data></response>'
        station=snapshot(parse_reports(payload,NOW),NOW)['stations'][0]
        self.assertEqual(station['tempF'],75.9)
        self.assertEqual(station['dewpointF'],54)
        self.assertEqual(station['wind']['speedKnots'],7)
        self.assertEqual(station['wind']['direction'],180)

    def test_legacy_live_rows_speci_and_rapid_cannot_reach_hourly_api(self):
        routine=[row(s) for s in app.STATIONS]
        other=[row(s,57,reportType='SPECI',temp=25) for s in app.STATIONS]+[row('KRAP',55,reportType='HFMETAR')]
        saved=snapshot(routine+other,NOW)
        saved['liveReports']=other;saved['live']={'isLive':True,'stations':other}
        data=current(saved,NOW)
        self.assertEqual(len(data['history']),12)
        self.assertEqual(data['history'][-1]['metro']['tempF'],75.2)
        self.assertNotIn('live',data);self.assertNotIn('liveReports',data)
        self.assertTrue(all(s['reportType']=='METAR' for h in data['history'] for s in h['stations']))

    def test_retained_history_rejects_mislabeled_speci_and_excluded_station(self):
        saved=snapshot([row('KOK1'),row('KCFE'),row('KFAKE',rawOb='SPECI KFAKE 112353Z')],NOW)
        self.assertEqual([s['station'] for s in saved['stations']],['KOK1'])

    def test_metro_position_is_approximately_equidistant_and_fixed(self):
        lat,lon=metro_position();scale=math.cos(math.radians((44.83+44.88+45.07)/3))
        distances=[math.hypot(lat-y,(lon-x)*scale) for y,x in [(44.83,-93.45),(44.88,-93.22),(45.07,-93.35)]]
        self.assertLess(max(distances)-min(distances),1e-8)

    def test_hourly_metro_plot_matches_main_conditions_snapshot_exactly(self):
        rows=[row(s,temp=10,dewp=5,rawOb=f'{s} 112353Z 10/05 RMK T01040053') for s in app.STATIONS]
        store=MemoryStore();store.write_json('live/metar-clouds.json',snapshot(rows,NOW))
        routine=[{**r,'icaoId':r['station'],'metarType':'METAR','obsTime':NOW.replace(minute=53).timestamp()} for r in rows]
        store.write_json('live/observations.json',{'reports':routine,'checkedAt':app.iso(NOW)})
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as fetch:
            client=app.app.test_client();main=client.get('/api/observations').json['current'];metro=client.get('/api/metar-clouds').json['history'][-1]['metro']
        self.assertEqual(main['tempF'],50.7)
        self.assertEqual(metro['tempF'],main['tempF']);self.assertEqual(metro['dewpointF'],main['dewpointF']);self.assertEqual(metro['wind'],main['wind'])
        fetch.assert_not_called()

    def test_each_scheduled_check_recovers_routine_reports_hidden_by_newer_speci(self):
        previous=snapshot([row()],NOW);previous['historyCheckedAt']=app.iso(NOW)
        cache=b'<response><data><METAR><station_id>KAAA</station_id><latitude>44.9</latitude><longitude>-93.4</longitude><metar_type>SPECI</metar_type><observation_time>2026-10-11T23:57:00Z</observation_time><sky_condition sky_cover="OVC" cloud_base_ft_agl="1000"/></METAR></data></response>'
        hourly=cache.replace(b'SPECI',b'METAR').replace(b'23:57',b'23:53').replace(b'1000',b'6000')
        with patch('metar_clouds.time.sleep'):
            urls=[]
            result=collect(lambda url:(urls.append(url),cache if 'cache' in url else hourly)[1],NOW,previous)
        self.assertEqual(len(urls),2)
        self.assertEqual(result['stations'][0]['mapLayer']['baseFtAGL'],6000)
        self.assertNotIn('live',result)
        self.assertEqual(result['historyCheckedAt'],app.iso(NOW))

    def test_collector_never_downloads_madis_and_has_three_scheduled_checks(self):
        store=MemoryStore()
        with patch('metar_clouds.collect',return_value=snapshot([row()],NOW)),patch('app.get_rapid_reports') as rapid:
            collector.collect_metar_clouds(store,NOW)
        rapid.assert_not_called()
        self.assertIn("weather_schedule metar-clouds '2,55,58 * * * *'",Path('deploy.sh').read_text())

    def test_large_metar_payload_compression_preserves_data_and_respects_negotiation(self):
        store=MemoryStore();rows=[row('K'+str(i).zfill(3)) for i in range(100)]
        store.write_json('live/metar-clouds.json',snapshot(rows,NOW))
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW):
            client=app.app.test_client()
            plain=client.get('/api/metar-clouds',headers={'Accept-Encoding':'gzip;q=0'})
            compressed=client.get('/api/metar-clouds',headers={'Accept-Encoding':'gzip'})
        self.assertNotIn('Content-Encoding',plain.headers)
        self.assertEqual(compressed.headers['Content-Encoding'],'gzip')
        self.assertEqual(json.loads(gzip.decompress(compressed.data)),plain.json)
        self.assertNotIn('live',plain.json)

    def test_schedule_aware_metar_staleness_allows_between_check_gap(self):
        store=MemoryStore();store.write_json('live/metar-clouds.json',snapshot([row()],NOW,app.iso(NOW.replace(minute=2))))
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW.replace(minute=40)):
            response=app.app.test_client().get('/api/metar-clouds')
        self.assertFalse(response.json['stale'])
        app._cache.clear()
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW.replace(minute=57)):
            response=app.app.test_client().get('/api/metar-clouds')
        self.assertTrue(response.json['stale'])

if __name__=='__main__':unittest.main()
