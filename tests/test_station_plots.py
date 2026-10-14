from datetime import datetime, timedelta, timezone
import gzip
import json
import unittest
from unittest.mock import patch

import app
import collector
import station_plots as stations
from test_realtime import MemoryStore

NOW = datetime(2026, 10, 14, 20, 20, tzinfo=timezone.utc)


def row(identifier="MSP", network="MN_ASOS", **values):
    return {"station": identifier, "name": "Minneapolis", "network": network, "state": "MN",
            "utc_valid": "2026-10-14T20:15:00Z", "lat": 44.9, "lon": -93.3,
            "tmpf": 55.4, "dwpf": 40.1, "sknt": 10, "drct": 270, **values}


def payload(*rows):
    return json.dumps({"data": rows}).encode()


class StationPlotTests(unittest.TestCase):
    def setUp(self):
        app._cache.clear()

    def test_source_units_air_temperature_and_network_ids(self):
        rows = stations.parse(payload(row(tsf0=110), row("MN001", "MN_RWIS", tmpf=60)), NOW)
        indexed = {r["station"]: r for r in rows}
        self.assertEqual(indexed["KMSP"]["tempF"], 55.4)
        self.assertEqual(indexed["MN001"]["tempF"], 60)
        self.assertAlmostEqual(indexed["KMSP"]["wind"]["speedMph"], 11.50779448)
        self.assertEqual(indexed["MN001"]["stationKey"], "MN_RWIS:MN001")
        self.assertEqual(indexed["KMSP"]["time"], "2026-10-14T20:15:00Z")

    def test_stale_future_missing_bad_coordinates_and_values(self):
        rows = stations.parse(payload(
            row("OLD", utc_valid=stations.iso(NOW-timedelta(minutes=91))),
            row("FUT", utc_valid=stations.iso(NOW+timedelta(seconds=1))),
            row("DAY", utc_valid="2026-10-14T13:00:00Z"),
            row("LOC", lat=float("nan")), row("OUT", lon=-110),
            row("NIL", tmpf=None, dwpf=None, sknt=None),
            row("BAD", tmpf=1000, dwpf=-9999, sknt=-10),
            row("BOOL", tmpf=True, dwpf=True, sknt=True),
            row("CFE"), row("SGS"), row("FCE"),
            row("OK1", dwpf=70), row("UNK", drct=None),
            row("VRB", drct=None, raw="KVRB 142015Z VRB10KT")), NOW)
        indexed = {r["station"]: r for r in rows}
        self.assertEqual(set(indexed), {"KOK1", "KUNK", "KVRB"})
        self.assertIsNone(indexed["KOK1"]["dewpointF"])
        self.assertFalse(indexed["KUNK"]["wind"]["variable"])
        self.assertTrue(indexed["KVRB"]["wind"]["variable"])

    def test_duplicate_ids_in_separate_networks_and_latest_report(self):
        rows = stations.parse(payload(row("ABC", "MN_DCP"), row("ABC", "MN_RWIS"),
                            row("ABC", "MN_DCP", utc_valid="2026-10-14T20:16:00Z", tmpf=61)), NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["stationKey"] for r in rows}, {"MN_DCP:ABC", "MN_RWIS:ABC"})
        self.assertEqual(next(r for r in rows if r["network"] == "MN_DCP")["tempF"], 61)

    def test_history_rolls_pending_into_completed_hour_without_carrying_older_reports(self):
        rows = stations.parse(payload(row()), NOW)
        frames, pending = stations.history(rows, NOW)
        self.assertTrue(all(not frame["stations"] for frame in frames))
        self.assertEqual(pending["hour"], "2026-10-14T21:00:00Z")
        previous = {"history": frames, "pendingHour": pending, "stations": rows}
        result = stations.current(previous, NOW.replace(hour=21, minute=0))
        self.assertEqual(result["history"][-1]["stations"][0]["time"], "2026-10-14T20:15:00Z")
        later = stations.current(previous, NOW.replace(hour=22, minute=0))
        self.assertEqual(later["stations"], [])
        self.assertEqual(later["history"][-1]["stations"], [])
        self.assertEqual(len(later["history"]), 12)

    def test_partial_failure_is_reported_and_only_recent_failed_state_reports_survive(self):
        previous = {"version": 1, "stations": stations.parse(payload(row("OLD", state="WI"),
                         row("STA", state="WI", utc_valid="2026-10-14T19:00:00Z")), NOW), "history": []}
        later = NOW+timedelta(minutes=20)
        def download(url):
            if url.endswith("=WI"):
                raise TimeoutError("temporary failure")
            return payload(row("NEW", utc_valid=stations.iso(later))) if url.endswith("=MN") else payload()
        with self.assertLogs("station_plots", level="ERROR"):
            result = stations.collect(download, later, previous)
        self.assertEqual(result["failedStates"], ["WI"])
        self.assertEqual({r["station"] for r in result["stations"]}, {"KOLD", "KNEW"})

    def test_total_failure_does_not_replace_prepared_object(self):
        store = MemoryStore()
        store.write_json("live/station-plots.json", {"version": 1, "checkedAt": stations.iso(NOW-timedelta(hours=1)), "stations": []})
        before = store.read("live/station-plots.json")
        with patch("app.download", return_value=payload()), self.assertRaises(ValueError):
            collector.collect_stations(store, NOW)
        self.assertEqual(store.read("live/station-plots.json"), before)

    def test_collector_bulk_calls_and_public_api_uses_only_saved_data(self):
        store = MemoryStore()
        with patch("app.download", return_value=payload(row())) as download:
            collector.collect_stations(store, NOW)
        self.assertEqual(download.call_count, len(stations.STATES))
        self.assertEqual(store.writes[-1], "live/station-plots.json")
        with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=NOW), patch("app.download") as upstream:
            result = app.app.test_client().get("/api/station-plots")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["stations"][0]["station"], "KMSP")
        self.assertNotIn("pendingHour", result.json)
        upstream.assert_not_called()
        with patch("app.download") as duplicate:
            collector.collect_stations(store, NOW+timedelta(minutes=1))
        duplicate.assert_not_called()

    def test_api_filters_expired_latest_data_without_upstream_and_compresses_history(self):
        rows = stations.parse(payload(*(row(str(i).zfill(3)) for i in range(100))), NOW)
        frames, pending = stations.history(rows, NOW)
        store = MemoryStore()
        store.write_json("live/station-plots.json", {"version": 1, "checkedAt": stations.iso(NOW),
                         "stations": rows, "history": frames, "pendingHour": pending})
        with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=NOW+timedelta(hours=2)), patch("app.download") as upstream:
            plain = app.app.test_client().get("/api/station-plots")
            zipped = app.app.test_client().get("/api/station-plots", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(plain.json["stations"], [])
        self.assertTrue(plain.json["stale"])
        self.assertEqual(json.loads(gzip.decompress(zipped.data)), plain.json)
        upstream.assert_not_called()

    def test_missing_prepared_data_returns_explicit_error_without_upstream(self):
        with patch("app.get_store", return_value=MemoryStore()), patch("app.download") as upstream:
            result = app.app.test_client().get("/api/station-plots")
        self.assertEqual(result.status_code, 503)
        self.assertIn("being prepared", result.json["error"])
        upstream.assert_not_called()



if __name__ == "__main__":
    unittest.main()
