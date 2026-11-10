from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import app
import rolling_observations as obs


class Store:
    data = None

    def read_json(self, key):
        assert key == obs.KEY
        return self.data

    def write_json(self, key, data):
        assert key == obs.KEY
        self.data = data


def test_partial_top_of_hour_advances_history_with_previous_matched_set():
    now = datetime(2026, 11, 9, 18, 10, tzinfo=timezone.utc)
    hour = now.replace(minute=0)
    t = int(hour.timestamp())
    temperatures = dict(zip(obs.STATIONS, (14, 15, 15)))

    def raw(code, stamp, temp):
        return {"icaoId": code, "metarType": "HFMETAR", "obsTime": stamp,
                "temp": temp, "dewp": 3.99999, "wspd": 10, "wdir": 350 if code == "KFCM" else 10}

    complete_55 = [raw(code, t-300, temp) for code, temp in temperatures.items()]
    rows = complete_55 + [raw(code, t, temp+2) for code, temp in list(temperatures.items())[:2]]
    rows += [{**raw("KMSP", t, 20), "metarType": "METAR"}]
    with patch("madis_observations.parse_file", side_effect=lambda payload, *_args, **_kw: rows if payload == b"new" else []):
        store = Store()
        obs.prepare(store, now, [(hour, b"new")], archive_download=lambda _: b"old")
        output = obs.present(store.data, now)
        assert output["current"]["observedAt"] == obs.iso(t-300)
        assert (output["current"]["tempF"], output["current"]["dewpointF"]) == (58, 39)
        assert output["current"]["wind"]["direction"] == 3
        assert len(output["history"]) == 12
        assert output["history"][0]["time"] == obs.iso(t)
        assert output["history"][0]["reading"]["observedAt"] == obs.iso(t-300)
        assert output["history"][1]["reading"] is None

        rows.append(raw("KMSP", t, 17))
        obs.prepare(store, now, [(hour, b"new")], archive_download=lambda _: b"old")
        updated = obs.present(store.data, now)
        assert updated["current"]["observedAt"] == obs.iso(t)
        assert updated["history"][0]["reading"]["observedAt"] == obs.iso(t)
        assert obs.present(store.data, hour+timedelta(minutes=31))["current"] is None

    app._cache.pop("prepared-three-airport-observations", None)
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=now):
        client = app.app.test_client()
        assert client.get("/api/observations/rolling").status_code == 404
        assert client.get("/api/hrmetar").status_code == 404


def test_variable_wind_keeps_its_speed_but_not_its_direction():
    base = {"temp": 10, "dewp": 2}
    for no_bearing in ("VRB", None):
        reading = obs.summary(0, {
            "KFCM": {**base, "wspd": 5, "wdir": 350},
            "KMIC": {**base, "wspd": 5, "wdir": 10},
            "KMSP": {**base, "wspd": 20, "wdir": no_bearing},
        })
        assert reading["wind"]["speedMph"] == 12
        assert reading["wind"]["direction"] in (0, 360)
        assert not reading["wind"]["variable"]

    reading = obs.summary(0, {
        code: {**base, "wspd": 10, "wdir": "VRB"} for code in obs.STATIONS
    })
    assert reading["wind"] == {"speedMph": 12, "direction": None, "variable": True}


def test_qc_upgrade_reprocesses_a_previously_scanned_hour():
    now = datetime(2026, 11, 9, 19, 40, tzinfo=timezone.utc)
    prior = int(now.replace(hour=17, minute=0).timestamp())
    store = Store()
    store.data = {"scannedHours": [prior], "reports": [
        [prior, code, {"temp": 10, "dewp": 4, "wspd": None, "wdir": None}]
        for code in obs.STATIONS
    ]}
    urls = []

    def download(url):
        urls.append(url)
        return b"archive" if url.endswith("_1700.gz") else b"other"

    def parse(payload, stations, as_of, *, high_frequency_only, allow_advisory_wind):
        assert high_frequency_only and allow_advisory_wind
        return [{"icaoId": code, "metarType": "HFMETAR", "obsTime": prior,
                 "temp": 10, "dewp": 4, "wspd": 13, "wdir": 230}
                for code in stations] if payload == b"archive" else []

    with patch("madis_observations.parse_file", side_effect=parse):
        obs.prepare(store, now, [], archive_download=download)
        result = obs.present(store.data, now)
        assert result["windQcVersion"] == obs.WIND_QC_VERSION
        repaired = next(slot for slot in result["history"] if slot["time"] == obs.iso(prior))
        assert repaired["reading"]["wind"] == {
            "speedMph": 15, "direction": 230, "variable": False,
        }
        obs.prepare(store, now, [], archive_download=download)
        assert sum(url.endswith("_1700.gz") for url in urls) == 1
