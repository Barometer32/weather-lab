from datetime import datetime, timedelta, timezone
import unittest

from lamp_hourly import HORIZON, STATIONS, build_forecast, clouds, latest_cycle


CYCLE = datetime(2026, 11, 28, 3, 30, tzinfo=timezone.utc)


def station_block(station, index):
    values = {
        "UTC": [f"{(4 + hour) % 24:02d}" for hour in range(25)],
        "TMP": [-4 + 2 * index] * 25,
        "DPT": [-10 + 2 * index] * 25,
        "WSP": [10] * 25,
        "WDR": [(35, 1, 0)[index]] * 25,
        "CLD": ["OV"] * 25,
        "CIG": [7] * 25,
        "P01": [0, 100, 100] + [50] * 21 + [90 + index * 5],
    }
    header = f" {station}   GFS LAMP GUIDANCE  11/28/2026  0330 UTC"
    return "\n".join([header, *(" " + key + " " + "".join(f"{value:>3}" for value in row)
                               for key, row in values.items())])


class HourlyLampTest(unittest.TestCase):
    def test_start_time_precip_window_and_midnight(self):
        document = "\n\n".join(station_block(station, index) for index, station in enumerate(STATIONS))
        forecast = build_forecast(document, CYCLE, CYCLE + timedelta(minutes=25))
        rows = forecast["rows"]
        self.assertEqual(len(rows), HORIZON)
        self.assertEqual(rows[0]["time"], "2026-11-28T04:00:00Z")
        self.assertEqual(rows[0]["endTime"], "2026-11-28T05:00:00Z")
        self.assertEqual(rows[0]["precipChance"], 100)
        self.assertEqual(rows[0]["tempF"], -2)
        self.assertEqual(rows[0]["dewpointF"], -8)
        self.assertEqual(rows[0]["windMph"], 12)
        self.assertAlmostEqual((rows[0]["windDirection"] + 180) % 360, 180)
        self.assertEqual(rows[0]["cloudCover"], "Overcast")
        self.assertEqual(rows[0]["ceiling"], "9k")
        self.assertEqual(rows[20]["time"], "2026-11-29T00:00:00Z")
        self.assertEqual(rows[-1]["time"], "2026-11-29T03:00:00Z")
        self.assertEqual(rows[-1]["endTime"], "2026-11-29T04:00:00Z")
        self.assertEqual(rows[-1]["precipChance"], 95)

    def test_ceiling_is_open_ended_when_all_cloudy_ceilings_are_high(self):
        self.assertEqual(clouds(["OV", "OV", "OV"], [8, 8, 8]), ("Overcast", ">12k"))
        self.assertEqual(clouds(["BK", "OV", "OV"], [7, 8, 8]), ("Broken", "9k"))
        self.assertEqual(clouds(["OV", "BK", "FW"], [7, 6, 8]), ("Broken", "7k"))
        self.assertEqual(clouds(["BK", "FW", "SC"], [4, 8, 8]), ("Scattered", "1k"))
        self.assertEqual(clouds(["CL", "SC", "FW"], [8, 8, 8]), ("Few", None))

    def test_required_station_and_cycle(self):
        partial = "\n".join(station_block(station, index) for index, station in enumerate(STATIONS[:2]))
        with self.assertRaisesRegex(ValueError, "KMIC"):
            build_forecast(partial, CYCLE, CYCLE)
        with self.assertRaisesRegex(ValueError, "cycle mismatch"):
            build_forecast(partial, CYCLE + timedelta(hours=1), CYCLE)

    def test_scheduled_cycle_at_top_of_hour(self):
        self.assertEqual(latest_cycle(CYCLE + timedelta(minutes=24)), CYCLE - timedelta(hours=1))
        self.assertEqual(latest_cycle(CYCLE + timedelta(minutes=25)), CYCLE)
        self.assertEqual(latest_cycle(CYCLE + timedelta(minutes=30)), CYCLE)


if __name__ == "__main__":
    unittest.main()


def test_text_forecast_and_lamp_keep_separate_failures():
    from unittest.mock import patch

    import collector

    with patch("collector.collect_forecast", return_value={"periods": 14}), \
         patch("collector.collect_lamp_forecast", side_effect=TimeoutError):
        assert collector.collect_forecasts(None, CYCLE) == {"periods": 14}

    with patch("collector.collect_forecast", side_effect=TimeoutError), \
         patch("collector.collect_lamp_forecast") as hourly:
        with unittest.TestCase().assertRaises(TimeoutError):
            collector.collect_forecasts(None, CYCLE)
        hourly.assert_called_once_with(None, CYCLE)
