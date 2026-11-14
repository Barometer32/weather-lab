from datetime import datetime, timedelta, timezone
import gzip
import json
from unittest.mock import patch
import pytest
import app
import public_conditions as p

NOW = datetime(2026, 11, 14, 22, 0, tzinfo=timezone.utc)

def row(station="HPN20", **changes):
    return {"station": station, "name": station, "lat": 44.95, "lon": -93.41,
            "time": p.iso(NOW-timedelta(minutes=5)), "tempF": 40.0, "dewpointF": 25.0,
            "network": "Hennepin West", "source": "NOAA MADIS", "wind": {"speedMph": 5, "direction": 350}, **changes}

def test_state_boundaries_exclude_neighboring_states_and_accept_both_states():
    assert p.state_at(44.95, -93.41) == "MN"
    assert p.state_at(43.0731, -89.4012) == "WI"
    assert p.state_at(41.6, -93.6) is None
    assert p.state_at(47.9, -97.1) is None
    assert p.state_at(float("nan"), -93) is None

def test_duplicate_deliveries_aliases_and_bad_qc_cannot_get_extra_votes():
    old = row(time=p.iso(NOW-timedelta(minutes=10)))
    revised = row(tempF=None, dewpointF=None)
    assert p.latest([old, revised], NOW)[0]["tempF"] is None
    direct = row("WISC:TEST", aliases=["WITST"], network="Wisconet", lat=43.07, lon=-89.4)
    madis = row("WITST", network="MesoWest", lat=43.07, lon=-89.4)
    result = p.latest([madis, direct, row("FUTURE", time=p.iso(NOW+timedelta(minutes=1))), row("OLD", time=p.iso(NOW-timedelta(days=2)))], NOW)
    assert len(result) == 1 and result[0]["station"] == "WISC:TEST"

def test_wisconet_preserves_measurement_time_and_ignores_hourly_fields():
    meta = [{"station_id": "TEST", "latitude": 43.07, "longitude": -89.4, "madis_id": "WITST", "station_name": "Test"}]
    stamp = (NOW-timedelta(minutes=5)).timestamp()
    summaries = [{"current": [
        {"station_id": "TEST", "collection_time": stamp, "standard_name": "5min_air_temp_f_avg", "value": 42.1},
        {"station_id": "TEST", "collection_time": stamp-300, "standard_name": "5min_dew_point_f_avg", "value": 30},
        {"station_id": "TEST", "collection_time": stamp, "standard_name": "60min_air_temp_f_avg", "value": 80},
    ]}]
    result = p.latest(p.wisconet_rows(meta, summaries, NOW), NOW)
    assert len(result) == 1 and result[0]["tempF"] == 42.1
    assert result[0]["dewpointF"] is None and result[0]["time"] == p.iso(NOW-timedelta(minutes=5))

def test_public_route_reads_only_prepared_data_and_does_not_receive_location():
    saved = {"version": p.VERSION, "checkedAt": p.iso(NOW), "stations": [p.normalize(row(), NOW)], "sources": {}, "files": {"cache": {}}, "sourceFailures": []}
    app._cache.pop("prepared-public-conditions", None)
    with patch("app.get_store") as storage, patch("app.download") as upstream, patch("app.utcnow", return_value=NOW):
        storage.return_value.read_json.return_value = saved
        response = app.app.test_client().get("/api/conditions", headers={"Accept-Encoding": "gzip"})
    upstream.assert_not_called()
    data = json.loads(gzip.decompress(response.data))
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert "files" not in data and "lat" not in data and not data["collectorDelayed"]
    assert response.headers["Permissions-Policy"] == "geolocation=(self)"
    app._cache.pop("prepared-public-conditions", None)

def test_source_outage_preserves_prior_inventory_without_resetting_its_age():
    class Store:
        def __init__(self):
            self.saved = {"version": p.VERSION, "checkedAt": p.iso(NOW-timedelta(minutes=10)), "stations": [row()]}
            self.writes = 0
        def read_json(self, key): return self.saved
        def write_json(self, key, value): self.writes += 1
    def offline(*args): raise OSError("offline")
    storage = Store()
    with pytest.raises(ValueError, match="All public feeds failed"):
        p.collect(storage, NOW, download=offline)
    assert storage.writes == 0
    assert p.present(storage.saved, NOW)["collectorDelayed"]

def test_new_conditions_job_uses_existing_authenticated_identity_and_has_rollback():
    from configure_live_jobs import plan
    existing = [{"name": "projects/p/locations/r/jobs/weather-live-metar-clouds", "httpTarget": {"oidcToken": {"serviceAccountEmail": "scheduler@example.com"}}}]
    commands, rollback = plan(existing, "p", "r", "https://collector.example")
    assert commands[0][:6] == ["gcloud", "scheduler", "jobs", "create", "http", "weather-live-public-conditions"]
    assert "--oidc-service-account-email=scheduler@example.com" in commands[0]
    assert "--schedule=*/2 * * * *" in commands[0]
    assert rollback[0][:5] == ["gcloud", "scheduler", "jobs", "delete", "weather-live-public-conditions"]

def test_conditional_source_refresh_reuses_rows_and_keeps_only_public_five_minute_asos(monkeypatch):
    class Store:
        saved = None
        def read_json(self, key): return self.saved
        def write_json(self, key, value): self.saved = value
    storage = Store()
    calls = []
    def download(url, previous=None):
        calls.append((url, previous))
        if previous:
            return None, previous
        if url == p.WISCONET+"stations/":
            return b'[{"station_id":"TEST","latitude":43.07,"longitude":-89.4}]', {}
        if url == p.WISCONET+"stations/current_summaries":
            return json.dumps([{"current":[{"station_id":"TEST","collection_time":NOW.timestamp()-300,"standard_name":"5min_air_temp_f_avg","value":42}]}]).encode(), {}
        return url.encode(), {"etag": "source-version"}
    def parse(payload, now, **kwargs):
        assert kwargs["sensor_status_checks"] and kwargs["include_invalid"]
        if b"hfmetar" in payload:
            return [row("KMSP"), row("NOTALLOWED", time=p.iso(NOW-timedelta(minutes=4)))]
        return [row()]
    monkeypatch.setattr(p.regional_madis, "parse_file", parse)
    monkeypatch.setattr(p, "awc_rows", lambda payload, now: [row("KFCM", network="ASOS/AWOS")])
    p.collect(storage, NOW, download=download)
    assert "NOTALLOWED" not in {r["station"] for r in storage.saved["stations"]}
    assert {"KMSP", "KFCM", "HPN20", "WISC:TEST"} <= {r["station"] for r in storage.saved["stations"]}
    first = storage.saved["stations"]
    p.collect(storage, NOW, download=download)
    assert storage.saved["stations"] == first
    assert sum(bool(previous) for _, previous in calls) == 6

def test_existing_paused_conditions_schedule_can_be_restored_without_deleting_it():
    from configure_live_jobs import plan
    job = {"name":"weather-live-public-conditions", "schedule":"*/5 * * * *", "state":"PAUSED", "attemptDeadline":"180s",
           "httpTarget":{"uri":"https://collector.example/collect/public-conditions", "oidcToken":{"serviceAccountEmail":"scheduler@example.com"}}}
    commands, rollback = plan([job], "p", "r", "https://collector.example")
    assert commands[-1][2:5] == ["jobs", "resume", "weather-live-public-conditions"]
    assert "--schedule=*/5 * * * *" in rollback[0] and "--attempt-deadline=180s" in rollback[0]
    assert rollback[-1][2:5] == ["jobs", "pause", "weather-live-public-conditions"]
    assert not any("delete" in command for command in rollback)
