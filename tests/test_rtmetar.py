import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import app
import collector
import rtmetar as rt

NOW = datetime(2026, 11, 11, 14, 12, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.data = {}

    def read_json(self, key):
        return self.data.get(key)

    def write_json(self, key, value):
        self.data[key] = value


def payload(*entries):
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["station", "valid", "lon", "lat", "metar"])
    writer.writerows(entries)
    return stream.getvalue().encode()


def row(station="MSP", minute=10, temperature="M02/M05", remarks="T00990088 MADISHF", hour=14, **values):
    raw = f"K{station} 11{hour:02}{minute:02}Z AUTO 27007KT 10SM CLR {temperature} A3000 RMK {remarks}"
    return [station, f"2026-11-11 {hour:02}:{minute:02}", values.get("lon", -93.23),
            values.get("lat", 44.88), values.get("raw", raw)]


def test_body_celsius_only_and_mph_without_using_t_remark_or_fahrenheit():
    rows = rt.parse_reports(payload(row(), row("MIC", temperature="10/02")), "MN", NOW)
    assert [(s["tempC"], s["dewpointC"]) for s in rows] == [(-2, -5), (10, 2)]
    assert abs(rows[0]["wind"]["speedMph"] - 8.05546) < .0001
    assert rows[0]["wind"]["direction"] == 270
    assert "tempF" not in rows[0] and "speedKnots" not in rows[0]["wind"]
    assert all(s["temperatureBasis"] == "main-XX/XX" for s in rows)


def test_only_marked_five_minute_reports_no_hourly_speci_or_timestamp_guessing():
    entries = [row(), row("MIC", minute=0, remarks="AO2 T01110022"),
               row("FCM", minute=53), row("MKT", raw=row("MKT")[4].replace("KMKT", "SPECI KMKT", 1)),
               row("STP", minute=15), row("RST", raw=row("RST")[4].replace("111410Z", "111405Z")),
               row("DLH", lat=55), row("BRD", minute=10, hour=12)]
    assert [s["station"] for s in rt.parse_reports(payload(*entries), "MN", NOW)] == ["KMSP"]


def test_missing_body_never_falls_back_to_remark_and_missing_dewpoint_stays_missing():
    reports = rt.parse_reports(payload(row(temperature=""), row("MIC", temperature="10///")), "MN", NOW)
    assert reports[0]["tempC"] is None and reports[0]["dewpointC"] is None
    assert reports[1]["tempC"] == 10 and reports[1]["dewpointC"] is None


def test_five_state_request_filter_and_latest_per_station_and_failure_retention():
    store = Store()
    calls = []
    def download(url):
        calls.append(url)
        q = parse_qs(urlparse(url).query)
        assert q["report_type"] == ["1"] and q["data"] == ["metar"]
        assert set(q["network"][0].split(",")) == {state+"_ASOS" for state in rt.STATES}
        return payload(*(row(station, minute=minute) for station in ["MSP", "FAR", "DSM", "MSN", "FSD", "ORD"] for minute in [5,10,0]))
    result = rt.collect(store, NOW, download)
    assert result["stations"] == 5 and len(calls) == 1
    data = rt.present(store.data[rt.KEY], NOW)
    assert {s["state"] for s in data["stations"]} == set(rt.STATES)
    assert all(s["time"].endswith("14:10:00Z") for s in data["stations"])
    assert not data["stale"]
    before = store.data[rt.KEY]
    with patch("rtmetar.source_url", side_effect=OSError("offline")):
        try:
            rt.collect(store, NOW)
        except OSError:
            pass
        else:
            raise AssertionError("Source failure must retain the saved snapshot")
    assert store.data[rt.KEY] is before


def test_expiry_delay_flags_and_no_renewing_source_age_on_successful_check():
    store = Store()
    rt.collect(store, NOW, lambda _: payload(row(minute=0, hour=14)))
    assert not rt.present(store.data[rt.KEY], NOW)["sourceDelayed"]
    data = rt.present(store.data[rt.KEY], NOW + timedelta(minutes=5))
    assert data["sourceDelayed"] and data["stations"][0]["delayed"]
    assert data["stations"][0]["time"] == "2026-11-11T14:00:00Z"
    assert rt.present(store.data[rt.KEY], NOW + timedelta(minutes=49))["stations"] == []


def test_prepared_only_endpoint_and_removed_observations_and_collector_routes():
    store = Store()
    rt.collect(store, NOW, lambda _: payload(row()))
    app._cache.clear()
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=NOW), patch("app.download") as download:
        client = app.app.test_client()
        response = client.get("/api/rtmetar")
        assert response.status_code == 200 and response.json["temperatureUnit"] == "C"
        assert response.headers["Cache-Control"] == "no-store"
        assert client.get("/api/observations").status_code == 404
        assert client.get("/api/observations/hourly").status_code == 404
        download.assert_not_called()
    app._cache.clear()
    with patch("app.get_store", return_value=None), patch("app.download") as download:
        assert app.app.test_client().get("/api/rtmetar").status_code == 503
        download.assert_not_called()
    with patch("collector.get_store", return_value=store), patch("app.utcnow", return_value=NOW), patch("rtmetar.collect", return_value={"stations": 1}) as collect:
        private = collector.app.test_client()
        assert private.post("/collect/rtmetar").status_code == 200
        collect.assert_called_once_with(store, NOW)
        assert private.post("/collect/hourly-observations").status_code == 404
    app._cache.clear()


def test_home_is_metar_default_rtmetar_without_observations_module():
    html = app.app.test_client().get("/").text
    assert 'id="tab-metar" aria-selected="true"' in html
    assert '<option value="rtmetar" selected>RTMETAR</option>' in html
    assert '<option value="plots">PLOTS</option>' in html
    assert '<option value="clouds">CLOUDS</option>' in html
    assert 'id="observations"' not in html and 'tab-observations' not in html
    assert 'hourly-observation-views.js' not in html and '/api/observations/hourly' not in html
