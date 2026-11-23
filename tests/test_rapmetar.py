from datetime import datetime, timedelta, timezone
import gzip
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import numpy as np
import pytest
from scipy.io import netcdf_file

import app
import collector
import configure_live_jobs
import rapmetar

NOW = datetime(2026, 11, 23, 17, 15, tzinfo=timezone.utc)


def make_feed(path, rows):
    with netcdf_file(path, "w") as dataset:
        dataset.createDimension("record", len(rows))
        dataset.createDimension("id", 8)
        for name, values in (("stationId", [r[0] for r in rows]), ("stationType", [r[1] for r in rows])):
            field = dataset.createVariable(name, "c", ("record", "id"))
            field[:] = np.array([v.encode().ljust(8) for v in values], dtype="S8").view("S1").reshape(-1, 8)
        stamp = dataset.createVariable("observationTime", "d", ("record",))
        stamp[:] = [(NOW - timedelta(minutes=r[2])).timestamp() for r in rows]
        for name, unit, values in (
            ("temperature", b"kelvin", [r[3] for r in rows]),
            ("dewpoint", b"kelvin", [r[4] for r in rows]),
            ("windSpeed", b"meter/sec", [5] * len(rows)),
            ("windDir", b"degree", [315] * len(rows)),
        ):
            field = dataset.createVariable(name, "f", ("record",))
            field.units = unit
            field[:] = values
    return gzip.compress(path.read_bytes())


def test_only_five_minute_hf_asos_reports_in_the_five_states_are_published(tmp_path):
    good = [("KMSP", "HF-METAR", 5, 269.15, 263.15)] + [
        (station, "HF-METAR", 5, 270.15, 268.15)
        for station in ("KFCM", "KMIC", "KMKT", "KFAR", "KABR", "KDSM", "KMSN")
    ]
    rejected = [
        ("KSTP", "HF-METAR", 5, 270.15, 268.15),
        ("KORD", "HF-METAR", 5, 270.15, 268.15),
        ("KDLH", "METAR", 5, 270.15, 268.15),
        ("KRST", "SPECI", 5, 270.15, 268.15),
        ("KSTC", "HF-METAR", 7, 270.15, 268.15),
        ("KBRD", "HF-METAR", -5, 270.15, 268.15),
    ]
    payload = make_feed(tmp_path / "hf.nc", good + rejected)
    store = Mock()
    store.read_json.return_value = None
    rapmetar.collect(store, NOW, download=lambda _: payload)
    key, saved = store.write_json.call_args.args
    assert key == rapmetar.KEY
    result = rapmetar.present(saved, NOW)
    assert {s["station"] for s in result["stations"]} == {r[0] for r in good}
    assert {s["state"] for s in result["stations"]} == rapmetar.STATES
    msp = next(s for s in result["stations"] if s["station"] == "KMSP")
    assert (msp["tempC"], msp["dewpointC"], msp["wind"]["direction"]) == (-4, -10, 315)
    assert msp["wind"]["speedMph"] == pytest.approx(11.18468)
    assert result["newestObservationAt"] == "2026-11-23T17:10:00Z"

    app._cache.clear()
    store.read_json.return_value = saved
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=NOW), patch("rapmetar.fetch_file") as upstream:
        response = app.app.test_client().get("/api/rapmetar")
    assert response.status_code == 200 and response.json["temperatureUnit"] == "C"
    assert response.json["updateIntervalSeconds"] == 300
    upstream.assert_not_called()
    with patch("collector.get_store", return_value=store), patch("rapmetar.collect", return_value={"stations": 8}) as collect:
        assert collector.app.test_client().post("/collect/rapmetar").status_code == 200
    collect.assert_called_once()


def test_collection_keeps_saved_reports_on_upstream_failure_and_expires_them(tmp_path):
    payload = make_feed(tmp_path / "hf.nc", [
        ("KMSP", "HF-METAR", 10, 269.15, 263.15),
        ("KMSP", "HF-METAR", 5, 269.15, float("nan")),
        ("KFCM", "HF-METAR", 5, 269.15, 263.15),
    ])
    store = Mock()
    store.read_json.return_value = None
    rapmetar.collect(store, NOW, download=lambda _: payload)
    saved = store.write_json.call_args.args[1]
    assert [s["station"] for s in rapmetar.present(saved, NOW)["stations"]] == ["KFCM"]
    assert not rapmetar.present(saved, NOW + timedelta(hours=1))["stations"]
    store.reset_mock()
    limited = Mock(side_effect=HTTPError("https://example.com", 429, "rate limit", None, None))
    with pytest.raises(HTTPError):
        rapmetar.collect(store, NOW, download=limited)
    limited.assert_called_once()
    store.write_json.assert_not_called()


def test_missing_scheduler_job_is_created_with_a_five_minute_interval():
    base = "https://collector.example"
    jobs = [
        {"name": name, "state": "ENABLED", "schedule": "*/5 * * * *",
         "httpTarget": {"httpMethod": "POST", "uri": base + "/collect/" + endpoint,
                        "oidcToken": {"audience": base, "serviceAccountEmail": configure_live_jobs.ACCOUNT}}}
        for name, endpoint in configure_live_jobs.REQUIRED.items()
        if name != "weather-live-rapmetar"
    ]
    commands = configure_live_jobs.plan(jobs, base)
    create = next(command for command in commands if "create" in command)
    assert create[:6] == ["gcloud", "scheduler", "jobs", "create", "http", "weather-live-rapmetar"]
    assert {"--schedule=*/5 * * * *", "--uri=" + base + "/collect/rapmetar"} <= set(create)
