from datetime import timedelta
import json
import unittest
from unittest.mock import patch

import numpy as np

import app
import station_plots
import surface_analysis as surface
from test_realtime import MemoryStore
from test_station_plots import NOW


def site(index, lat, lon, temp=50, dew=40, speed=10, direction=0):
    return {"station": str(index), "stationKey": "TEST:"+str(index), "network": "TEST", "lat": lat, "lon": lon,
            "time": station_plots.iso(NOW-timedelta(minutes=20)), "tempF": temp, "dewpointF": dew,
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

    def test_archived_dot_recovers_40_after_current_feed_replaced_it(self):
        csv = b'station,obtime,longitude,latitude,tmpf,dwpf,sknt,drct\nMN001,2026-10-14 19:40:00,-93,45,50,40,5,270\nMN001,2026-10-14 20:00:00,-93,45,51,41,5,270\n'
        rows = station_plots.parse_rwis(csv, 'MN_RWIS', NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['time'], '2026-10-14T19:40:00Z')
        self.assertEqual(rows[0]['tempF'], 50)

    def test_prepared_assets_and_history_reference_and_public_allowlist(self):
        store=MemoryStore(); rows=sample()
        data={"hour": station_plots.iso(NOW), "stations": rows, "history": [{"hour": station_plots.iso(NOW), "stations": rows}]}
        result=surface.prepare(data, store)
        url=data['history'][0]['analysisUrl']
        filtered=station_plots.current(data, NOW)
        self.assertEqual(filtered['history'][-1]['analysisUrl'], url)
        app.prepared_image.cache_clear()
        with patch('app.get_store', return_value=store), patch('app.download') as upstream:
            client=app.app.test_client()
            response=client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/json')
            self.assertEqual(response.json['hour'], data['hour'])
            self.assertEqual(client.get(result['fields']['tempF']['imageUrl']).mimetype, 'image/png')
            self.assertEqual(client.get('/api/prepared/live/station-plots.json').status_code, 404)
            upstream.assert_not_called()
        app.prepared_image.cache_clear()


if __name__ == '__main__': unittest.main()
