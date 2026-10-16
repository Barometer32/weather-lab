from datetime import timedelta
import io
import json
import unittest
from unittest.mock import patch

import numpy as np

from PIL import Image

import collector
import app
import station_plots
import surface_analysis as surface
from test_support import MemoryStore
from datetime import datetime, timezone
NOW=datetime(2026,10,16,17,tzinfo=timezone.utc)


def site(index, lat, lon, temp=50, dew=40, speed=10, direction=0):
    return {"station": str(index), "stationKey": "TEST:"+str(index), "network": "TEST", "lat": lat, "lon": lon,
            "time": station_plots.iso(NOW-timedelta(minutes=7)), "tempF": temp, "dewpointF": dew,
            "wind": {"speedMph": speed, "direction": direction}}


def sample():
    return [site(i*5+j, 44.5+i*.15, -94+j*.2) for i in range(5) for j in range(5)]


class SurfaceTests(unittest.TestCase):
    def test_single_bad_temperature_excluded_without_changing_raw_or_other_fields(self):
        rows = sample(); rows[12]["tempF"] = 110
        surface.screen(rows)
        self.assertEqual(rows[12]["tempF"], 110)
        self.assertEqual(rows[12]["analysisQc"]["tempF"]["status"], "suspect")
        self.assertEqual(rows[12]["analysisQc"]["dewpointF"]["status"], "screened")
        *_, z, u, v, count = surface.grid(rows, "tempF", 121, 81)
        self.assertEqual(count, 24)
        self.assertTrue(np.isfinite(z).any())
        self.assertLessEqual(np.nanmax(z), 50.000001)

    def test_too_few_independent_neighbors_stays_unverified(self):
        rows = [site(i, 45+i*.00001, -93) for i in range(10)]
        surface.screen(rows)
        self.assertTrue(all(r["analysisQc"]["tempF"]["status"] == "unverified" for r in rows))
        self.assertFalse(np.isfinite(surface.grid(rows, "tempF")[2]).any())

    def test_weight_cap_normalization_and_bounded_values(self):
        weights = surface.capped_weights(np.array([[10000., 1, 1, 1], [10., 2, 1, 0], [.1, .2, .3, .4]]))
        np.testing.assert_allclose(weights.sum(axis=1), 1, atol=1e-7)
        self.assertTrue((weights >= 0).all()); self.assertLessEqual(weights.max(), .40000001)
        self.assertTrue(((weights*np.array([10, 20, 30, 40])).sum(axis=1) <= 40).all())

    def test_vector_winds_handle_north_wrap_and_sparse_mask(self):
        rows = sample()
        for i, row in enumerate(rows): row["wind"]["direction"] = 359 if i%2 else 1
        surface.screen(rows)
        _, _, z, u, v, _ = surface.grid(rows, "wind")
        good = np.isfinite(z)
        self.assertTrue(good.any()); self.assertTrue((v[good] < -9.9).all())
        self.assertLess(np.nanmax(np.abs(u)), .18)
        self.assertGreater(np.isnan(z).sum(), .9*z.size)

    def test_real_front_is_not_erased_as_a_single_sensor_outlier(self):
        rows = sample()
        for row in rows: row["tempF"] = 65 if row["lon"] > -93.5 else 45
        surface.screen(rows)
        self.assertTrue(all(r["analysisQc"]["tempF"]["status"] != "suspect" for r in rows))

    def test_reference_color_boundaries_and_transparent_missing_cells(self):
        z=np.array([[49.999, 50., 54.999, 55., np.nan]], dtype=float)
        # Constant columns produce flat color interiors after scalar refinement.
        z=np.repeat(z, 4, axis=1)
        image=Image.open(io.BytesIO(surface.image(z, surface.PALETTES["tempF"], banded=True)))
        for x, color in [(8, (153,255,0)), (24, (204,255,0)), (40, (204,255,0)), (56, (255,255,0))]:
            self.assertEqual(image.getpixel((x, 1)), (*color,255))
        self.assertEqual(image.getpixel((72,1))[3], 0)
        image=Image.open(io.BytesIO(surface.image(np.full((2,2),19.9),surface.PALETTES["dewpointF"],banded=True)))
        self.assertEqual(image.getpixel((2,2)),(0,153,255,255))
        image=Image.open(io.BytesIO(surface.image(np.full((2,2),20.),surface.PALETTES["dewpointF"],banded=True)))
        self.assertEqual(image.getpixel((2,2)),(0,204,255,255))

    def test_same_fahrenheit_value_has_identical_temperature_and_dewpoint_colors(self):
        self.assertEqual(surface.PALETTES['tempF'],surface.PALETTES['dewpointF'])
        for value in [-10,20,40,45,50,55,70,85]:
            grid=np.full((2,2),float(value))
            self.assertEqual(surface.image(grid,surface.PALETTES['tempF'],True),surface.image(grid,surface.PALETTES['dewpointF'],True))

    def test_wind_bands_are_five_mph_and_change_at_exact_boundary(self):
        levels=[level for level,_ in surface.PALETTES['wind']]
        self.assertTrue(all(b-a==5 for a,b in zip(levels,levels[1:])))
        before=Image.open(io.BytesIO(surface.image(np.full((2,2),4.999),surface.PALETTES['wind'],True)))
        after=Image.open(io.BytesIO(surface.image(np.full((2,2),5.),surface.PALETTES['wind'],True)))
        self.assertNotEqual(before.getpixel((2,2)),after.getpixel((2,2)))

    def test_changed_late_readings_get_new_immutable_assets_and_unchanged_history_is_reused(self):
        rows=sample();store=MemoryStore();hour=station_plots.iso(NOW)
        data={'hour':hour,'stations':rows,'history':[{'hour':hour,'stations':rows}]}
        surface.prepare_history(data,store);old=data['history'][0]['analysisUrl'];writes=len(store.writes)
        surface.prepare_history(data,store);self.assertEqual(len(store.writes),writes)
        rows.append(site('LATE',45,-93,51))
        surface.prepare_history(data,store);new=data['history'][0]['analysisUrl']
        self.assertNotEqual(old,new)
        self.assertIsNotNone(store.read(old.removeprefix('/api/prepared/')))
        self.assertIsNotNone(store.read(new.removeprefix('/api/prepared/')))

    def test_contour_intervals_are_five_degrees(self):
        lons=np.linspace(-95,-90,10); lats=np.linspace(42,47,10)
        z=np.tile(np.linspace(41,64,10),(10,1))
        features=surface.lines(lons,lats,z,5)
        self.assertEqual({f['properties']['value'] for f in features},{45,50,55,60})

    def test_builds_all_saved_hours_without_changing_observations_or_refetching(self):
        from copy import deepcopy
        rows=sample();old=deepcopy(rows)
        for row in old:row['time']=station_plots.iso(NOW-timedelta(hours=1,minutes=7))
        data={'hour':station_plots.iso(NOW),'checkedAt':station_plots.iso(NOW+timedelta(minutes=2)),
              'bounds':[[40,-100],[50,-85]],'stations':rows,'history':[
                  {'hour':station_plots.iso(NOW-timedelta(hours=1)),'stations':old},
                  {'hour':station_plots.iso(NOW),'stations':rows}]}
        original=deepcopy(data);store=MemoryStore()
        with patch('app.download') as upstream:result=surface.prepare_maps(data,store)
        upstream.assert_not_called();self.assertEqual(data,original)
        self.assertEqual(result['hours'],2)
        saved=store.read_json('live/maps.json')
        self.assertEqual(saved['checkedAt'],data['checkedAt'])
        self.assertTrue(all('/'+surface.VERSION+'/' in f['analysisUrl'] for f in saved['history']))
        writes=len(store.writes)
        surface.prepare_maps(data,store);self.assertEqual(len(store.writes),writes)
        previous=saved['history'][0]['analysisUrl']
        data['stations'][12]['tempF']=51
        surface.prepare_maps(data,store)
        updated=store.read_json('live/maps.json')
        self.assertEqual(updated['history'][0]['analysisUrl'],previous)
        self.assertNotEqual(updated['history'][1]['analysisUrl'],saved['history'][1]['analysisUrl'])
        data['history'][0]['stations']=[]
        surface.prepare_maps(data,store)
        self.assertNotIn('analysisUrl',store.read_json('live/maps.json')['history'][0])

    def test_prepared_map_routes_only_read_allowed_saved_assets(self):
        store=MemoryStore();rows=sample();hour=station_plots.iso(NOW)
        data={'hour':hour,'stations':rows,'checkedAt':station_plots.iso(NOW+timedelta(minutes=2)),
              'bounds':[[40,-100],[50,-85]],'history':[{'hour':hour,'stations':rows}]}
        surface.prepare_maps(data,store);saved=store.read_json('live/maps.json')
        app._cache.clear();app.prepared_image.cache_clear()
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW+timedelta(minutes=3)),patch('app.download') as upstream:
            client=app.app.test_client();response=client.get('/api/maps')
            self.assertEqual(response.status_code,200)
            url=response.json['history'][0]['analysisUrl']
            manifest=client.get(url)
            self.assertEqual(manifest.status_code,200)
            self.assertEqual(manifest.mimetype,'application/json')
            self.assertEqual(client.get(manifest.json['fields']['wind']['imageUrl']).mimetype,'image/png')
            self.assertEqual(client.get('/api/prepared/live/maps.json').status_code,404)
            self.assertEqual(client.get('/api/prepared/analysis/metar-maps-v1/../../live/maps.json').status_code,404)
            upstream.assert_not_called()
        app._cache.clear();app.prepared_image.cache_clear()

    def test_failed_analysis_retains_observations_and_previous_map_index(self):
        from copy import deepcopy
        rows=sample();hour=station_plots.iso(NOW)
        observations={'hour':hour,'stations':rows,'checkedAt':hour,'bounds':[[40,-100],[50,-85]],
                      'history':[{'hour':hour,'stations':rows}]}
        store=MemoryStore();store.write_json('live/station-plots.json',observations)
        store.write_json('live/maps.json',{'version':'previous','history':[]})
        before=deepcopy(store.objects)
        with patch('surface_analysis.grid',side_effect=ValueError('fixture failure')):
            result=collector.prepare_maps(store,observations)
        self.assertIn('delayed',result['status']);self.assertEqual(store.objects,before)


if __name__ == '__main__':unittest.main()
