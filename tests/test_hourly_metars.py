from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import airport_plots as airports
import app
import backfill_metars as backfill
import collector
import metar_clouds
from test_support import MemoryStore

NOW = datetime(2026, 10, 16, 12, 5, tzinfo=timezone.utc)
HOUR = NOW.replace(minute=0)


def row(station='KMSP', minutes=7, **fields):
    return {'station': station, 'lat':44.9, 'lon':-93.3, 'time':airports.iso(HOUR-timedelta(minutes=minutes)),
            'reportType':'METAR', 'tempF':60., 'dewpointF':45., 'wind':{'speedKnots':10., 'direction':270.},
            **fields}


def raw_rows():
    return [{'station':'KMSP', 'lat':44.9, 'lon':-93.3, 'time':airports.iso(HOUR-timedelta(hours=i,minutes=7)),
             'reportType':'METAR', 'temp':15., 'dewp':7., 'wspd':10., 'wdir':270., 'layers':[],
             'rawOb':'KMSP 161153Z 27010KT CLR 15/07 A3000', 'receiptTime':''} for i in range(12)]


def xml_report():
    return b'<response><data><METAR><station_id>KMSP</station_id><latitude>44.9</latitude><longitude>-93.3</longitude><observation_time>2026-10-16T11:53:00Z</observation_time><metar_type>METAR</metar_type><temp_c>15</temp_c><dewpoint_c>7</dewpoint_c><wind_speed_kt>10</wind_speed_kt><wind_dir_degrees>270</wind_dir_degrees></METAR></data></response>'


class HourlyMetarTests(unittest.TestCase):
    def setUp(self):
        app._cache.clear()

    def test_strict_window_boundaries_and_report_types(self):
        reports=[row('KSTA',10),row('KEND',minutes=1/60),row('KOLD',minutes=10+1/60),row('KNEW',0),
                 row('KSPE',reportType='SPECI'),row('KRAP',rawOb='MADISHF'),row('KBAD',source='mesonet')]
        data=airports.collect(None,NOW,airport_rows=reports)
        self.assertEqual({r['station'] for r in data['stations']},{'KSTA','KEND'})
        self.assertEqual(data['windowMinutes'],10)
        for minutes,expected in [(10,HOUR),(10+1/60,None),(1/60,HOUR),(0,None)]:
            r={'metarType':'METAR','obsTime':(HOUR-timedelta(minutes=minutes)).timestamp()}
            self.assertEqual(app.routine_hour(r,NOW),expected)

    def test_closest_to_53_and_latest_correction_win_even_across_saved_history(self):
        old=airports.collect(None,NOW,airport_rows=[row(tempF=50),row(minutes=5,tempF=70)])
        new=airports.collect(None,NOW,old,airport_rows=[row(tempF=51,receiptTime='2026-10-16T11:59:00Z'),row(minutes=8,tempF=55)])
        self.assertEqual(new['stations'][0]['tempF'],51)
        self.assertEqual(new['stations'][0]['time'],'2026-10-16T11:53:00Z')

    def test_qc_rejects_bad_coordinates_and_impossible_fields(self):
        data=airports.collect(None,NOW,airport_rows=[row(dewpointF=90),row('KBAD',lat=0),row('KNULL',tempF=900,dewpointF=-900,wind={})])
        self.assertEqual(len(data['stations']),1)
        self.assertIsNone(data['stations'][0]['dewpointF'])
        self.assertAlmostEqual(data['stations'][0]['wind']['speedMph'],11.50779448)

    def test_backfill_publishes_all_twelve_real_hours_and_no_contour_assets(self):
        store=MemoryStore()
        data=backfill.publish_history({'source':airports.SOURCE,'reports':raw_rows()},store,NOW)
        self.assertEqual(len(data),12)
        self.assertTrue(all(h['stations']==1 for h in data))
        saved=store.read_json('live/station-plots.json')
        self.assertEqual([f['stations'][0]['time'] for f in saved['history']],sorted(r['time'] for r in raw_rows()))
        self.assertTrue(all('analysisUrl' not in h for h in saved['history']))
        self.assertEqual(store.writes,['live/station-plots.json'])

    def test_incomplete_backfill_and_failed_hourly_collection_preserve_previous_data(self):
        store=MemoryStore();store.write_json('live/station-plots.json',airports.collect(None,NOW,airport_rows=[row()]))
        previous=dict(store.objects)
        with self.assertRaises(ValueError):backfill.publish_history({'source':airports.SOURCE,'reports':raw_rows()[:-1]},store,NOW)
        self.assertEqual(store.objects,previous)
        with patch('backfill_metars.fetch_history',side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):collector.collect_stations(store,NOW+timedelta(hours=1))
        self.assertEqual(store.objects,previous)

    def test_archive_query_is_capped_tiled_deduplicated_and_supports_one_hour(self):
        import xml.etree.ElementTree as ET
        one=ET.tostring(ET.fromstring(xml_report()).find('.//METAR'))
        calls=[]
        def download(url):
            query=parse_qs(urlparse(url).query);calls.append(query)
            return b'<response><data>'+one*(4 if query['bbox']==['40,-100,50,-85'] else 1)+b'</data></response>'
        archive=backfill.fetch_history(download,NOW,limit=4,interval=0,pause=lambda _:None,hours=1)
        self.assertEqual(len(calls),3)
        self.assertEqual(len(archive['reports']),1)
        self.assertTrue(all(c['hours']==['1'] and c['date']==[airports.iso(HOUR)] for c in calls))

    def test_hourly_collector_queries_archive_once_and_second_run_is_noop(self):
        store=MemoryStore()
        with patch('backfill_metars.fetch_history',return_value={'reports':raw_rows()[:1]}) as fetch:
            collector.collect_stations(store,NOW)
            collector.collect_stations(store,NOW+timedelta(minutes=15))
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs['hours'],1)
        self.assertEqual(store.writes,['live/station-plots.json'])

    def test_public_reader_only_reads_prepared_data_and_has_twelve_positions(self):
        store=MemoryStore();rows=[row(minutes=7+60*i) for i in range(12)]
        store.write_json('live/station-plots.json',airports.collect(None,NOW,airport_rows=rows))
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as download:
            response=app.app.test_client().get('/api/station-plots')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['history']),12)
        self.assertTrue(all(f['stations'] for f in response.json['history']))
        download.assert_not_called()

    def test_page_has_only_requested_maps_and_no_contour_asset_routes(self):
        client=app.app.test_client();html=client.get('/').get_data(as_text=True)
        for text in ['tab-metar-clouds','tab-radar','tab-satellite','tab-forecast',':50–:59']:
            self.assertIn(text,html)
        for text in ['surface-analysis.js','id="surface-map"','id="metar-view"','id="observations"']:
            self.assertNotIn(text,html)
        self.assertEqual(client.get('/api/prepared/analysis/surface-v3/202610161200/0000000000000000/tempF.png').status_code,404)
        self.assertEqual(client.get('/api/metar-clouds').status_code,404)
        self.assertEqual(client.post('/collect/metar-clouds').status_code,404)

    def test_hourly_staleness_allows_five_minute_arrival_buffer(self):
        data={'checkedAt':airports.iso(NOW-timedelta(hours=1))}
        store=MemoryStore();store.write_json('live/station-plots.json',data)
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=HOUR+timedelta(minutes=6)):
            self.assertFalse(app.prepared_hourly_snapshot('station-plots')['stale'])
        app._cache.clear()
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=HOUR+timedelta(minutes=8)):
            self.assertTrue(app.prepared_hourly_snapshot('station-plots')['stale'])


if __name__=='__main__':unittest.main()
