from datetime import datetime, timedelta, timezone
import gzip
import json
import unittest
from unittest.mock import patch

import app as weather
import collector
from metar_clouds import reports, current
import alternate_clouds as clouds
import numpy as np
from io import BytesIO
from PIL import Image
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
    def setUp(self):
        weather._cache.clear();clouds.FRAME_CACHE.clear()

    def stamp(self,t=NOW):return t.strftime('%Y%j%H%M%S')+'0'

    def row(self,t=NOW):
        return {'id':self.stamp(t),'time':clouds.iso(t),'keys':{'mask':'mask.nc','height':'height.nc','optical':'optical.nc'}}

    def blob(self,field,value,q=0):
        from netCDF4 import Dataset
        d=Dataset('test','w',memory=100000)
        d.createDimension('y',16);d.createDimension('x',24)
        x=d.createVariable('x','f4',('x',));x[:]=np.linspace(-.12,.02,24)
        y=d.createVariable('y','f4',('y',));y[:]=np.linspace(.14,.02,16)
        p=d.createVariable('goes_imager_projection','i4')
        for a,v in {'perspective_point_height':35786023.,'longitude_of_projection_origin':-75.,'semi_major_axis':6378137.,'semi_minor_axis':6356752.31414,'sweep_angle_axis':'x'}.items():setattr(p,a,v)
        v=d.createVariable(field,'f4',('y','x'),fill_value=-9999);v[:]=value
        qv=d.createVariable('DQF','i4',('y','x'));qv[:]=q
        return bytes(d.close())

    def pixel(self,blob):return np.asarray(Image.open(BytesIO(blob)))[0,0]

    def test_utc_identifier_and_recent_window_and_product_validation(self):
        self.assertEqual(clouds.stamp_time(self.stamp()),NOW)
        with self.assertRaises(ValueError):clouds.stamp_time('20263670000000')
        rows=[self.row(NOW-timedelta(hours=2)),self.row(),self.row(NOW+timedelta(seconds=1)),self.row(NOW-timedelta(hours=2,seconds=1))]
        d=clouds.manifest(rows,NOW)
        self.assertEqual(len(d['frames']),2);self.assertEqual(d['bounds'],clouds.BOUNDS)
        self.assertTrue(all('/combined.png?v=' in f['url'] for f in d['frames']))
        with patch('app.utcnow',return_value=NOW),patch('alternate_clouds.scans') as upstream:
            for path in ['/api/alternate-clouds/frame/invalid/combined.png','/api/alternate-clouds/frame/'+self.stamp()+'/evil.png','/api/alternate-clouds/frame/'+self.stamp(NOW+timedelta(seconds=1))+'/combined.png']:
                self.assertEqual(weather.app.test_client().get(path).status_code,404)
            upstream.assert_not_called()

    def test_exact_scan_pairing_across_midnight_and_optional_fields(self):
        def listing(feed,hour,now):
            t=NOW-timedelta(minutes=5)
            return {self.stamp(t):feed+'.nc'} if hour.hour==1 and feed!='ABI-L2-CODC' else {}
        with patch('alternate_clouds.list_hour',side_effect=listing) as read:
            rows=clouds.scans(NOW)
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['keys']['optical'])
        self.assertEqual(rows[0]['keys']['height'],'ABI-L2-ACHAC.nc');self.assertEqual(read.call_count,9)

    def test_height_classes_clear_missing_and_unknown_height_remain_distinct(self):
        mask=np.array([[3,3,3,0,3,3]]);ok=np.array([[1,1,1,1,1,0]],dtype=bool)
        heights=np.array([[1000,4000,9000,0,0,0]]);h_ok=np.array([[1,1,1,0,0,0]],dtype=bool)
        images=clouds.palette(mask,ok,heights,h_ok,np.zeros(mask.shape),np.zeros(mask.shape,dtype=bool))
        a=images['combined'];self.assertEqual(list(a[0,0,:3]),[56,118,188]);self.assertEqual(list(a[0,1,:3]),[20,150,143]);self.assertEqual(list(a[0,2,:3]),[129,85,179])
        self.assertEqual(a[0,3,3],0);self.assertGreater(a[0,4,3],0)

    def test_real_netcdf_projection_sampling_and_source_quality_flags(self):
        sources={'mask':self.blob('ACM',3),'height':self.blob('HT',9000),'optical':self.blob('COD',30,q=2)}
        images=clouds.render(sources)
        self.assertEqual(list(self.pixel(images['combined'])[:3]),[129,85,179])
        self.assertEqual(list(self.pixel(images['optical'])[:3]),[16,66,115])
        sources['height']=self.blob('HT',9000,q=1);sources['optical']=self.blob('COD',30,q=1)
        images=clouds.render(sources)
        self.assertEqual(list(self.pixel(images['combined'])[:3]),[138,146,153])
        self.assertNotEqual(list(self.pixel(images['optical'])[:3]),[16,66,115])
        sources['mask']=self.blob('ACM',3,q=1);images=clouds.render(sources)
        self.assertLess(self.pixel(images['combined'])[3],100)

    def test_north_up_mercator_rows_and_west_to_east_columns(self):
        lon,lat=clouds.output_grid()
        self.assertGreater(lat[0,0],lat[-1,0]);self.assertGreater(lon[0,-1],lon[0,0])
        merc=np.log(np.tan(np.pi/4+np.radians(lat[:,0])/2))
        np.testing.assert_allclose(np.diff(merc),np.diff(merc)[0],rtol=1e-9)
        self.assertEqual(lon.shape,(576,1024))

    def test_optional_product_failure_keeps_cloud_mask(self):
        images=clouds.render({'mask':self.blob('ACM',3),'height':b'bad file'})
        self.assertEqual(list(self.pixel(images['combined'])[:3]),[138,146,153])
        with self.assertRaises(Exception):clouds.render({'mask':b'bad file'})

    def test_output_cache_reuses_scan_for_both_views_and_prunes_old(self):
        old=self.stamp(NOW-timedelta(hours=3));clouds.FRAME_CACHE[old]={'combined':b'old'}
        with patch('alternate_clouds.fetch',return_value=b'raw') as fetch,patch('alternate_clouds.render',return_value={'combined':b'height','optical':b'depth'}) as render:
            self.assertEqual(clouds.frame(self.row(),'combined',NOW),b'height')
            self.assertEqual(clouds.frame(self.row(),'optical',NOW),b'depth')
        self.assertEqual(fetch.call_count,3);self.assertEqual(render.call_count,1);self.assertNotIn(old,clouds.FRAME_CACHE)

    def test_public_routes_use_only_independent_noaa_feed(self):
        with patch('app.utcnow',return_value=NOW),patch('alternate_clouds.scans',return_value=[self.row()]) as scans,patch('alternate_clouds.frame',return_value=b'PNG') as render,patch('app.get_store') as bucket,patch('app.download') as cod:
            c=weather.app.test_client();self.assertEqual(c.get('/api/alternate-clouds').status_code,200)
            r=c.get('/api/alternate-clouds/frame/'+self.stamp()+'/combined.png')
            self.assertEqual(r.status_code,200);self.assertEqual(r.mimetype,'image/png');self.assertEqual(scans.call_count,1)
            bucket.assert_not_called();cod.assert_not_called();render.assert_called_once()

    def test_late_optional_fields_change_urls_and_replace_provisional_output(self):
        provisional=self.row();provisional['keys']['height']=None
        complete=self.row()
        self.assertNotEqual(clouds.manifest([provisional],NOW)['frames'][0]['url'],clouds.manifest([complete],NOW)['frames'][0]['url'])
        with patch('alternate_clouds.fetch',return_value=b'raw'),patch('alternate_clouds.render',side_effect=[{'combined':b'gray'},{'combined':b'height'}]) as render:
            self.assertEqual(clouds.frame(provisional,'combined',NOW),b'gray')
            self.assertEqual(clouds.frame(complete,'combined',NOW),b'height')
            self.assertEqual(render.call_count,2)
        with patch('app.utcnow',return_value=NOW),patch('alternate_clouds.scans',return_value=[complete]),patch('alternate_clouds.frame') as image:
            old=clouds.revision(provisional)
            self.assertEqual(weather.app.test_client().get('/api/alternate-clouds/frame/'+self.stamp()+'/combined.png?v='+old).status_code,409)
            image.assert_not_called()

    def test_failed_download_is_not_cached_as_permanent_missing_data(self):
        def read(url):
            if url.endswith('height.nc'):raise TimeoutError()
            return b'raw'
        with patch('alternate_clouds.fetch',side_effect=read),patch('alternate_clouds.render') as render:
            with self.assertRaises(TimeoutError):clouds.frame(self.row(),'combined',NOW)
            render.assert_not_called();self.assertEqual(clouds.FRAME_CACHE,{})


if __name__=='__main__':unittest.main()
