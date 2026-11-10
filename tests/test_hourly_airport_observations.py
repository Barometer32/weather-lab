from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import app
import collector
import hourly_airport_observations as obs


NOW = datetime(2026, 11, 10, 2, 3, tzinfo=timezone.utc)
HOUR = NOW.replace(minute=0)


class Store(dict):
    read_json = dict.get
    write_json = dict.__setitem__


def report(code, hour=HOUR, minute=53, *, remark="T00101005", kind="METAR", receipt=None):
    observed = hour - timedelta(minutes=60-minute)
    raw = f"{kind} {code} {observed:%d%H%M}Z 35010KT 10SM CLR 20/05 A2998 RMK AO2 {remark}"
    return {"icaoId": code, "obsTime": observed.timestamp(), "metarType": kind,
            "receiptTime": app.iso(receipt or observed), "rawOb": raw,
            "temp": 20, "dewp": 5, "wspd": 10, "wdir": 350 if code == "KFCM" else 10}


def test_strict_report_window_correction_and_t_remark():
    reports = [
        report("KFCM", minute=49, remark="T01900050"),
        report("KFCM", minute=59, remark="T10111020"),
        report("KMIC", minute=53, kind="SPECI", remark="T01900050"),
        report("KMIC", minute=50),
        report("KMSP", remark="T01900050"),
        report("KMSP", receipt=HOUR, remark="T00101005"),
        report("KSTP", remark="T01900050"),
        report("KFCM", hour=HOUR+timedelta(hours=1)),
    ]
    data = obs.present({"reports": reports}, NOW)
    assert len(data["history"]) == 12
    assert data["current"] is data["history"][0]
    assert data["current"]["hour"] == app.iso(HOUR)
    assert data["current"]["count"] == 3
    assert (data["current"]["tempF"], data["current"]["dewpointF"]) == (33, 30)
    assert data["current"]["wind"]["direction"] == 3
    assert [s["observedAt"][14:16] for s in data["current"]["stations"]] == ["59", "53", "50"]
    assert data["history"][-1]["hour"] == app.iso(HOUR-timedelta(hours=11))


def test_hourly_average_rounds_directly_from_metar_precision():
    rows = [report("KFCM", remark="T01130005"), report("KMSP", remark="T01140005"),
            report("KMIC", remark="T01140005")]
    for row in rows:
        row["wspd"] = 10
    rows[0]["wspd"] = 7
    # 52.46°F and about 10.36 mph, from the native Celsius and knot values.
    current = obs.present({"reports": rows}, NOW)["current"]
    assert current["tempF"] == 52
    assert current["wind"]["speedMph"] == 10


def test_no_body_temperature_fallback_and_no_partial_wind_average():
    rows = [report("KFCM", remark=""), report("KMSP"), report("KMIC")]
    data = obs.present({"reports": rows}, NOW)
    assert data["current"] is None
    current = data["history"][0]
    assert not current["complete"]
    assert current["tempF"] is None and current["dewpointF"] is None
    assert current["stations"][0]["tempF"] is None
    assert current["wind"]["speedMph"] == 12
    partial = obs.present({"reports": rows[:2]}, NOW)
    assert partial["current"] is None
    assert partial["history"][0]["count"] == 2
    assert partial["history"][0]["wind"]["speedMph"] is None


def test_new_hour_stays_pending_without_dropping_any_of_the_prior_twelve():
    prior = [report(station, hour=HOUR-timedelta(hours=i))
             for i in range(1, 13) for station in app.STATIONS]
    store = Store()
    store[obs.KEY] = {"reports": prior, "checkedAt": app.iso(NOW-timedelta(hours=1))}
    pending = obs.present(store[obs.KEY], NOW)
    assert pending["pendingHour"] == app.iso(HOUR)
    assert pending["history"][0]["hour"] == app.iso(HOUR-timedelta(hours=1))
    assert pending["history"][-1]["hour"] == app.iso(HOUR-timedelta(hours=12))
    assert all(hour["complete"] for hour in pending["history"])

    first_two = [report("KFCM"), report("KMSP")]
    with patch("app.download", side_effect=[json.dumps(first_two).encode(),
                                           json.dumps([report("KMIC")]).encode()]) as download:
        obs.collect(store, NOW)
        assert obs.present(store[obs.KEY], NOW)["pendingHour"]
        obs.collect(store, NOW+timedelta(minutes=2))
        assert obs.present(store[obs.KEY], NOW)["pendingHour"] is None
        assert obs.present(store[obs.KEY], NOW)["history"][0]["hour"] == app.iso(HOUR)
        # A historical gap does not keep polling for an already complete current hour.
        store[obs.KEY]["reports"] = [r for r in store[obs.KEY]["reports"]
                                     if r["obsTime"] > (HOUR-timedelta(hours=1)).timestamp()]
        assert obs.collect(store, NOW+timedelta(minutes=4))["status"] == "already prepared"
        assert download.call_count == 2


def test_official_archive_backfills_twelve_hours_and_retires_realtime_routes():
    store = Store()
    rows = [report(station, hour=HOUR-timedelta(hours=i))
            for i in range(12) for station in app.STATIONS]
    with patch("collector.get_store", return_value=store), patch("app.utcnow", return_value=NOW), \
            patch("app.download", return_value=json.dumps(rows).encode()) as download:
        private = collector.app.test_client()
        result = private.post("/collect/hourly-observations")
        assert result.json["result"]["reports"] == 36
        assert private.post("/collect/hourly-observations").json["result"]["status"] == "already prepared"
        assert private.post("/collect/mn-asos-audit").status_code == 404
        assert private.post("/collect/observation-stations").status_code == 404
        download.assert_called_once()
    url = urlparse(download.call_args.args[0])
    query = parse_qs(url.query)
    assert url.hostname == "aviationweather.gov" and set(query["ids"][0].split(",")) == set(app.STATIONS)
    assert query["date"] == [app.iso(HOUR)]
    cache_key = "prepared-hourly-airport-observations"
    app._cache.pop(cache_key, None)
    try:
        with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=NOW):
            public = app.app.test_client()
            result = public.get("/api/observations/hourly")
            assert result.headers["Cache-Control"] == "no-store"
            assert len(result.json["history"]) == 12
            assert all(hour["count"] == 3 and hour["tempF"] == 34 for hour in result.json["history"])
            compact = public.get("/api/observations/hourly?view=table")
            assert compact.headers["Cache-Control"] == "no-store"
            assert len(compact.json["history"]) == 12
            assert compact.json["history"][0]["tempF"] == result.json["history"][0]["tempF"]
            assert "stations" not in compact.json["history"][0]
            assert len(compact.data) < len(result.data) / 3
            assert public.get("/api/observations/mesonet").status_code == 404
            assert public.get("/api/observations/rolling").status_code == 404
    finally:
        app._cache.pop(cache_key, None)
