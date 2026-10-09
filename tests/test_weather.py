import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image
from app import hourly_snapshot, observations, recolor_and_project, wind_mean, scans_in_window, get_scans, _cache, app

UTC = timezone.utc
HOUR = datetime(2026, 10, 9, 1, tzinfo=UTC)


def report(station="KFCM", offset=-7, **kwargs):
    return {"icaoId": station, "obsTime": (HOUR + timedelta(minutes=offset)).timestamp(),
            "metarType": "METAR", "temp": 10, "dewp": 5, "wspd": 5, "wdir": 350, **kwargs}


class WeatherTests(unittest.TestCase):
    def test_equal_station_weights_and_conversion(self):
        rows = [report("KFCM", temp=10), report("KMSP", temp=20), report("KMIC", temp=30)]
        x = hourly_snapshot(rows, HOUR, HOUR + timedelta(minutes=15))
        self.assertEqual(x["tempF"], 68)
        self.assertEqual(x["tempCount"], 3)

    def test_routine_53_wins_over_other_minutes_and_after_hour(self):
        rows = [report(offset=-7, temp=10), report(offset=-1, temp=30),
                report(offset=4, temp=20), report("KMIC", offset=-16)]
        x = hourly_snapshot(rows, HOUR, HOUR + timedelta(minutes=15))
        self.assertEqual(x["tempF"], 50)
        self.assertEqual(x["count"], 1)

    def test_speci_never_replaces_routine_report(self):
        rows = [report(temp=10), report(offset=-1, temp=30, metarType="SPECI")]
        self.assertEqual(hourly_snapshot(rows,HOUR,HOUR)["tempF"],50)
        self.assertEqual(hourly_snapshot([report(metarType="SPECI")],HOUR,HOUR)["count"],0)
        self.assertEqual(hourly_snapshot([report(rawOb="SPECI KFCM 090053Z")],HOUR,HOUR)["count"],0)

    def test_small_routine_timing_variation_is_allowed(self):
        rows = [report(offset=-8), report("KMSP", offset=-10), report("KMIC", offset=-11)]
        self.assertEqual(hourly_snapshot(rows,HOUR,HOUR)["count"],2)

    def test_never_use_future_observation(self):
        x = hourly_snapshot([report()], HOUR, HOUR - timedelta(minutes=8))
        self.assertEqual(x["count"], 0)

    def test_missing_and_invalid_are_excluded(self):
        rows = [report(temp=None), report("KMSP", temp=-999, dewp=None), report("KMIC", temp=10)]
        x = hourly_snapshot(rows, HOUR, HOUR)
        self.assertEqual(x["tempCount"], 1)
        self.assertEqual(x["tempF"], 50)
        self.assertEqual(x["dewpointCount"], 2)

    def test_quality_pass_requires_all_three_complete_stations(self):
        rows = [report(station) for station in ["KFCM", "KMSP", "KMIC"]]
        x = hourly_snapshot(rows, HOUR, HOUR)
        self.assertTrue(x["qa"]["allStationsUsed"])
        self.assertEqual(x["qa"]["stationsUsed"], 3)
        self.assertEqual(x["qa"]["status"], "passed")
        partial = hourly_snapshot(rows[:2], HOUR, HOUR)
        self.assertFalse(partial["qa"]["allStationsUsed"])
        self.assertEqual(partial["qa"]["stationsUsed"], 2)
        self.assertEqual(partial["tempF"], 50)

    def test_impossible_dewpoint_is_excluded_and_qa_fails(self):
        rows = [report("KFCM", dewp=15), report("KMSP"), report("KMIC")]
        x = hourly_snapshot(rows, HOUR, HOUR)
        self.assertEqual(x["dewpointCount"], 2)
        self.assertEqual(x["dewpointF"], 41)
        self.assertEqual(x["qa"]["stationsUsed"], 2)
        self.assertEqual(x["qa"]["checks"]["dewpoint"], 2)
        self.assertFalse(x["qa"]["allStationsUsed"])

    def test_dewpoint_rounding_tolerance(self):
        x = hourly_snapshot([report(dewp=10.5)], HOUR, HOUR)
        self.assertEqual(x["dewpointCount"], 1)

    def test_variable_and_calm_are_valid_but_missing_direction_is_not(self):
        rows = [report("KFCM", wdir="VRB"), report("KMSP", wspd=0, wdir=None), report("KMIC")]
        self.assertTrue(hourly_snapshot(rows, HOUR, HOUR)["qa"]["allStationsUsed"])
        rows[2]["wdir"] = None
        self.assertEqual(hourly_snapshot(rows, HOUR, HOUR)["qa"]["checks"]["wind"], 2)

    def test_boolean_field_is_not_a_number(self):
        x = hourly_snapshot([report(temp=True)], HOUR, HOUR)
        self.assertIsNone(x["tempF"])
        self.assertEqual(x["qa"]["checks"]["temperature"], 0)

    def test_circular_wind_crosses_north(self):
        x = wind_mean([report(wdir=350), report(wdir=10)])
        self.assertEqual(x["direction"] % 360, 0)

    def test_variable_and_calm_wind(self):
        self.assertIsNone(wind_mean([report(wdir="VRB")])["direction"])
        self.assertIsNone(wind_mean([report(wspd=0)])["direction"])

    def test_routine_report_is_shown_on_receipt_with_following_hour_label(self):
        before = observations([report()], HOUR - timedelta(minutes=8))["current"]["hour"]
        after = observations([report()], HOUR - timedelta(minutes=6))["current"]
        self.assertEqual(before, "2026-10-09T00:00:00Z")
        self.assertEqual(after["hour"], "2026-10-09T01:00:00Z")
        self.assertEqual(after["stations"][0]["observedAt"], "2026-10-09T00:53:00Z")
        self.assertEqual(after["tempF"],50)

    def test_missing_current_routine_does_not_reuse_an_old_hour(self):
        x = observations([report()], HOUR + timedelta(hours=1))["current"]
        self.assertEqual(x["hour"], "2026-10-09T02:00:00Z")
        self.assertEqual(x["count"],0)
        self.assertFalse(x["qa"]["allStationsUsed"])

    def test_previous_days_2353_is_labeled_midnight(self):
        midnight = HOUR.replace(hour=0)
        rows = [report(obsTime=(midnight - timedelta(minutes=7)).timestamp())]
        self.assertEqual(hourly_snapshot(rows,midnight,midnight)["count"],1)

    def test_two_hour_radar_window_retains_every_available_scan(self):
        rows = [{"ts": (HOUR - timedelta(minutes=i)).isoformat()} for i in range(0, 124, 2)]
        rows += [{"ts": (HOUR + timedelta(minutes=1)).isoformat()}, rows[1], {"ts":"invalid"}]
        scans = scans_in_window(rows,HOUR)
        self.assertEqual(len(scans),61)
        self.assertEqual(scans[0]["time"],"2026-10-08T23:00:00Z")
        self.assertEqual(scans[-1]["time"],"2026-10-09T01:00:00Z")

    def test_radar_query_and_cached_frames_respect_two_hour_window(self):
        _cache.pop("radar-scans",None)
        rows = [{"ts": (HOUR - timedelta(minutes=i)).isoformat()} for i in range(0, 124, 2)]
        with patch("app.download",return_value=json.dumps({"scans":rows}).encode()) as fetch:
            self.assertEqual(len(get_scans(HOUR)),61)
            query = parse_qs(urlparse(fetch.call_args.args[0]).query)
            self.assertEqual(query["start"],["2026-10-08T23:00Z"])
            self.assertEqual(query["end"],["2026-10-09T01:00Z"])
            self.assertEqual(query["product"],["N0B"])
            later = get_scans(HOUR + timedelta(minutes=3))
            self.assertEqual(later[0]["time"],"2026-10-08T23:04:00Z")
            self.assertEqual(fetch.call_count,1)
        _cache.pop("radar-scans",None)

    def test_correction_wins_at_same_timestamp(self):
        rows = [report(temp=10, receiptTime="2026-10-09T00:55:00Z"),
                report(temp=20, receiptTime="2026-10-09T00:56:00Z")]
        self.assertEqual(hourly_snapshot(rows,HOUR,HOUR)["tempF"],68)

    def test_indexed_radar_bins_and_georeferencing(self):
        # Codes 85/86 straddle the 9.5/10 dBZ cutoff. Missing codes stay transparent.
        data = np.tile(np.array([0,1,85,86,106,126,146,166,255],dtype="uint8"),(9,1))
        image = Image.fromarray(data).convert("P"); b = io.BytesIO();image.save(b,format="PNG")
        png,bounds = recolor_and_project(b.getvalue(),b"0.01\n0\n0\n-0.01\n-93\n45\n", smooth=False)
        out = np.asarray(Image.open(io.BytesIO(png)))
        self.assertTrue((out[0,:3,3] == 0).all())
        self.assertEqual(tuple(out[0,3]),(76,175,99,220))
        self.assertEqual(tuple(out[0,7]),(200,44,85,220))
        self.assertEqual(tuple(out[0,8]),(138,63,160,220))
        self.assertAlmostEqual(bounds[1][0],45.005)
        self.assertAlmostEqual(bounds[0][1],-93.005)

    def test_eight_radar_bands_classify_both_sides_of_every_boundary(self):
        codes = [85,86,105,106,115,116,125,126,141,142,153,154,165,166,179,180,255]
        data = np.tile(np.array(codes,dtype="uint8"),(17,1))
        image = Image.fromarray(data).convert("P"); b=io.BytesIO(); image.save(b,format="PNG")
        png,_ = recolor_and_project(b.getvalue(),b"0.01\n0\n0\n-0.01\n-93\n45\n", smooth=False)
        out = np.asarray(Image.open(io.BytesIO(png)))[0]
        expected = [(0,0,0,0), (76,175,99,220),(76,175,99,220),
                    (37,139,69,220),(37,139,69,220),
                    (11,81,37,220),(11,81,37,220),
                    (230,205,57,220),(230,205,57,220),
                    (246,162,58,220),(246,162,58,220),
                    (230,91,59,220),(230,91,59,220),
                    (200,44,85,220),(200,44,85,220),
                    (138,63,160,220),(138,63,160,220)]
        self.assertEqual([tuple(pixel) for pixel in out],expected)

    def test_radar_smoothing_preserves_cutoff_footprint_and_core_colors(self):
        data = np.zeros((64,64), dtype="uint8")
        data[12:52,12:52] = 86  # Exactly 10 dBZ.
        data[24:40,24:40] = 126  # Exactly 30 dBZ.
        image = Image.fromarray(data).convert("P"); b = io.BytesIO(); image.save(b,format="PNG")
        world = b"0.01\n0\n0\n-0.01\n-93\n45\n"
        exact, exact_bounds = recolor_and_project(b.getvalue(),world,smooth=False)
        smooth, smooth_bounds = recolor_and_project(b.getvalue(),world)
        original = np.asarray(Image.open(io.BytesIO(exact)))
        softened = np.asarray(Image.open(io.BytesIO(smooth)))
        self.assertEqual(softened.shape, (128,128,4))
        self.assertEqual(exact_bounds, smooth_bounds)
        footprint = np.repeat(np.repeat(original[:,:,3] > 0,2,axis=0),2,axis=1)
        self.assertTrue((softened[~footprint] == 0).all())
        self.assertEqual(tuple(softened[64,64]), (230,205,57,220))
        self.assertEqual(tuple(softened[40,40]), (76,175,99,220))
        self.assertGreater(len(np.unique(softened.reshape(-1,4),axis=0)), len(np.unique(original.reshape(-1,4),axis=0)))

    def test_non_indexed_radar_rejected(self):
        b=io.BytesIO();Image.new("RGB",(10,10)).save(b,format="PNG")
        with self.assertRaises(ValueError):
            recolor_and_project(b.getvalue(),b"0.01\n0\n0\n-0.01\n-93\n45\n")



if __name__ == "__main__":
    unittest.main()
