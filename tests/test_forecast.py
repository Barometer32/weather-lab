import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import app, _cache
from nws_forecast import normalize_forecast, POINT_URL
from satellite import parse_loop, page_url, BASE

NOW = datetime(2026, 10, 9, 16, 50, tzinfo=timezone.utc)

def period(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=2), pop=0, name="Today"):
    return {"name": name, "startTime": start.isoformat(), "endTime": end.isoformat(),
            "isDaytime": True, "temperature": 74, "temperatureUnit": "F",
            "windSpeed": "10 to 15 mph", "windDirection": "SE",
            "shortForecast": "Sunny", "detailedForecast": "Sunny, with a high near 74.",
            "probabilityOfPrecipitation": {"value": pop}}

def document(periods):
    return {"properties": {"updateTime": "2026-10-09T13:21:39Z", "periods": periods}}

class ForecastTests(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def test_keeps_current_period_and_drops_completed_period(self):
        past = period(end=NOW)
        current = period()
        data = normalize_forecast(document([past,current]),NOW)
        self.assertEqual(len(data["periods"]),1)
        self.assertEqual(data["periods"][0]["detailedForecast"],current["detailedForecast"])
        self.assertEqual((data["latitude"],data["longitude"]),(44.9244,-93.414))

    def test_null_precip_is_not_zero_and_zero_is_preserved(self):
        data = normalize_forecast(document([period(pop=None),period(pop=0),period(pop=101)]),NOW)
        self.assertEqual([x["precipChancePct"] for x in data["periods"]],[None,0,None])

    def test_empty_forecast_does_not_look_like_success(self):
        with self.assertRaises(ValueError): normalize_forecast(document([]),NOW)

    def test_api_uses_point_discovery_and_caches_upstream(self):
        upstream = document([period()])
        with patch("app.utcnow", return_value=NOW), patch("app.download", side_effect=[
            json.dumps({"properties":{"forecast":"https://api.weather.gov/gridpoints/MPX/104,70/forecast"}}).encode(),
            json.dumps(upstream).encode()]) as download:
            client=app.test_client()
            self.assertEqual(client.get("/api/forecast").status_code,200)
            self.assertEqual(client.get("/api/forecast").status_code,200)
            self.assertEqual(download.call_count,2)
            self.assertEqual(download.call_args_list[0].args[0],POINT_URL)

    def test_api_rejects_unexpected_upstream_host(self):
        with patch("app.download", return_value=json.dumps({"properties":{"forecast":"https://example.org/forecast"}}).encode()) as download:
            self.assertEqual(app.test_client().get("/api/forecast").status_code,502)
            self.assertEqual(download.call_count,1)

    def test_upstream_error_is_reported(self):
        with patch("app.download",side_effect=TimeoutError):
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
