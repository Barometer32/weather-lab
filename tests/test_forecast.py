import copy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from forecast_models import target_cycle, selected_records, blend, LOCATIONS, parse_index, decode_points, earth_wind, lambert_rotation
from forecast_store import read_forecast, write_forecast
from app import app, _cache
from forecast_models import ModelUnavailable
from forecast_worker import locate_common_cycle, main as worker_main

UTC = timezone.utc
CYCLE = datetime(2026, 10, 9, 12, tzinfo=UTC)


def models():
    point = {"temperatureK": 283.15, "dewpointK": 278.15, "east10": 3., "north10": 4., "lowCloudPct": 60., "midCloudPct": 20., "highCloudPct": 30.}
    return {m: {h: {s: dict(point, precipTotalMm=h * (1 if m == "HRRR" else 3)) for s in LOCATIONS}
                for h in range(1, 19)} for m in ("HRRR", "RRFS")}


class ForecastTests(unittest.TestCase):
    def test_late_model_chooses_same_complete_cycle_for_both_models(self):
        target = CYCLE + timedelta(hours=1)
        def locate(model, cycle):
            if model == "RRFS" and cycle == target:
                raise ModelUnavailable("RRFS late")
            return (f"{model}/{cycle.hour}", "index")
        with patch("forecast_worker.locate", side_effect=locate) as lookup:
            cycle, feeds = locate_common_cycle(target)
            self.assertEqual(cycle, CYCLE)
            self.assertEqual(feeds["HRRR"][0], "HRRR/12")
            self.assertEqual(feeds["RRFS"][0], "RRFS/12")
            self.assertEqual(lookup.call_count, 4)

    def test_late_target_does_not_redownload_stored_or_older_cycles(self):
        target = CYCLE + timedelta(hours=1)
        with patch("forecast_worker.locate", side_effect=ModelUnavailable("late")) as lookup:
            self.assertIsNone(locate_common_cycle(target, "2026-10-09T12:00:00Z"))
            self.assertEqual(lookup.call_count, 1)
            with self.assertRaises(ModelUnavailable):
                locate_common_cycle(target, lookback=0)

    def test_cached_grid_extraction_matches_independent_nearest_searches(self):
        import eccodes as ec
        handle = ec.codes_grib_new_from_samples("GRIB2")
        try:
            geometry = {"gridType": "lambert", "Nx": 20, "Ny": 20,
                "latitudeOfFirstGridPointInDegrees": 44.75, "longitudeOfFirstGridPointInDegrees": 266.4,
                "LoVInDegrees": 262.5, "LaDInDegrees": 38.5, "Latin1InDegrees": 38.5,
                "Latin2InDegrees": 38.5, "DxInMetres": 3000, "DyInMetres": 3000,
                "scanningMode": 64, "dataDate": 20261009, "dataTime": 1200,
                "stepUnits": 1, "forecastTime": 2}
            for key, value in geometry.items(): ec.codes_set(handle, key, value)
            for offset in (270, 280, 290):
                ec.codes_set_values(handle, [offset + i / 100 for i in range(400)])
                expected = {station: ec.codes_grib_find_nearest(handle, lat, lon % 360)[0]["value"]
                            for station, (lat, lon) in LOCATIONS.items()}
                message = ec.codes_get_message(handle)
                self.assertEqual(decode_points(message, CYCLE, 2, "temperatureK"), expected)
            with self.assertRaises(ValueError): decode_points(message, CYCLE, 3, "temperatureK")
        finally:
            ec.codes_release(handle)

    def test_cycle_at_45_and_retry_55_match_and_midnight_rolls_back(self):
        self.assertEqual(target_cycle(CYCLE + timedelta(hours=1, minutes=45)), CYCLE)
        self.assertEqual(target_cycle(CYCLE + timedelta(hours=1, minutes=55)), CYCLE)
        self.assertEqual(target_cycle(CYCLE + timedelta(hours=1, minutes=44)), CYCLE - timedelta(hours=1))
        self.assertEqual(target_cycle(CYCLE.replace(hour=0, minute=45)), CYCLE - timedelta(hours=13))

    def test_subhourly_records_do_not_replace_whole_hour(self):
        variables = [("TMP", "2 m above ground"), ("DPT", "2 m above ground"),
                     ("UGRD", "10 m above ground"), ("VGRD", "10 m above ground"),
                     ("GUST", "surface"), ("PRES", "surface"), ("APCP", "surface")]
        rows = []
        for minute in (105, 120):
            for parameter, level in variables:
                period = f"0-{minute} min acc fcst" if parameter == "APCP" else f"{minute} min fcst"
                rows.append(f"{len(rows)+1}:{len(rows)*100}:d=2026100912:{parameter}:{level}:{period}:")
        selected = selected_records("\n".join(rows), CYCLE, 2)
        self.assertTrue(all(r["offset"] >= 700 for r in selected.values()))
        self.assertEqual(parse_index("\n".join(rows))[0]["end"], 99)
        with self.assertRaises(ValueError):
            selected_records("\n".join(rows[:7]), CYCLE, 2)

    def test_blend_is_six_way_and_17_hour_precip_is_deaccumulated(self):
        inputs = models()
        inputs["RRFS"][1]["KMSP"]["temperatureK"] = 289.15
        data = blend(inputs, CYCLE, {})
        self.assertEqual(len(data["hours"]), 17)
        self.assertEqual(data["windowStart"], "2026-10-09T13:00:00Z")
        self.assertEqual(data["windowEnd"], "2026-10-10T06:00:00Z")
        self.assertEqual(data["hours"][0]["tempF"], 51.8)
        self.assertAlmostEqual(data["hours"][0]["precipIn"], 2 / 25.4, places=3)
        self.assertEqual(data["hours"][0]["precipEnd"], "2026-10-09T14:00:00Z")
        self.assertEqual(data["hours"][-1]["forecastHour"], 17)
        self.assertEqual(data["hours"][-1]["precipEnd"], "2026-10-10T06:00:00Z")
        self.assertNotIn("gustMph", data["hours"][0])
        self.assertNotIn("humidityPct", data["hours"][0])
        self.assertAlmostEqual(data["hours"][1]["precipIn"], 2 / 25.4, places=3)
        self.assertAlmostEqual(data["precipTotalIn"], 34 / 25.4, places=2)
        self.assertAlmostEqual(data["hours"][1]["windMph"], 11.2, places=1)

    def test_precipitation_is_for_the_following_hour(self):
        inputs = models()
        for model in inputs.values():
            for h, stations in model.items():
                for p in stations.values(): p["precipTotalMm"] = h * h
        data = blend(inputs, CYCLE, {})
        self.assertAlmostEqual(data["hours"][0]["precipIn"], (4 - 1) / 25.4, places=3)
        self.assertAlmostEqual(data["hours"][-1]["precipIn"], (324 - 289) / 25.4, places=3)

    def test_vector_blend_cancellation_north_wrap_and_from_direction(self):
        inputs = models()
        for h in inputs["HRRR"].values():
            for p in h.values(): p.update(east10=5, north10=0)
        for h in inputs["RRFS"].values():
            for p in h.values(): p.update(east10=-5, north10=0)
        row = blend(inputs, CYCLE, {})["hours"][0]
        self.assertEqual(row["windMph"], 0)
        self.assertIsNone(row["windDirection"])
        for model, angle in (("HRRR", 350), ("RRFS", 10)):
            for h in inputs[model].values():
                for p in h.values(): p.update(east10=-5*math.sin(math.radians(angle)), north10=-5*math.cos(math.radians(angle)))
        row = blend(inputs, CYCLE, {})["hours"][0]
        self.assertEqual(row["windDirection"], 0)
        self.assertAlmostEqual(row["windMph"], 11.0, places=1)
        self.assertEqual(row["contributors"]["windDirection"], ["HRRR", "RRFS"])
        for model in inputs.values():
            for h in model.values():
                for p in h.values(): p.update(east10=5, north10=0)
        self.assertEqual(blend(inputs, CYCLE, {})["hours"][0]["windDirection"], 270)

    def test_lambert_grid_rotation_and_earth_relative_flag(self):
        import eccodes as ec
        handle = ec.codes_grib_new_from_samples("GRIB2")
        try:
            geometry = {"gridType": "lambert", "Nx": 20, "Ny": 20,
                "latitudeOfFirstGridPointInDegrees": 44.75, "longitudeOfFirstGridPointInDegrees": 266.4,
                "LoVInDegrees": 262.5, "LaDInDegrees": 38.5, "Latin1InDegrees": 38.5,
                "Latin2InDegrees": 38.5, "DxInMetres": 3000, "DyInMetres": 3000,
                "scanningMode": 64, "shapeOfTheEarth": 6, "dataDate": 20261009,
                "dataTime": 1200, "stepUnits": 1, "forecastTime": 2}
            for key, value in geometry.items(): ec.codes_set(handle, key, value)
            ec.codes_set_values(handle, [10.] * 400)
            ec.codes_set(handle, "uvRelativeToGrid", 1)
            metadata = {station: {} for station in LOCATIONS}
            values = decode_points(ec.codes_get_message(handle), CYCLE, 2, "u10", metadata)
            for station, (lat, lon) in LOCATIONS.items():
                nearest = ec.codes_grib_find_nearest(handle, lat, lon % 360)[0]
                angle = metadata[station]["u10"][1]
                self.assertAlmostEqual(angle, math.sin(math.radians(38.5)) * math.radians(nearest["lon"] - 262.5))
                east, north = earth_wind(values[station], 0, angle)
                self.assertGreater(east, 9)
                self.assertLess(north, 0)  # East of central meridian: grid east points south of true east.
                self.assertAlmostEqual(math.hypot(east, north), 10)
            self.assertEqual(lambert_rotation(-97.5, 262.5, 38.5, 38.5), 0)
            ec.codes_set(handle, "uvRelativeToGrid", 0)
            decode_points(ec.codes_get_message(handle), CYCLE, 2, "v10", metadata)
            self.assertTrue(all(metadata[s]["v10"][1] == 0 for s in LOCATIONS))
        finally:
            ec.codes_release(handle)

    def test_worker_rebuilds_stored_cycle_for_new_schema_once(self):
        old = blend(models(), CYCLE, {})
        old.pop("schemaVersion")
        with patch("sys.argv", ["forecast_worker.py"]), patch("forecast_worker.target_cycle", return_value=CYCLE), patch("forecast_worker.read_forecast", return_value=old), patch("forecast_worker.locate_common_cycle", return_value=(CYCLE, {"HRRR": ("hrrr/prod/file", "index"), "RRFS": ("rrfs/para/file", "index")})) as locate, patch("forecast_worker.collect_model", side_effect=lambda model, *args: models()[model]) as collect, patch("forecast_worker.write_forecast") as publish:
            worker_main()
            self.assertEqual(locate.call_args.args[1], "2026-10-09T11:00:00Z")
            self.assertEqual(collect.call_count, 2)
            self.assertEqual(publish.call_args.args[0]["schemaVersion"], 3)
        with patch("sys.argv", ["forecast_worker.py"]), patch("forecast_worker.target_cycle", return_value=CYCLE), patch("forecast_worker.read_forecast", return_value=blend(models(), CYCLE, {})), patch("forecast_worker.collect_model") as collect:
            worker_main()
            collect.assert_not_called()

    def test_schema_upgrade_can_replace_same_cycle_but_not_newer_cycle(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"FORECAST_FILE": str(Path(temp)/"forecast.json"), "FORECAST_BUCKET": ""}):
                old = blend(models(), CYCLE, {})
                old.pop("schemaVersion")
                self.assertTrue(write_forecast(old))
                upgraded = blend(models(), CYCLE, {})
                self.assertTrue(write_forecast(upgraded))
                self.assertFalse(write_forecast(upgraded))
                self.assertFalse(write_forecast(old))
                older = dict(upgraded, cycle="2026-10-09T11:00:00Z", schemaVersion=4)
                self.assertFalse(write_forecast(older))

    def test_cloud_single_source_has_explicit_provenance(self):
        inputs = models()
        for h in inputs["RRFS"].values():
            for p in h.values(): p.pop("lowCloudPct")
        row = blend(inputs,CYCLE,{})["hours"][0]
        self.assertEqual(row["lowCloudPct"], 60)
        self.assertEqual(row["contributors"]["lowCloudPct"], ["HRRR"])
        self.assertEqual(row["contributors"]["midCloudPct"], ["HRRR", "RRFS"])
        self.assertEqual(row["contributors"]["highCloudPct"], ["HRRR", "RRFS"])

    def test_incomplete_station_and_invalid_values_fail_collection(self):
        inputs = models()
        del inputs["RRFS"][5]["KMIC"]
        with self.assertRaises(KeyError): blend(inputs,CYCLE,{})
        inputs = models(); inputs["RRFS"][5]["KMIC"]["dewpointK"] = 330
        with self.assertRaises(ValueError): blend(inputs,CYCLE,{})
        inputs = models(); inputs["RRFS"][5]["KMIC"]["precipTotalMm"] = 0
        with self.assertRaises(ValueError): blend(inputs,CYCLE,{})

    def test_publication_does_not_overwrite_a_newer_forecast(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"FORECAST_FILE": str(Path(temp)/"forecast.json"), "FORECAST_BUCKET": ""}):
                new = blend(models(),CYCLE,{})
                self.assertTrue(write_forecast(new))
                self.assertFalse(write_forecast(new))
                older = dict(new,cycle="2026-10-09T11:00:00Z")
                self.assertFalse(write_forecast(older))
                self.assertEqual(read_forecast()["cycle"],new["cycle"])

    def test_forecast_api_shows_stale_and_missing(self):
        _cache.pop("forecast",None)
        data = blend(models(),CYCLE,{})
        with patch("forecast_store.read_forecast",return_value=data), patch("app.utcnow",return_value=CYCLE+timedelta(hours=4)):
            self.assertTrue(app.test_client().get("/api/forecast").get_json()["stale"])
        _cache.pop("forecast",None)
        with patch("forecast_store.read_forecast",side_effect=FileNotFoundError()):
            self.assertEqual(app.test_client().get("/api/forecast").status_code,503)
        _cache.pop("forecast",None)


if __name__ == "__main__":
    unittest.main()
