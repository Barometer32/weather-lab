import json
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

from PIL import Image

import app as weather
import collector
from satellite import BASE

NOW = datetime(2026, 10, 9, 18, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.writes = []

    def read(self, key):
        return self.objects.get(key)

    def write(self, key, data, content_type):
        self.objects[key] = data
        self.writes.append(key)

    def read_json(self, key):
        raw = self.read(key)
        return json.loads(raw) if raw is not None else None

    def write_json(self, key, data):
        self.write(key, json.dumps(data).encode(), "application/json")


def frame(minutes):
    moment = NOW - timedelta(minutes=minutes)
    return {"id": moment.strftime("%Y%m%d%H%M"), "time": weather.iso(moment)}


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        weather._cache.clear()
        weather.prepared_image.cache_clear()

    def test_radar_publishes_images_before_manifest_and_only_processes_new_frames(self):
        with patch("app.get_scans", return_value=[frame(10),frame(5)]), patch("app.radar_frame", return_value=(b"png",[[44,-94],[46,-92]])) as render:
            collector.collect_radar(self.store, NOW)
            self.assertEqual(render.call_args_list[0].args[0],frame(5)["id"])
            self.assertEqual(self.store.writes[-1],"live/radar.json")
            collector.collect_radar(self.store, NOW)
            self.assertEqual(render.call_count,2)
        with patch("app.get_scans", return_value=[frame(5),frame(0)]), patch("app.radar_frame", return_value=(b"new",[[44,-94],[46,-92]])) as render:
            collector.collect_radar(self.store,NOW)
            self.assertEqual(render.call_count,1)
        self.assertEqual(len(self.store.read_json("live/radar.json")["frames"]),2)

    def test_failed_radar_collection_keeps_previous_manifest(self):
        self.store.write_json("live/radar.json", {"checkedAt":weather.iso(NOW),"frames":[]})
        before = self.store.read("live/radar.json")
        with patch("app.get_scans",return_value=[frame(0)]), patch("app.radar_frame",side_effect=TimeoutError):
            with self.assertRaises(ValueError): collector.collect_radar(self.store,NOW)
        self.assertEqual(self.store.read("live/radar.json"),before)

    def test_initial_backfill_checkpoints_and_resumes_without_reprocessing_latest(self):
        with patch("app.get_scans",return_value=[frame(5),frame(0)]), patch("app.radar_frame",return_value=(b"png",[[44,-94],[46,-92]])) as render:
            with patch("collector.time.monotonic",side_effect=[0,1,200]):
                result=collector.collect_radar(self.store,NOW)
            self.assertEqual(result["unavailable"],1)
            self.assertEqual(self.store.read_json("live/radar.json")["frames"][0]["id"],frame(0)["id"])
            collector.collect_radar(self.store,NOW)
            self.assertEqual(render.call_count,2)
            self.assertEqual(len(self.store.read_json("live/radar.json")["frames"]),2)

    def test_partial_collection_publishes_only_valid_available_frames(self):
        with patch("app.get_scans",return_value=[frame(5),frame(0)]), patch("app.radar_frame",side_effect=[(b"new",[[44,-94],[46,-92]]),TimeoutError]):
            collector.collect_radar(self.store,NOW)
        data = self.store.read_json("live/radar.json")
        self.assertEqual([f["id"] for f in data["frames"]],[frame(0)["id"]])
        self.assertEqual(data["unavailableScans"],1)

    def test_satellite_keeps_original_image_bytes_and_reuses_existing_frames_and_maps(self):
        buf=BytesIO(); Image.new("RGB",(1600,900),(50,80,120)).save(buf,format="JPEG"); jpeg=buf.getvalue()
        buf=BytesIO(); Image.new("RGBA",(1600,900)).save(buf,format="PNG"); overlay=buf.getvalue()
        html = BASE+"/truecolor/S_Minnesota.truecolor.20261009.175000.jpg " + BASE+"/maps/S_Minnesota_map.png?v=123"
        def download(url):
            return html.encode() if "satrad" in url else overlay if "maps" in url else jpeg
        with patch("app.download",side_effect=download) as fetch:
            collector.collect_product(self.store,"truecolor",NOW)
            self.assertEqual(fetch.call_count,3)
            data=self.store.read_json("live/satellite-truecolor.json")
            self.assertEqual(self.store.read(data["frames"][0]["url"].removeprefix("/api/prepared/")),jpeg)
            self.assertIn(BASE+"/maps/S_Minnesota_map.png?v=123",data["boundarySources"])
            collector.collect_product(self.store,"truecolor",NOW)
            self.assertEqual(fetch.call_count,4)

    def test_cold_web_reads_prepared_radar_without_upstream_processing_and_refilters_window(self):
        data=weather.radar_manifest([frame(121),frame(5)],NOW); data["checkedAt"]=weather.iso(NOW)
        self.store.write_json("live/radar.json",data)
        with patch("app.get_store",return_value=self.store), patch("app.utcnow",return_value=NOW), patch("app.download") as upstream, patch("app.radar_frame") as render:
            response=weather.app.test_client().get("/api/radar")
            self.assertEqual(response.status_code,200)
            self.assertEqual([x["id"] for x in response.json["frames"]],[frame(5)["id"]])
            self.assertFalse(response.json["stale"])
            upstream.assert_not_called(); render.assert_not_called()

    def test_missing_prepared_data_does_not_trigger_expensive_public_collection(self):
        with patch("app.get_store",return_value=self.store), patch("app.download") as upstream:
            self.assertEqual(weather.app.test_client().get("/api/radar").status_code,502)
            self.assertEqual(weather.app.test_client().post("/collect/radar").status_code,404)
            upstream.assert_not_called()

    def test_stale_observations_are_recomputed_for_now_instead_of_reusing_old_green_hour(self):
        reports=[{"icaoId":station,"metarType":"METAR","obsTime":(NOW-timedelta(minutes=67)).timestamp(),
                  "temp":10,"dewp":5,"wspd":5,"wdir":90} for station in weather.STATIONS]
        self.store.write_json("live/observations.json",{"reports":reports,"checkedAt":weather.iso(NOW-timedelta(hours=2))})
        with patch("app.get_store",return_value=self.store), patch("app.utcnow",return_value=NOW):
            response=weather.app.test_client().get("/api/observations")
            self.assertTrue(response.json["stale"])
            self.assertEqual(response.json["current"]["hour"],weather.iso(NOW))
            self.assertFalse(response.json["current"]["qa"]["allStationsUsed"])

    def test_prepared_asset_route_cannot_read_manifests_or_arbitrary_objects(self):
        key=f"radar/{weather.RENDER_VERSION}/{frame(0)['id']}.png"
        self.store.write(key,b"png","image/png")
        with patch("app.get_store",return_value=self.store), patch("app.download") as upstream:
            client=weather.app.test_client()
            self.assertEqual(client.get("/api/prepared/"+key).data,b"png")
            self.assertEqual(client.get("/api/prepared/live/observations.json").status_code,404)
            self.assertEqual(client.get("/api/prepared/secrets.txt").status_code,404)
            upstream.assert_not_called()


if __name__ == "__main__": unittest.main()
