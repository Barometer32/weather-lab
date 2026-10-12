from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import math
import gzip
import json

import app
from metar_clouds import parse_reports, snapshot, current, collect, live_snapshot, metro_position
from test_realtime import MemoryStore

NOW=datetime(2026,10,11,23,58,tzinfo=timezone.utc)


def row(station='KAAA',minute=53,**values):
    return {'station':station,'time':NOW.replace(minute=minute).isoformat().replace('+00:00','Z'),
            'lat':44.9,'lon':-93.4,'layers':[{'cover':'BKN','baseFtAGL':6000,'heightType':'cloudBase'}],
            'temp':24,'dewp':12,'wspd':5,'wdir':350,'reportType':'METAR',
            'cloudReportAvailable':True,'cloudDataAvailable':True,**values}


class LiveMetarTests(unittest.TestCase):
    def setUp(self):app._cache.clear()

    def test_xml_decodes_celsius_and_knots_for_weather_plots(self):
        payload=b'<response><data><METAR><station_id>KMKT</station_id><latitude>44.2</latitude><longitude>-93.9</longitude><observation_time>2026-10-11T23:55:00Z</observation_time><temp_c>24</temp_c><dewpoint_c>12</dewpoint_c><wind_speed_kt>7</wind_speed_kt><wind_dir_degrees>180</wind_dir_degrees><sky_condition sky_cover="SCT" cloud_base_ft_agl="3000"/></METAR></data></response>'
        live=live_snapshot(parse_reports(payload,NOW),NOW)['stations'][0]
        self.assertEqual(live['tempF'],75.2)
        self.assertEqual(live['dewpointF'],53.6)
        self.assertEqual(live['wind']['speedKnots'],7)
        self.assertEqual(live['wind']['direction'],180)

    def test_live_clouds_update_independently_when_rapid_feed_omits_clouds(self):
        original=row();rapid=row(minute=55,temp=25,layers=[],cloudReportAvailable=False)
        live=live_snapshot([original,rapid],NOW)['stations'][0]
        self.assertEqual(live['time'],original['time'])
        self.assertEqual(live['weatherTime'],rapid['time'])
        self.assertEqual(live['mapLayer']['baseFtAGL'],6000)
        self.assertEqual(live['tempF'],77)
        missing=row(minute=57,layers=[])
        live=live_snapshot([original,rapid,missing],NOW)['stations'][0]
        self.assertIsNone(live['mapLayer'])

    def test_hourly_history_and_live_are_separate_with_speci_only_in_live(self):
        routine=[row(s) for s in app.STATIONS]
        speci=[row(s,57,reportType='SPECI',temp=25) for s in app.STATIONS]
        saved=snapshot(routine+speci,NOW);saved['liveReports']=routine+speci
        data=current(saved,NOW)
        self.assertEqual(len(data['history']),12)
        self.assertEqual(data['history'][-1]['metro']['tempF'],75.2)
        self.assertEqual(data['live']['metro']['tempF'],77)
        self.assertTrue(data['live']['isLive'])
        self.assertEqual(data['live']['metro']['wind']['speedKnots'],5)

    def test_live_excludes_kcfe_future_and_stale_rows(self):
        records=[row('KCFE'),row('KOK1'),row('KFUT',time=(NOW+timedelta(seconds=1)).isoformat()),
                 row('KOLD',time=(NOW-timedelta(minutes=91)).isoformat())]
        self.assertEqual([r['station'] for r in live_snapshot(records,NOW)['stations']],['KOK1'])

    def test_metro_position_is_approximately_equidistant_and_fixed(self):
        lat,lon=metro_position();scale=math.cos(math.radians((44.83+44.88+45.07)/3))
        distances=[math.hypot(lat-y,(lon-x)*scale) for y,x in [(44.83,-93.45),(44.88,-93.22),(45.07,-93.35)]]
        self.assertLess(max(distances)-min(distances),1e-8)
        self.assertTrue(44.83<lat<45.07 and -93.45<lon<-93.22)

    def test_live_metro_plot_matches_main_conditions_snapshot_exactly(self):
        store=MemoryStore();saved=snapshot([row(s,temp=10) for s in app.STATIONS],NOW)
        saved['liveReports']=[row(s,temp=10) for s in app.STATIONS]
        store.write_json('live/metar-clouds.json',saved)
        rapid=[{'icaoId':s,'obsTime':NOW.replace(minute=55).timestamp(),'temp':c,'dewp':12,'wspd':5,'wdir':350}
               for s,c in zip(app.STATIONS,[24,24,25])]
        store.write_json('live/observations.json',{'reports':[],'rapidReports':rapid,'checkedAt':app.iso(NOW)})
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as fetch:
            client=app.app.test_client();main=client.get('/api/observations').json['current'];live=client.get('/api/metar-clouds').json['live']['metro']
        self.assertEqual(live['tempF'],main['tempF'])
        self.assertEqual(live['dewpointF'],main['dewpointF'])
        self.assertEqual(live['wind'],main['wind'])
        fetch.assert_not_called()

    def test_minute_refresh_does_not_requery_hourly_history_between_backfills(self):
        previous=snapshot([row()],NOW);previous['historyCheckedAt']=app.iso(NOW)
        payload=b'<response><data><METAR><station_id>KAAA</station_id><latitude>44.9</latitude><longitude>-93.4</longitude><observation_time>2026-10-11T23:53:00Z</observation_time><sky_condition sky_cover="CLR"/></METAR></data></response>'
        with patch('metar_clouds.time.sleep'):
            urls=[]
            result=collect(lambda url:(urls.append(url),payload)[1],NOW,previous,[])
        self.assertEqual(len(urls),1)
        self.assertIn('cache',urls[0])
        self.assertEqual(result['historyCheckedAt'],previous['historyCheckedAt'])

    def test_large_metar_payload_compression_preserves_data_and_respects_negotiation(self):
        store=MemoryStore();rows=[row('K'+str(i).zfill(3)) for i in range(100)]
        saved=snapshot(rows,NOW);saved['liveReports']=rows
        store.write_json('live/metar-clouds.json',saved)
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW):
            client=app.app.test_client()
            plain=client.get('/api/metar-clouds',headers={'Accept-Encoding':'gzip;q=0'})
            compressed=client.get('/api/metar-clouds',headers={'Accept-Encoding':'gzip'})
        self.assertNotIn('Content-Encoding',plain.headers)
        self.assertEqual(compressed.headers['Content-Encoding'],'gzip')
        self.assertEqual(json.loads(gzip.decompress(compressed.data)),plain.json)
        self.assertLess(len(compressed.data),len(plain.data))


if __name__=='__main__':unittest.main()
