from datetime import datetime, timezone
import json
import unittest

import wisconet
import station_plots

HOUR = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)


def feature(station="WDVL", stamp="2026-10-14T20:00:00Z", qc="Z", **values):
    defaults = {"tempF": 50.3, "dewpointF": 42.9, "speedMph": 4.6, "direction": 171.4}
    defaults.update(values)
    properties = {"station_id": station, "station_name": "Woodville"}
    for field, (name, unit, _, _) in wisconet.FIELDS.items():
        properties[field] = {"unitCode": unit, "observations": [{"timestamp": stamp,
                             "value": defaults[name], "qualityControl": qc}]}
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-92.3, 44.9]}, "properties": properties}


def payload(*features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


class WisconetTests(unittest.TestCase):
    def test_units_are_already_fahrenheit_and_mph_and_source_identity_is_preserved(self):
        row = wisconet.parse(payload(feature()), HOUR)[0]
        self.assertEqual(row["tempF"], 50.3)
        self.assertEqual(row["wind"]["speedMph"], 4.6)
        self.assertAlmostEqual(row["wind"]["speedKnots"], 4.6 / 1.150779448)
        self.assertEqual(row["stationKey"], "WISCONET:WDVL")
        self.assertEqual(row["license"], "CC BY 4.0")
        self.assertEqual(row["sourceQc"]["tempF"], "Z")
        self.assertEqual(row["measurementPeriod"], "5-minute average")

    def test_time_window_inclusive_boundaries_stale_future_and_test_stations(self):
        rows = wisconet.parse(payload(feature("START", "2026-10-14T19:50:00Z"), feature("END"),
                       feature("OLD", "2026-10-14T19:49:59Z"), feature("FUT", "2026-10-14T20:00:01Z"),
                       feature("WNTEST1"), feature("MITEST1")), HOUR)
        self.assertEqual({r["station"] for r in rows}, {"START", "END"})

    def test_flagged_bad_or_suspect_values_are_omitted(self):
        rows = wisconet.parse(payload(feature("BAD", qc="X"), feature("SUSPECT", qc="Q"),
                                     feature("UNKNOWN", qc="unexpected"), feature("OK", qc="V")), HOUR)
        self.assertEqual([r["station"] for r in rows], ["OK"])

    def test_impossible_values_and_wrong_units(self):
        rows = wisconet.parse(payload(feature(tempF=55, dewpointF=70, speedMph=-5, direction=1000)), HOUR)
        self.assertIsNone(rows[0]["dewpointF"])
        self.assertIsNone(rows[0]["wind"]["speedMph"])
        self.assertIsNone(rows[0]["wind"]["direction"])
        bad = feature()
        bad["properties"]["5min_air_temp_f_avg"]["unitCode"] = "ud:degC"
        with self.assertRaises(ValueError):
            wisconet.parse(payload(bad), HOUR)

    def test_fields_from_different_times_are_not_combined(self):
        item = feature()
        item["properties"]["5min_dew_point_f_avg"]["observations"][0]["timestamp"] = "2026-10-14T19:55:00Z"
        rows = wisconet.parse(payload(item), HOUR)
        self.assertEqual(rows[0]["time"], "2026-10-14T20:00:00Z")
        self.assertIsNone(rows[0]["dewpointF"])

    def test_merge_uses_one_bulk_wisconet_request_and_does_not_duplicate_physical_values(self):
        from test_station_plots import downloader, row
        base = downloader(row("MSP"))
        calls = []
        def download(url):
            calls.append(url)
            return payload(feature()) if url.startswith(wisconet.SOURCE) else base(url)
        result = station_plots.collect(download, HOUR)
        self.assertEqual({r["station"] for r in result["stations"]}, {"KMSP", "WDVL"})
        self.assertEqual(sum(url.startswith(wisconet.SOURCE) for url in calls), 1)
        self.assertEqual(len(calls), len(station_plots.STATES)+1)
        self.assertIn("date=2026-10-14T20%3A00%3A00Z", next(url for url in calls if url.startswith(wisconet.SOURCE)))

    def test_wisconet_failure_keeps_other_networks_and_reports_source_delay(self):
        from test_station_plots import downloader, row
        base = downloader(row("MSP"))
        def download(url):
            if url.startswith(wisconet.SOURCE):
                raise TimeoutError("Wisconet delayed")
            return base(url)
        with self.assertLogs("station_plots", level="ERROR"):
            result = station_plots.collect(download, HOUR)
        self.assertEqual([r["station"] for r in result["stations"]], ["KMSP"])
        self.assertEqual(result["failedSources"], ["WISCONET"])


if __name__ == "__main__":
    unittest.main()
