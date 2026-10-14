from datetime import datetime, timedelta, timezone
import gzip
import json
import unittest
from unittest.mock import patch

import app
import collector
import station_plots as stations
from test_realtime import MemoryStore

NOW = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)


def row(identifier='MSP', network='MN_ASOS', **values):
    return {'station': identifier, 'name': 'Minneapolis', 'network': network, 'state': 'MN',
            'utc_valid': '2026-10-14T19:55:00Z', 'lat': 44.9, 'lon': -93.3,
            'tmpf': 55.4, 'dwpf': 40.1, 'sknt': 10, 'drct': 270,
            'raw': 'K'+identifier+' 141955Z AUTO 27010KT 13/04 A3020', **values}


def payload(*rows):
    return json.dumps({'data': rows}).encode()


def empty_wisconet():
    return json.dumps({'type': 'FeatureCollection', 'features': []}).encode()


def awc_xml():
    return b'<response><data><METAR><station_id>KMSP</station_id><latitude>44.9</latitude><longitude>-93.3</longitude><observation_time>2026-10-14T19:53:00Z</observation_time><metar_type>METAR</metar_type><raw_text>KMSP 141953Z AUTO 27010KT 13/04 RMK T01330044</raw_text><temp_c>13</temp_c><dewpoint_c>4</dewpoint_c><wind_speed_kt>10</wind_speed_kt><wind_dir_degrees>270</wind_dir_degrees><sky_condition sky_cover="BKN" cloud_base_ft_agl="2500"/></METAR></data></response>'


def downloader(*rows):
    def download(url):
        if 'aviationweather.gov' in url:
            return awc_xml()
        if '/request/rwis.py?' in url:
            return b'Sorry, no results found for query!'
        if 'api.wisconet.wisc.edu' in url:
            return empty_wisconet()
        return payload(*rows) if url.endswith('=MN') else payload()
    return download


class StationPlotTests(unittest.TestCase):
    def setUp(self):
        app._cache.clear()

    def test_source_units_air_temperature_and_network_ids(self):
        rows = stations.parse(payload(row(tsf0=110), row('MN001', 'MN_RWIS', tmpf=60)), NOW)
        indexed = {r['station']: r for r in rows}
        self.assertEqual(indexed['KMSP']['tempF'], 55.4)
        self.assertEqual(indexed['MN001']['tempF'], 60)
        self.assertAlmostEqual(indexed['KMSP']['wind']['speedMph'], 11.50779448)
        self.assertEqual(indexed['MN001']['stationKey'], 'MN_RWIS:MN001')
        self.assertEqual(indexed['KMSP']['time'], '2026-10-14T19:55:00Z')

    def test_stale_future_missing_bad_coordinates_and_values(self):
        rows = stations.parse(payload(
            row('OLD', utc_valid=stations.iso(NOW-timedelta(minutes=91))),
            row('FUT', utc_valid=stations.iso(NOW+timedelta(seconds=1))),
            row('LOC', lat=float('nan')), row('OUT', lon=-110),
            row('NIL', tmpf=None, dwpf=None, sknt=None),
            row('BAD', tmpf=1000, dwpf=-9999, sknt=-10),
            row('BOOL', tmpf=True, dwpf=True, sknt=True),
            row('CFE'), row('SGS'), row('FCE'),
            row('OK1', dwpf=70), row('UNK', drct=None),
            row('VRB', drct=None, raw='KVRB 141955Z VRB10KT')), NOW)
        indexed = {r['station']: r for r in rows}
        self.assertEqual(set(indexed), {'KOK1', 'KUNK', 'KVRB'})
        self.assertIsNone(indexed['KOK1']['dewpointF'])
        self.assertFalse(indexed['KUNK']['wind']['variable'])
        self.assertTrue(indexed['KVRB']['wind']['variable'])

    def test_duplicate_ids_in_separate_networks_and_latest_report(self):
        rows = stations.parse(payload(row('ABC', 'MN_DCP'), row('ABC', 'MN_RWIS'),
                            row('ABC', 'MN_DCP', utc_valid='2026-10-14T19:56:00Z', tmpf=61)), NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['stationKey'] for r in rows}, {'MN_DCP:ABC', 'MN_RWIS:ABC'})
        self.assertEqual(next(r for r in rows if r['network'] == 'MN_DCP')['tempF'], 61)

    def test_hourly_window_boundaries_and_no_post_hour_relabeling(self):
        result = stations.collect(downloader(
            row('START', 'MN_RWIS', utc_valid='2026-10-14T19:35:00Z'),
            row('MNDOT', 'MN_RWIS', utc_valid='2026-10-14T19:40:00Z'),
            row('AT00', 'MN_RWIS', utc_valid='2026-10-14T20:00:00Z'),
            row('END', 'MN_RWIS', utc_valid='2026-10-14T19:59:59Z'),
            row('OLD', 'MN_RWIS', utc_valid='2026-10-14T19:34:59Z'),
            row('NEW', 'MN_RWIS', utc_valid='2026-10-14T20:00:01Z')), NOW+timedelta(minutes=10))
        self.assertEqual({r['station'] for r in result['stations']}, {'START', 'MNDOT', 'END'})
        self.assertEqual(result['hour'], '2026-10-14T20:00:00Z')
        self.assertEqual(len(result['history']), 12)
        self.assertNotIn('pendingHour', result)

    def test_airports_exclude_specials_rapid_and_prefer_official_routine(self):
        official = {'station': 'KMSP', 'time': '2026-10-14T19:53:00Z', 'lat': 44.9, 'lon': -93.3,
                    'tempF': 56.0, 'dewpointF': 40.0, 'wind': {'speedKnots': 10}, 'reportType': 'METAR'}
        result = stations.collect(downloader(
            row('MSP', raw='SPECI KMSP 141955Z'),
            row('RAP', raw='KRAP 141955Z MADISHF'),
            row('FCM', raw='KFCM 141955Z AUTO'),
            row('UNK', raw=None)), NOW, airport_rows=[official])
        indexed = {r['station']: r for r in result['stations']}
        self.assertEqual(set(indexed), {'KMSP', 'KFCM'})
        self.assertEqual(indexed['KMSP']['source'], 'NOAA Aviation Weather Center')
        self.assertEqual(indexed['KMSP']['tempF'], 56.0)
        self.assertEqual(indexed['KMSP']['stationKey'], 'MN_ASOS:KMSP')

    def test_old_history_is_filtered_and_failed_collection_does_not_invent_a_new_hour(self):
        rows = stations.parse(payload(row(), row('OLD', 'MN_RWIS', utc_valid='2026-10-14T19:30:00Z')), NOW)
        frames = stations.history([{'hour': stations.iso(NOW), 'stations': rows}], NOW)
        saved = {'hour': stations.iso(NOW), 'history': frames, 'stations': rows}
        result = stations.current(saved, NOW+timedelta(hours=2))
        self.assertEqual(result['history'][-1]['hour'], stations.iso(NOW))
        self.assertEqual([r['station'] for r in result['stations']], ['KMSP'])
        next_frames = stations.history(frames+[{'hour': stations.iso(NOW+timedelta(hours=1)), 'stations': rows}], NOW+timedelta(hours=1))
        self.assertEqual(next_frames[-1]['stations'], [])

    def test_partial_failure_carries_only_same_hour_window(self):
        previous = {'stations': stations.parse(payload(row('OLD', state='WI'),
                    row('STA', state='WI', utc_valid='2026-10-14T19:00:00Z')), NOW), 'history': []}
        base = downloader(row('NEW'))
        def download(url):
            if url.endswith('=WI'):
                raise TimeoutError('temporary failure')
            return base(url)
        with self.assertLogs('station_plots', level='ERROR'):
            result = stations.collect(download, NOW+timedelta(minutes=2), previous)
        self.assertEqual(result['failedSources'], ['WI'])
        self.assertEqual({r['station'] for r in result['stations']}, {'KOLD', 'KNEW'})

    def test_total_failure_does_not_replace_prepared_object(self):
        store = MemoryStore()
        store.write_json('live/station-plots.json', {'version': 1, 'checkedAt': stations.iso(NOW-timedelta(hours=1)), 'stations': []})
        before = store.read('live/station-plots.json')
        with patch('collector.collect_metar_clouds', side_effect=TimeoutError()), patch('app.download', side_effect=downloader()), self.assertRaises(ValueError), self.assertLogs('collector', level='ERROR'):
            collector.collect_stations(store, NOW)
        self.assertEqual(store.read('live/station-plots.json'), before)

    def test_hourly_collector_shares_airport_download_and_deduplicates_repeated_triggers(self):
        store = MemoryStore()
        with patch('app.download', side_effect=downloader(row('MSP', raw='SPECI KMSP 141955Z'))) as download:
            collector.collect_stations(store, NOW)
        self.assertEqual(download.call_count, len(stations.STATES)+len(stations.RWIS_NETWORKS)+2)
        self.assertEqual(sum('aviationweather.gov' in c.args[0] for c in download.call_args_list), 1)
        self.assertEqual(store.writes[-1], 'live/station-plots.json')
        with patch('app.get_store', return_value=store), patch('app.utcnow', return_value=NOW), patch('app.download') as upstream:
            result = app.app.test_client().get('/api/station-plots')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['stations'][0]['source'], 'NOAA Aviation Weather Center')
        upstream.assert_not_called()
        with patch('app.download') as duplicate:
            collector.collect_stations(store, NOW+timedelta(minutes=55))
        duplicate.assert_not_called()

    def test_delayed_api_retains_original_hour_compresses_history_without_upstream(self):
        rows = stations.parse(payload(*(row(str(i).zfill(3)) for i in range(100))), NOW)
        frames = stations.history([{'hour': stations.iso(NOW), 'stations': rows}], NOW)
        store = MemoryStore()
        store.write_json('live/station-plots.json', {'version': 2, 'hour': stations.iso(NOW), 'checkedAt': stations.iso(NOW), 'stations': rows, 'history': frames})
        with patch('app.get_store', return_value=store), patch('app.utcnow', return_value=NOW+timedelta(hours=2)), patch('app.download') as upstream:
            plain = app.app.test_client().get('/api/station-plots')
            zipped = app.app.test_client().get('/api/station-plots', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(len(plain.json['stations']), 100)
        self.assertEqual(plain.json['history'][-1]['hour'], stations.iso(NOW))
        self.assertTrue(plain.json['stale'])
        self.assertEqual(json.loads(gzip.decompress(zipped.data)), plain.json)
        upstream.assert_not_called()

    def test_missing_prepared_data_returns_explicit_error_without_upstream(self):
        with patch('app.get_store', return_value=MemoryStore()), patch('app.download') as upstream:
            result = app.app.test_client().get('/api/station-plots')
        self.assertEqual(result.status_code, 503)
        self.assertIn('being prepared', result.json['error'])
        upstream.assert_not_called()


if __name__ == '__main__':
    unittest.main()
