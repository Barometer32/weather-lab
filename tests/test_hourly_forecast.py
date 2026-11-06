from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from collector import collect_forecast
from nws_forecast import POINT_URL, FORECAST_URL, SOURCE_URL, add_hourly_windows, enrich_from_nws, normalize_forecast
from test_forecast import document, text_page, NOW
from test_realtime import MemoryStore


START = datetime(2026, 10, 9, 17, tzinfo=timezone.utc)
GRID = "https://api.weather.gov/gridpoints/MPX/104,70"


def hourly():
    hours = [(0, "Chance Rain Showers", 30), (1, "Chance Rain Showers", 50),
             (2, "Rain Showers Likely", 70), (4, "Rain Showers Likely", 70),
             (5, "Mostly Cloudy", None)]
    return {"properties": {"updateTime": NOW.isoformat(), "periods": [
        {"startTime": (START + timedelta(hours=offset)).isoformat(),
         "endTime": (START + timedelta(hours=offset + 1)).isoformat(),
         "shortForecast": condition, "probabilityOfPrecipitation": {"value": chance}}
        for offset, condition, chance in hours]}}


def test_optional_hourly_helper_does_not_interpolate_or_invent_intensity():
    grid = {"properties": {"weather": {"values": [
        {"validTime": START.isoformat() + "/PT2H",
         "value": [{"weather": "rain_showers", "coverage": "scattered", "intensity": "light"}]},
        {"validTime": (START + timedelta(hours=2)).isoformat() + "/PT3H",
         "value": [{"weather": "rain_showers", "coverage": "likely", "intensity": None}]},
    ]}}}
    responses = {POINT_URL: {"properties": {"forecastHourly": GRID + "/forecast/hourly", "forecastGridData": GRID}},
                 FORECAST_URL: document(), GRID: grid, GRID + "/forecast/hourly": hourly()}
    saved = normalize_forecast(document(), NOW)
    enrich_from_nws(saved, lambda url: responses[url], NOW)
    windows = saved["periods"][0]["hourlyWindows"]
    assert [(w["minChancePct"], w["maxChancePct"]) for w in windows] == [(30, 50), (70, 70), (70, 70), (None, None)]
    assert windows[0]["weather"] == ["Scattered rain showers (light)"]
    assert windows[1]["weather"] == ["Rain showers likely"]
    assert windows[1]["endTime"] < windows[2]["startTime"]
    assert saved["periods"][0]["detailedForecast"] == document()["data"]["text"][0]


def test_grid_failure_uses_only_the_hourly_conditions_and_missing_chance_stays_missing():
    data = {"periods": [{"startTime": START.isoformat(), "endTime": (START+timedelta(hours=6)).isoformat()}]}
    add_hourly_windows(data, hourly(), {}, NOW)
    windows = data["periods"][0]["hourlyWindows"]
    assert windows[0]["condition"] == "Chance Rain Showers"
    assert windows[0]["weather"] == []
    assert windows[-1]["maxChancePct"] is None


def test_collector_fetches_only_the_official_point_forecast():
    store = MemoryStore()
    narrative = "Sunny, with a high near 74."
    with patch("app.download", return_value=text_page(periods=[("This Afternoon", narrative)]).encode()) as download:
        collect_forecast(store, NOW)
    download.assert_called_once_with(SOURCE_URL)
    period = store.read_json("live/forecast.json")["periods"][0]
    assert "hourlyWindows" not in period
    assert period["detailedForecast"] == narrative
