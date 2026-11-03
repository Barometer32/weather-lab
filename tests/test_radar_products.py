"""Higher-cut selection and precipitation semantics must stay separate."""
from datetime import timedelta
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch
import numpy as np

import app as weather
import native_radar as radar
import radar_precipitation as precip
from test_native_radar import sweep, NOW
from test_realtime import MemoryStore


class RadarProductsTests(unittest.TestCase):
    def test_every_reflectivity_cut_is_kept_but_duplicate_split_cut_is_not(self):
        angles = [.5, .5, .9, .9, 1.3, 1.8, 4, 19.5]
        rows = radar.Radials()
        rows.cuts = {}
        for number, angle in enumerate(angles, 1):
            part = sweep(angle=angle, minute=40+number)
            for radial in part:
                radial.header.el_num = number
            rows.extend(part)
            rows.cuts[str(number)] = {"angle": angle, "waveform": "Contig. Doppler with Ambiguity Res." if number in (2, 4) else "Contiguous Surveillance" if angle < 1.4 else "Staggered Pulse Pair"}
        items, pending = radar.consume(rows, "KMPX", all_tilts=True)
        self.assertIsNone(pending)
        self.assertEqual([meta["nominalElevation"] for meta, _ in items], [.5, .9, 1.3, 1.8, 4, 19.5])
        self.assertEqual(radar.reflectivity_product(19.5), "ref-19p5")

    def test_public_api_sends_only_selected_loop_and_rejects_unknown_products(self):
        store = MemoryStore()
        frames = [{"id": str(i), "time": radar.iso(NOW-timedelta(minutes=10-i)), "elevationDegrees": angle}
                  for i, angle in enumerate([.5, 1.8, 19.5])]
        data = radar.manifest(frames, NOW, "KMPX", [])
        data["products"] = {radar.reflectivity_product(f["elevationDegrees"]): {
            "label": str(f["elevationDegrees"]), "elevationDegrees": f["elevationDegrees"], "frames": [f]} for f in frames}
        store.write_json("live/radar-all-KMPX.json", data)
        store.write_json("live/radar-storm-total-KMPX.json", {**data, "frames": [frames[1]], "units": "inches", "product": "Storm-total precipitation"})
        weather._cache.clear()
        with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=NOW), patch("app.download") as upstream:
            client = weather.app.test_client()
            default = client.get('/api/radar').json
            self.assertEqual([f['id'] for f in default['frames']], ['0'])
            self.assertTrue(all('frames' not in p for p in default['products']))
            upper = client.get('/api/radar?product=ref-19p5').json
            self.assertEqual([f['id'] for f in upper['frames']], ['2'])
            self.assertEqual(upper['elevationDegrees'], 19.5)
            self.assertEqual(client.get('/api/radar?product=storm-total').json['units'], 'inches')
            self.assertEqual(client.get('/api/radar?product=anything').status_code, 400)
            upstream.assert_not_called()

    def test_precipitation_scale_flags_and_accumulation_start_are_preserved(self):
        field = {"data": np.full((360, 4), 100, dtype=np.uint8), "start_az": np.arange(360),
                 "end_az": np.arange(360)+1, "gate_scale": .25, "first": 0}
        # Simulate an automatic scale of .03 inches per code (max > 5.1 inches).
        def mapped(values):
            result = values.astype(float)*3;result[0] = np.nan;return result
        product = Obj(siteID='MPX', header=Obj(code=172), sym_block=[[field]], lat=44.849, lon=-93.565,
                      map_data=mapped, metadata={"rainfall_end": NOW, "rainfall_begin": NOW-timedelta(days=2), "vol_time": NOW})
        with patch('metpy.io.Level3File', return_value=product):
            meta, binary = precip.decode_precipitation(b'fixture', 'KMPX')
        _, codes = radar.unpack(binary)
        self.assertEqual(meta['codeValues'][100], 3)
        self.assertIsNone(meta['codeValues'][0])
        self.assertEqual(meta['accumulationStart'], radar.iso(NOW-timedelta(days=2)))
        self.assertEqual(meta['firstGateMeters'], 125)
        self.assertTrue(meta['groundRange'])
        self.assertTrue((codes == 100).all())
        product.header.code = 170
        with patch('metpy.io.Level3File', return_value=product), self.assertRaises(ValueError):
            precip.decode_precipitation(b'wrong', 'KMPX')

    def test_failed_precipitation_keeps_last_good_manifest(self):
        store = MemoryStore()
        store.write_json('live/radar-storm-total-KMPX.json', {'checkedAt': radar.iso(NOW), 'frames': []})
        before = dict(store.objects)
        with patch('radar_precipitation.objects', side_effect=TimeoutError), self.assertRaises(TimeoutError):
            precip.collect(store, NOW)
        self.assertEqual(store.objects, before)


if __name__ == '__main__':
    unittest.main()
