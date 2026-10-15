from datetime import timedelta
import unittest

import station_plots as stations
from test_station_plots import NOW, downloader, row
from test_late_road_reports import archive


class StationHealthTests(unittest.TestCase):
    def test_absent_networks_remain_visible_without_any_current_rows(self):
        previous = {'expectedNetworks': ['MN_DCP'], 'history': [], 'coverage': []}
        result = stations.collect(downloader(row()), NOW, previous, airport_rows=[])
        counts = {r['network']: r['selected'] for r in result['history'][-1]['networkHealth']}
        self.assertEqual(counts['MN_ASOS'], 1)
        self.assertEqual(counts['MN_RWIS'], 0)
        self.assertEqual(counts['WISCONET'], 0)
        self.assertEqual(counts['MN_DCP'], 0)
        self.assertIn('MN_DCP', result['expectedNetworks'])
        # An empty but valid response differs from an actual failed download.
        self.assertEqual(next(s for s in result['sourceHealth'] if s['source']=='MN_RWIS'),
                         {'source': 'MN_RWIS', 'status': 'ok', 'reports': 0})
        self.assertEqual(next(s for s in result['sourceHealth'] if s['source']=='AWC METAR')['reports'], 0)

    def test_download_failure_is_recorded_even_when_fallback_reports_are_present(self):
        base = downloader(row(), row('ROAD', 'MN_RWIS'))
        def download(url):
            if '/request/rwis.py?' in url and 'network=MN_RWIS' in url:
                raise TimeoutError('archive unavailable')
            return base(url)
        with self.assertLogs('station_plots', level='ERROR'):
            result = stations.collect(download, NOW, airport_failed=True)
        checks = {s['source']: s for s in result['sourceHealth']}
        self.assertEqual(checks['MN_RWIS']['status'], 'failed')
        self.assertEqual(checks['AWC METAR']['status'], 'failed')
        self.assertEqual(next(r for r in result['coverage'] if r['network']=='MN_RWIS')['selected'], 1)

    def test_history_preserves_original_failures_while_late_network_counts_recover(self):
        initial = stations.collect(downloader(row()), NOW, airport_failed=True)
        base = downloader(row(utc_valid='2026-10-14T20:53:00Z'))
        def download(url):
            if '/request/rwis.py?' in url and 'network=MN_RWIS' in url:
                return archive(('MN001', '2026-10-14 19:40:00'))
            return base(url)
        later = stations.collect(download, NOW+timedelta(hours=1), initial, airport_rows=[])
        earlier = next(f for f in later['history'] if f['hour']==stations.iso(NOW))
        self.assertEqual(next(n for n in earlier['networkHealth'] if n['network']=='MN_RWIS')['selected'], 1)
        self.assertEqual(next(s for s in earlier['sourceHealth'] if s['source']=='AWC METAR')['status'], 'failed')
        self.assertEqual(next(s for s in later['history'][-1]['sourceHealth'] if s['source']=='AWC METAR')['status'], 'ok')
        public = stations.current(later, NOW+timedelta(hours=2))
        self.assertEqual(public['history'], later['history'])
        self.assertEqual(len(public['history']), 12)

    def test_awc_fallback_keeps_known_airport_network_when_state_metadata_feed_fails(self):
        first = stations.collect(downloader(row()), NOW)
        stamp = '2026-10-14T20:53:00Z'
        official = {'station': 'KMSP', 'time': stamp, 'lat': 44.9, 'lon': -93.3,
                    'tempF': 56.0, 'dewpointF': 40.0, 'wind': {'speedKnots': 10}, 'reportType': 'METAR'}
        base = downloader()
        def download(url):
            if url.endswith('=MN'):
                raise TimeoutError('state feed unavailable')
            return base(url)
        with self.assertLogs('station_plots', level='ERROR'):
            second = stations.collect(download, NOW+timedelta(hours=1), first, airport_rows=[official])
        self.assertEqual(second['stations'][0]['network'], 'MN_ASOS')
        self.assertEqual(next(n for n in second['history'][-1]['networkHealth'] if n['network']=='MN_ASOS')['selected'], 1)
        self.assertEqual(next(s for s in second['sourceHealth'] if s['source']=='MN')['status'], 'failed')

    def test_missing_individual_site_does_not_change_whole_network_presence(self):
        first = stations.collect(downloader(row(), row('ROAD1', 'MN_RWIS'), row('ROAD2', 'MN_RWIS')), NOW)
        second = stations.collect(downloader(row(utc_valid='2026-10-14T20:53:00Z'),
                                  row('ROAD1', 'MN_RWIS', utc_valid='2026-10-14T20:40:00Z')), NOW+timedelta(hours=1), first)
        self.assertEqual(next(n for n in second['history'][-1]['networkHealth'] if n['network']=='MN_RWIS')['selected'], 1)
        self.assertNotIn('missingStations', second)


if __name__=='__main__':
    unittest.main()
