from datetime import datetime, timedelta, timezone
import gzip
import json
import unittest
from unittest.mock import patch

import app as weather
import collector
from metar_clouds import reports, current
from alternate_clouds import parse_loop, page_url
from test_realtime import MemoryStore

NOW=datetime(2026,10,10,2,tzinfo=timezone.utc)


def metar(station='KAAA',cloud='<sky_condition sky_cover="CLR"/>',stamp=None,kind='METAR',extra='',raw='METAR KAAA CLR'):
    stamp=stamp or NOW.isoformat()
    return f'<METAR><station_id>{station}</station_id><observation_time>{stamp}</observation_time><latitude>44.9</latitude><longitude>-93.4</longitude><metar_type>{kind}</metar_type><raw_text>{raw}</raw_text>{cloud}{extra}</METAR>'


def xml(*items):
    return ('<response><data>'+''.join(items)+'</data></response>').encode()


class CloudReportTests(unittest.TestCase):
    def setUp(self):weather._cache.clear()

    def test_preserves_all_layers_and_heights_above_twelve_thousand(self):
        cloud='<sky_condition sky_cover="FEW" cloud_base_ft_agl="3500"/><sky_condition sky_cover="BKN" cloud_base_ft_agl="12000"/><sky_condition sky_cover="BKN" cloud_base_ft_agl="25000"/>'
        d=reports(gzip.compress(xml(metar(cloud=cloud))),NOW)
        self.assertEqual([l['baseFtAGL'] for l in d['stations'][0]['layers']],[3500,12000,25000])
        self.assertNotIn('temperature',d['stations'][0])

    def test_distinguishes_clear_sky_missing_height_missing_clouds_and_vertical_visibility(self):
        d=reports(xml(metar('KCLR'),metar('KSKC','<sky_condition sky_cover="SKC"/>'),
                      metar('KUNK','',raw='METAR KUNK'),metar('KBKN','<sky_condition sky_cover="BKN" cloud_base_ft_agl="-9999"/>'),
                      metar('KVIS','<sky_condition sky_cover="OVX" cloud_base_ft_agl="0"/>',extra='<vert_vis_ft>300</vert_vis_ft>')),NOW)
        rows={r['station']:r for r in d['stations']}
        self.assertEqual(rows['KUNK']['layers'],[])
        self.assertFalse(rows['KUNK']['cloudDataAvailable'])
        self.assertIsNone(rows['KBKN']['layers'][0]['baseFtAGL'])
        self.assertEqual(rows['KVIS']['layers'][0],{'cover':'VV','baseFtAGL':300,'heightType':'verticalVisibility'})
        self.assertEqual(rows['KCLR']['layers'][0]['cover'],'CLR')
        self.assertEqual(rows['KSKC']['layers'][0]['cover'],'SKC')

    def test_latest_special_and_missing_cloud_report_replace_older_clear(self):
        d=reports(xml(metar(stamp=(NOW-timedelta(minutes=30)).isoformat()),metar(cloud='',kind='SPECI',raw='SPECI KAAA')),NOW)
        self.assertEqual(len(d['stations']),1)
        self.assertEqual(d['stations'][0]['reportType'],'SPECI')
        self.assertEqual(d['stations'][0]['layers'],[])

    def test_uses_observation_time_not_rounded_report_hour_and_excludes_future_old_or_outside_region(self):
        d=reports(xml(metar('KOK1',stamp=(NOW-timedelta(minutes=113)).isoformat()),
                      metar('KFUT',stamp=(NOW+timedelta(seconds=1)).isoformat()),
                      metar('KOLD',stamp=(NOW-timedelta(hours=2,seconds=1)).isoformat()),
                      metar('KOUT').replace('<latitude>44.9</latitude>','<latitude>35</latitude>')),NOW)
        self.assertEqual([s['station'] for s in d['stations']],['KOK1'])
        self.assertTrue(d['stations'][0]['delayed'])
        self.assertEqual(current(d,NOW+timedelta(minutes=8))['stations'],[])

    def test_full_dataset_is_not_limited_to_four_hundred_reports(self):
        d=reports(xml(*(metar('K'+str(i).zfill(3)) for i in range(500))),NOW)
        self.assertEqual(len(d['stations']),500)

    def test_empty_or_invalid_collection_retains_previous_snapshot(self):
        store=MemoryStore();store.write_json('live/metar-clouds.json',{'saved':True});before=store.read('live/metar-clouds.json')
        with patch('app.download',return_value=xml()),self.assertRaises(ValueError):collector.collect_metar_clouds(store,NOW)
        self.assertEqual(store.read('live/metar-clouds.json'),before)

    def test_cold_public_app_reads_snapshot_without_upstream_collection(self):
        store=MemoryStore();store.write_json('live/metar-clouds.json',reports(xml(metar()),NOW))
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as fetch:
            response=weather.app.test_client().get('/api/metar-clouds')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['stations'][0]['station'],'KAAA')
            self.assertFalse(response.json['stale'])
            fetch.assert_not_called()


class AlternateCloudTests(unittest.TestCase):
    def url(self,stamp,band='DayNightCloudMicroCombo'):
        return f'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/umv/{band}/{stamp}_GOES19-ABI-umv-{band}-1200x1200.jpg'

    def test_sorted_unique_two_hour_window_and_correct_product_only(self):
        stamps=[NOW-timedelta(hours=2),NOW,NOW-timedelta(hours=2,minutes=1),NOW+timedelta(minutes=1)]
        urls=[self.url(t.strftime('%Y%j%H%M')) for t in stamps]
        html=' '.join(urls+urls[:1]+[self.url(stamps[1].strftime('%Y%j%H%M'),'GEOCOLOR')])
        d=parse_loop(html,'combo',NOW)
        self.assertEqual(len(d['frames']),2)
        self.assertEqual(d['frames'][0]['time'],'2026-10-10T00:00:00Z')
        self.assertEqual(d['width'],1200)
        self.assertTrue(all('DayNightCloudMicroCombo' in f['url'] for f in d['frames']))

    def test_other_host_and_sector_and_bad_julian_day_do_not_enter_loop(self):
        valid=self.url(NOW.strftime('%Y%j%H%M'))
        html=' '.join([valid,valid.replace('cdn.star.nesdis.noaa.gov','example.com'),valid.replace('/umv/','/cgl/'),self.url('20263670000')])
        self.assertEqual(len(parse_loop(html,'combo',NOW)['frames']),1)

    def test_invalid_product_and_empty_feed_are_reported(self):
        with self.assertRaises(ValueError):page_url('../evil')
        with self.assertRaises(ValueError):parse_loop('','infrared',NOW)
        with patch('app.download') as fetch:
            self.assertEqual(weather.app.test_client().get('/api/alternate-clouds/unknown').status_code,404)
            fetch.assert_not_called()

    def test_noaa_route_uses_independent_cache_and_never_cod_or_bucket(self):
        weather._cache.clear();html=self.url(NOW.strftime('%Y%j%H%M'))
        with patch('app.utcnow',return_value=NOW),patch('app.download',return_value=html.encode()) as fetch,patch('app.get_store') as bucket:
            client=weather.app.test_client()
            self.assertEqual(client.get('/api/alternate-clouds/combo').status_code,200)
            self.assertEqual(client.get('/api/alternate-clouds/combo').status_code,200)
            self.assertEqual(fetch.call_count,1)
            self.assertIn('star.nesdis.noaa.gov',fetch.call_args.args[0])
            bucket.assert_not_called()


if __name__=='__main__':unittest.main()
