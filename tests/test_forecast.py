import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import app as weather
import collector
from app import app, _cache
from nws_forecast import normalize_forecast, FORECAST_URL, FORECAST_VERSION
from satellite import parse_loop, page_url, BASE
from test_realtime import MemoryStore

NOW = datetime(2026, 10, 9, 16, 50, tzinfo=timezone.utc)


def document():
    return {"creationDate":"2026-10-09T16:56:41-05:00",
            "creationDateLocal":"9 Oct 17:53 pm CDT",
            "time":{"startPeriodName":["This Afternoon","Tonight","Saturday"],
                    "startValidTime":["2026-10-09T12:00:00-05:00","2026-10-09T18:00:00-05:00","2026-10-10T06:00:00-05:00"],
                    "tempLabel":["High","Low","High"]},
            "data":{"temperature":["75","61","87"],"pop":[None,"0","20"],
                    "weather":["Sunny","Partly Cloudy","Sunny then Sunny and Breezy"],
                    "text":["Sunny, with a high near 75.",
                            "Partly cloudy, with a low around 61. Southeast wind 5 to 10 mph. ",
                            "Sunny, with a high near 87. Breezy, with a south wind 10 to 20 mph, with gusts as high as 35 mph. "]}}


class ForecastTests(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def test_feed_narrative_periods_and_issuance_come_from_same_mapclick_response(self):
        upstream=document()
        data=normalize_forecast(upstream,NOW)
        self.assertEqual(data["forecastVersion"],FORECAST_VERSION)
        self.assertEqual(data["updatedAt"],"2026-10-09T21:56:41Z")
        self.assertEqual(data["periods"][1]["detailedForecast"],upstream["data"]["text"][1].strip())
        self.assertEqual(data["periods"][1]["temperature"],61)
        self.assertFalse(data["periods"][1]["isDaytime"])
        self.assertEqual(data["periods"][2]["name"],"Saturday")
        self.assertTrue(data["periods"][2]["isDaytime"])
        self.assertEqual((data["latitude"],data["longitude"]),(44.9244,-93.414))

    def test_keeps_ongoing_period_but_drops_completed_one_at_exact_boundary(self):
        now=datetime(2026,10,9,23,tzinfo=timezone.utc)
        self.assertEqual(normalize_forecast(document(),now-timedelta(seconds=1))["periods"][0]["name"],"This Afternoon")
        self.assertEqual(normalize_forecast(document(),now)["periods"][0]["name"],"Tonight")

    def test_webpage_can_start_tonight_before_six_without_reinserting_afternoon(self):
        upstream=document()
        for key in upstream["time"]:upstream["time"][key]=upstream["time"][key][1:]
        for key in upstream["data"]:upstream["data"][key]=upstream["data"][key][1:]
        now=datetime(2026,10,9,22,58,tzinfo=timezone.utc)
        data=normalize_forecast(upstream,now)
        self.assertEqual([p["name"] for p in data["periods"]],["Tonight","Saturday"])

    def test_null_precip_is_not_zero_and_invalid_numbers_are_missing(self):
        upstream=document();upstream["data"]["pop"]=[None,"0","101"]
        upstream["data"]["temperature"]=["NA","61","NaN"]
        data=normalize_forecast(upstream,NOW)
        self.assertEqual([x["precipChancePct"] for x in data["periods"]],[None,0,None])
        self.assertEqual([x["temperature"] for x in data["periods"]],[None,61,None])

    def test_invalid_or_misaligned_feed_does_not_look_like_success(self):
        cases=[]
        for group,key,value in [("time","startPeriodName",[]),("data","text",["Sunny"]),
                                ("data","text",["Sunny","","Breezy"]),
                                ("time","startValidTime",["2026-10-09T12:00:00","2026-10-09T18:00:00-05:00","2026-10-10T06:00:00-05:00"])]:
            upstream=document();upstream[group][key]=value;cases.append(upstream)
        upstream=document();upstream["creationDate"]="2026-10-09T16:56:41";cases.append(upstream)
        upstream=document();upstream["time"]["startValidTime"][1]=upstream["time"]["startValidTime"][0];cases.append(upstream)
        for upstream in cases:
            with self.subTest(upstream=upstream),self.assertRaises(ValueError):normalize_forecast(upstream,NOW)
        with self.assertRaises(ValueError):normalize_forecast(document(),NOW+timedelta(days=10))

    def test_final_night_period_ends_at_local_six_across_dst(self):
        upstream=document()
        upstream["time"]={"startPeriodName":["Saturday Night"],"startValidTime":["2026-10-31T18:00:00-05:00"],"tempLabel":["Low"]}
        upstream["data"]={"temperature":["40"],"text":["Mostly cloudy."]}
        data=normalize_forecast(upstream,datetime(2026,10,31,23,tzinfo=timezone.utc))
        self.assertEqual(data["periods"][0]["endTime"],"2026-11-01T06:00:00-06:00")

    def test_api_uses_mapclick_directly_and_caches_upstream(self):
        with patch("app.get_store",return_value=None),patch("app.utcnow",return_value=NOW),patch("app.download",return_value=json.dumps(document()).encode()) as download:
            client=app.test_client()
            response=client.get("/api/forecast")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertEqual(client.get("/api/forecast").status_code,200)
            self.assertEqual(download.call_count,1)
            self.assertEqual(download.call_args.args[0],FORECAST_URL)

    def test_saved_forecast_is_filtered_at_request_time_without_upstream_calls(self):
        store=MemoryStore();data=normalize_forecast(document(),NOW);data["checkedAt"]="2026-10-09T22:55:00Z"
        store.write_json("live/forecast.json",data)
        with patch("app.get_store",return_value=store),patch("app.utcnow",return_value=datetime(2026,10,9,23,tzinfo=timezone.utc)),patch("app.download") as upstream:
            response=app.test_client().get("/api/forecast")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json["periods"][0]["name"],"Tonight")
            self.assertEqual(response.json["updatedAt"],data["updatedAt"])
            upstream.assert_not_called()

    def test_legacy_snapshot_does_not_masquerade_as_matching_webpage(self):
        store=MemoryStore();data=normalize_forecast(document(),NOW);data.pop("forecastVersion");data["checkedAt"]=weather.iso(NOW)
        store.write_json("live/forecast.json",data)
        with patch("app.get_store",return_value=store),patch("app.utcnow",return_value=NOW),patch("app.download") as upstream:
            self.assertEqual(app.test_client().get("/api/forecast").status_code,503)
            upstream.assert_not_called()

    def test_collector_replaces_periods_even_when_issuance_time_is_unchanged(self):
        store=MemoryStore();older=document();newer=copy.deepcopy(older)
        for group in ("time","data"):
            for key in newer[group]:newer[group][key]=newer[group][key][1:]
        with patch("app.download",side_effect=[json.dumps(older).encode(),json.dumps(newer).encode()]) as upstream:
            collector.collect_forecast(store,NOW)
            collector.collect_forecast(store,NOW+timedelta(minutes=5))
            self.assertEqual(upstream.call_count,2)
        saved=store.read_json("live/forecast.json")
        self.assertEqual(saved["updatedAt"],"2026-10-09T21:56:41Z")
        self.assertEqual(saved["periods"][0]["name"],"Tonight")

    def test_upstream_failure_retains_previous_prepared_forecast(self):
        store=MemoryStore();data=normalize_forecast(document(),NOW);store.write_json("live/forecast.json",data)
        before=store.read("live/forecast.json")
        with patch("app.download",side_effect=TimeoutError),self.assertRaises(TimeoutError):collector.collect_forecast(store,NOW)
        self.assertEqual(store.read("live/forecast.json"),before)

    def test_upstream_error_is_reported(self):
        with patch("app.get_store",return_value=None),patch("app.download",side_effect=TimeoutError):
            self.assertEqual(app.test_client().get("/api/forecast").status_code,502)

class SatelliteTests(unittest.TestCase):
    def test_product_specific_loop_sorted_deduplicated_and_future_excluded(self):
        prefix=BASE+"/truecolor/S_Minnesota.truecolor."
        urls=[prefix+x+".jpg" for x in ["20261009.164618","20261009.164118","20261009.164618","20261009.170118","20261309.164118"]]
        html=" ".join(urls)+" "+BASE+"/dcphase/S_Minnesota.dcphase.20261009.164118.jpg"
        data=parse_loop(html,"truecolor",NOW)
        self.assertEqual([x["time"] for x in data["frames"]],["2026-10-09T16:41:18Z","2026-10-09T16:46:18Z"])
        self.assertEqual(data["product"],"truecolor")

    def test_only_state_and_county_overlays_are_selected(self):
        html=BASE+"/ntmicro/S_Minnesota.ntmicro.20261009.164618.jpg"
        html+=" "+BASE+"/maps/S_Minnesota_counties.png?v=123"
        html+=" "+BASE+"/maps/S_Minnesota_map.png?v=456"
        html+=" "+BASE+"/maps/S_Minnesota_cities.png"
        data=parse_loop(html,"ntmicro",NOW)
        self.assertEqual(len(data["boundaries"]),2)
        self.assertTrue(all("cities" not in x for x in data["boundaries"]))

    def test_invalid_product_and_empty_loop_do_not_fetch_arbitrary_urls(self):
        with self.assertRaises(ValueError): page_url("../../evil")
        with self.assertRaises(ValueError): parse_loop("","dcphase",NOW)
        with patch("app.download") as fetch:
            self.assertEqual(app.test_client().get("/api/satellite/unknown").status_code,404)
            fetch.assert_not_called()

if __name__ == "__main__": unittest.main()
