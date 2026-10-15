from datetime import datetime, timedelta, timezone
import gzip
import json
import unittest
from unittest.mock import patch

import app as weather
import collector
from metar_clouds import reports, current, snapshot, collect, parse_reports
from test_realtime import MemoryStore

NOW=datetime(2026,10,10,2,tzinfo=timezone.utc)


def metar(station='KAAA',cloud='<sky_condition sky_cover="CLR"/>',stamp=None,kind='METAR',extra='',raw='METAR KAAA CLR'):
    stamp=stamp or NOW.isoformat()
    return f'<METAR><station_id>{station}</station_id><observation_time>{stamp}</observation_time><latitude>44.9</latitude><longitude>-93.4</longitude><metar_type>{kind}</metar_type><raw_text>{raw}</raw_text>{cloud}{extra}</METAR>'


def xml(*items):
    return ('<response><data>'+''.join(items)+'</data></response>').encode()


class CloudReportTests(unittest.TestCase):
    def setUp(self):
        weather._cache.clear()
        rapid=patch('app.get_rapid_reports',return_value=[]);rapid.start();self.addCleanup(rapid.stop)

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

    def test_uses_observation_time_and_excludes_future_old_or_non_us_stations(self):
        d=reports(xml(metar('KOK1',stamp=(NOW-timedelta(minutes=113)).isoformat()),
                      metar('KFUT',stamp=(NOW+timedelta(seconds=1)).isoformat()),
                      metar('KOLD',stamp=(NOW-timedelta(hours=2,seconds=1)).isoformat()),
                      metar('CYYZ').replace('<latitude>44.9</latitude>','<latitude>35</latitude>')),NOW)
        self.assertEqual([s['station'] for s in d['stations']],['KOK1'])
        self.assertTrue(d['stations'][0]['delayed'])

    def test_full_dataset_is_not_limited_to_four_hundred_reports(self):
        d=reports(xml(*(metar('K'+str(i).zfill(3)) for i in range(500))),NOW)
        self.assertEqual(len(d['stations']),500)

    def test_region_filters_both_new_and_retained_national_rows(self):
        regional=metar('KMSP',stamp=(NOW-timedelta(minutes=7)).isoformat())
        outside=metar('KSFO').replace('<latitude>44.9</latitude>','<latitude>37.6</latitude>')
        self.assertEqual([r['station'] for r in reports(xml(regional,outside),NOW)['stations']],['KMSP'])
        saved=snapshot(parse_reports(xml(regional),NOW),NOW)
        saved['history'][-1]['stations'].append({**saved['stations'][0],'station':'KSFO','lat':37.6,'lon':-122.4})
        self.assertTrue(all(r['station']!='KSFO' for h in current(saved,NOW)['history'] for r in h['stations']))

    def test_empty_or_invalid_collection_retains_previous_snapshot(self):
        store=MemoryStore();store.write_json('live/metar-clouds.json',{'saved':True});before=store.read('live/metar-clouds.json')
        with patch('app.download',return_value=xml()),self.assertRaises(ValueError):collector.collect_metar_clouds(store,NOW)
        self.assertEqual(store.read('live/metar-clouds.json'),before)

    def test_cold_public_app_reads_snapshot_without_upstream_collection(self):
        store=MemoryStore();store.write_json('live/metar-clouds.json',snapshot(parse_reports(xml(metar(stamp=(NOW-timedelta(minutes=7)).isoformat())),NOW),NOW))
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as fetch:
            response=weather.app.test_client().get('/api/metar-clouds')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['stations'][0]['station'],'KAAA')
            self.assertFalse(response.json['stale'])
            fetch.assert_not_called()


class HourlyCloudTests(unittest.TestCase):
    def setUp(self):
        weather._cache.clear()
        rapid=patch('app.get_rapid_reports',return_value=[]);rapid.start();self.addCleanup(rapid.stop)
    def rows(self, *items):return parse_reports(xml(*items), NOW)

    def report(self, minutes=7, **kwargs):
        return metar(stamp=(NOW-timedelta(minutes=minutes)).isoformat(), **kwargs)

    def test_ceiling_skips_scattered_and_selects_lowest_broken_or_overcast(self):
        cloud='<sky_condition sky_cover="OVC" cloud_base_ft_agl="7000"/><sky_condition sky_cover="SCT" cloud_base_ft_agl="2500"/><sky_condition sky_cover="BKN" cloud_base_ft_agl="6000"/>'
        row=snapshot(self.rows(self.report(cloud=cloud)),NOW)['stations'][0]
        self.assertTrue(row['hasCeiling'])
        self.assertEqual(row['mapLayer']['cover'],'BKN')
        self.assertEqual(row['mapLayer']['baseFtAGL'],6000)
        self.assertEqual([l['baseFtAGL'] for l in row['layers']],[2500,6000,7000])

    def test_few_scattered_and_clear_are_not_ceilings_and_unknown_height_stays_unknown(self):
        for cover in ['FEW','SCT','CLR','BKN','OVC']:
            with self.subTest(cover=cover):
                cloud=f'<sky_condition sky_cover="{cover}"'+(' cloud_base_ft_agl="2200"' if cover in ['FEW','SCT'] else '')+'/>'
                row=snapshot(self.rows(self.report(cloud=cloud)),NOW)['stations'][0]
                self.assertEqual(row['hasCeiling'],cover in ['BKN','OVC'])
                self.assertEqual(row['mapLayer']['cover'],cover)
                if cover in ['BKN','OVC']:
                    self.assertIsNone(row['mapLayer']['baseFtAGL'])
        row=snapshot(self.rows(self.report(cloud='',raw='METAR KAAA')),NOW)['stations'][0]
        self.assertIsNone(row['mapLayer'])
        self.assertFalse(row['hasCeiling'])

    def test_vertical_visibility_remains_a_distinct_indefinite_ceiling(self):
        row=snapshot(self.rows(self.report(cloud='<sky_condition sky_cover="OVX"/>',extra='<vert_vis_ft>300</vert_vis_ft>')),NOW)['stations'][0]
        self.assertTrue(row['hasCeiling'])
        self.assertEqual(row['mapLayer'],{'cover':'VV','baseFtAGL':300,'heightType':'verticalVisibility'})

    def test_kcfe_excluded_from_new_reports_and_already_saved_history(self):
        self.assertEqual([r['station'] for r in self.rows(self.report(station='KCFE'),self.report())],['KAAA'])
        old=snapshot(self.rows(self.report(),self.report(67)),NOW)
        for hour in old['history']:
            hour['stations'].extend({**row,'station':'KCFE'} for row in list(hour['stations']))
        filtered=current(old,NOW)
        self.assertTrue(all(row['station']!='KCFE' for hour in filtered['history'] for row in hour['stations']))
        urls=[]
        def fetch(url):
            urls.append(url)
            return xml(self.report(station='KCFE'),self.report())
        result=collect(fetch,NOW,old)
        self.assertTrue(all('KCFE' not in url for url in urls))
        self.assertEqual([row['station'] for row in result['stations']],['KAAA'])

    def test_public_api_filters_old_snapshot_and_derives_ceiling_without_recollection(self):
        layers=[{'cover':'SCT','baseFtAGL':2500,'heightType':'cloudBase'},
                {'cover':'OVC','baseFtAGL':7000,'heightType':'cloudBase'},
                {'cover':'BKN','baseFtAGL':6000,'heightType':'cloudBase'}]
        old=snapshot(self.rows(self.report()),NOW)
        row=old['history'][-1]['stations'][0]
        row['layers']=layers
        row.pop('mapLayer');row.pop('hasCeiling')
        old['history'][-1]['stations'].append({**row,'station':'KCFE'})
        store=MemoryStore();store.write_json('live/metar-clouds.json',old)
        weather._cache.clear()
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as fetch:
            response=weather.app.test_client().get('/api/metar-clouds')
        self.assertEqual(response.status_code,200)
        self.assertEqual([r['station'] for r in response.json['stations']],['KAAA'])
        self.assertEqual(response.json['stations'][0]['mapLayer']['baseFtAGL'],6000)
        fetch.assert_not_called()

    def test_exactly_twelve_hours_and_same_routine_rule_as_main_observations(self):
        items=[self.report(7+60*i) for i in range(13)]
        data=snapshot(self.rows(*items),NOW)
        self.assertEqual(len(data['history']),12)
        self.assertEqual(data['history'][0]['hour'],'2026-10-09T15:00:00Z')
        self.assertEqual(data['history'][-1]['hour'],'2026-10-10T02:00:00Z')
        self.assertTrue(all(len(h['stations'])==1 for h in data['history']))
        core=[{'icaoId':'KMSP','metarType':'METAR','obsTime':(NOW-timedelta(minutes=7+60*i)).timestamp()} for i in range(13)]
        self.assertEqual([h['hour'] for h in data['history']],list(reversed([h['hour'] for h in weather.observations(core,NOW)['history']])))

    def test_prefers_53_and_correction_receipt_excludes_speci_future_and_off_hour(self):
        items=[self.report(6,cloud='<sky_condition sky_cover="BKN" cloud_base_ft_agl="6000"/>'),
               self.report(7), self.report(7,cloud='<sky_condition sky_cover="OVC" cloud_base_ft_agl="9000"/>',extra='<receipt_time>2026-10-10T01:55:00Z</receipt_time>'),
               self.report(5,kind='SPECI'), self.report(7,raw='SPECI KAAA OVC001'),
               self.report(31,station='KOFF'),metar('KFUT',stamp=(NOW+timedelta(minutes=53)).isoformat())]
        data=snapshot(self.rows(*items),NOW)
        self.assertEqual([r['station'] for r in data['stations']],['KAAA'])
        self.assertEqual(data['stations'][0]['layers'][0]['baseFtAGL'],9000)

    def test_closest_minute_fallback_is_labeled_following_hour(self):
        data=snapshot(self.rows(self.report(10),self.report(5,cloud='<sky_condition sky_cover="SCT" cloud_base_ft_agl="3000"/>')),NOW)
        self.assertEqual(data['stations'][0]['time'],'2026-10-10T01:55:00Z')
        self.assertEqual(data['history'][-1]['hour'],'2026-10-10T02:00:00Z')

    def test_does_not_carry_forward_reports_into_missing_station_or_hour(self):
        data=snapshot(self.rows(self.report(7),self.report(67,station='KBBB')),NOW)
        self.assertEqual([r['station'] for r in data['stations']],['KAAA'])
        later=current(data,NOW+timedelta(hours=1))
        self.assertEqual(later['stations'],[])
        self.assertEqual([r['station'] for r in later['history'][-2]['stations']],['KAAA'])
        self.assertEqual(later['checkedAt'],data['checkedAt'])

    def test_rounded_hour_can_appear_ahead_of_clock_just_like_observations(self):
        now=NOW-timedelta(minutes=5)
        data=snapshot(parse_reports(xml(self.report()),now),now)
        self.assertEqual(data['history'][-1]['hour'],'2026-10-10T02:00:00Z')

    def test_empty_cloud_data_stays_unknown_instead_of_previous_clear(self):
        data=snapshot(self.rows(self.report(7),self.report(7,cloud='',raw='METAR KAAA',extra='<receipt_time>2026-10-10T01:55:00Z</receipt_time>')),NOW)
        self.assertEqual(data['stations'][0]['layers'],[])

    def test_one_bulk_pull_merges_saved_history_without_historical_requests(self):
        previous=snapshot(self.rows(*(self.report(7+60*i) for i in range(12))),NOW)
        urls=[]
        def fetch(url):
            urls.append(url)
            return xml(metar(stamp=(NOW+timedelta(minutes=53)).isoformat()))
        data=collect(fetch,NOW+timedelta(hours=1),previous)
        self.assertEqual(urls,['https://aviationweather.gov/data/cache/metars.cache.xml.gz'])
        self.assertEqual(len(data['history']),12)
        self.assertTrue(all(h['stations'] for h in data['history']))
        self.assertEqual(data['history'][-1]['hour'],'2026-10-10T03:00:00Z')
        self.assertEqual(data['collectionMode'],'shared-hourly-bulk')

    def test_bulk_speci_does_not_replace_a_saved_routine_report(self):
        previous=snapshot(self.rows(self.report()),NOW)
        data=collect(lambda url:xml(self.report(5,kind='SPECI')),NOW,previous)
        self.assertEqual(data['stations'][0]['time'],'2026-10-10T01:53:00Z')

    def test_empty_new_store_builds_hourly_history_without_extra_source_calls(self):
        data=collect(lambda url:xml(self.report()),NOW)
        self.assertEqual(len(data['history']),12)
        self.assertEqual(sum(bool(h['stations']) for h in data['history']),1)

    def test_failed_collection_preserves_canonical_snapshot(self):
        store=MemoryStore();store.write_json('live/metar-clouds.json',snapshot(self.rows(self.report()),NOW))
        before=store.read('live/metar-clouds.json')
        with patch('app.download',side_effect=TimeoutError()),self.assertRaises(TimeoutError):
            collector.collect_metar_clouds(store,NOW)
        self.assertEqual(store.read('live/metar-clouds.json'),before)

    def test_removed_alternate_routes_return_not_found(self):
        client=weather.app.test_client()
        self.assertEqual(client.get('/api/alternate-clouds').status_code,404)
        self.assertEqual(client.get('/api/alternate-clouds/frame/20261010015300/combined.png').status_code,404)


if __name__=='__main__':unittest.main()
