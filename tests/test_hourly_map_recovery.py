"""Outage recovery and prepared-only serving for the retained hourly maps."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import app
import collector
import metar_clouds as metar
from test_metar_history_restore import HOUR, Store, archive


def shutdown_gap():
    data = metar.snapshot(archive(3)["reports"], HOUR, metar.iso(HOUR))
    data.update(collectionMode="official-hourly-archive", hourlyTarget=metar.iso(HOUR))
    return data


def test_populated_current_hour_with_shutdown_gaps_is_repaired_after_catchup_deadline():
    store = Store()
    store.data["live/metar-clouds.json"] = shutdown_gap()
    assert metar.prepared_loop(store.data["live/metar-clouds.json"]) is None
    with patch("metar_history.fetch_history", return_value=archive(5)) as source:
        result = collector.collect_metar_clouds(store, HOUR + timedelta(minutes=25))
    assert source.call_args.kwargs == {"hours": 5}
    assert result["loopReady"]
    loop = store.data[metar.LOOP_KEY]
    assert len(loop["history"]) == 4
    assert all(f["stations"] for f in loop["history"])
    assert loop["history"][-1]["hour"] == metar.iso(HOUR)
    assert loop["history"][-1]["stations"][0]["time"] == metar.iso(HOUR-timedelta(minutes=7))
    assert "rawOb" not in loop["history"][-1]["stations"][0]


def test_healthy_window_seeds_fast_payload_without_another_noaa_request():
    store = Store()
    store.data["live/metar-clouds.json"] = metar.snapshot(archive(5)["reports"], HOUR)
    store.data["live/metar-clouds.json"].update(collectionMode="official-hourly-archive", hourlyTarget=metar.iso(HOUR))
    with patch("metar_history.fetch_history") as source:
        collector.collect_metar_clouds(store, HOUR + timedelta(minutes=25))
        collector.collect_metar_clouds(store, HOUR + timedelta(minutes=30))
    source.assert_not_called()
    assert store.writes == [metar.LOOP_KEY]


def test_incomplete_recovery_never_erases_previously_usable_loop():
    store = Store()
    store.data["live/metar-clouds.json"] = shutdown_gap()
    previous = metar.prepared_loop(metar.snapshot(archive(5)["reports"], HOUR))
    store.data[metar.LOOP_KEY] = deepcopy(previous)
    with patch("metar_history.fetch_history", return_value=archive(3)):
        result = collector.collect_metar_clouds(store, HOUR + timedelta(minutes=25))
    assert not result["loopReady"]
    assert store.data[metar.LOOP_KEY] == previous
    assert metar.LOOP_KEY not in store.writes


def test_fast_api_reads_only_prepared_loop_and_still_labels_stale_data():
    saved = metar.prepared_loop(metar.snapshot(archive(5)["reports"], HOUR))
    store = Store()
    store.data[metar.LOOP_KEY] = saved
    for elapsed, stale in [(timedelta(minutes=25), False), (timedelta(hours=2), True)]:
        app._cache.clear()
        with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=HOUR+elapsed), \
             patch.object(store, "read_json", wraps=store.read_json) as reads, \
             patch("metar_clouds.current") as rebuild, patch("app.download") as source:
            response = app.app.test_client().get("/api/station-plots?view=loop")
        assert response.status_code == 200
        assert response.json["history"] == saved["history"]
        assert response.json["stale"] is stale
        assert [c.args[0] for c in reads.call_args_list] == [metar.LOOP_KEY]
        rebuild.assert_not_called()
        source.assert_not_called()


def test_unready_history_is_a_retryable_error_instead_of_empty_success():
    store = Store()
    store.data["live/metar-clouds.json"] = shutdown_gap()
    app._cache.clear()
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=HOUR), patch("app.download") as source:
        response = app.app.test_client().get("/api/station-plots?view=loop")
    assert response.status_code == 503
    assert response.json["historyPending"] is True
    assert "recovering in the background" in response.json["error"]
    assert response.headers["Cache-Control"] == "no-store"
    source.assert_not_called()


def test_fresh_collector_check_does_not_make_an_old_observation_window_current():
    saved = metar.prepared_loop(metar.snapshot(archive(5)["reports"], HOUR))
    now = HOUR + timedelta(hours=3, minutes=25)
    saved["checkedAt"] = metar.iso(now)
    store = Store()
    store.data[metar.LOOP_KEY] = saved
    app._cache.clear()
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=now):
        response = app.app.test_client().get("/api/station-plots?view=loop")
    assert response.status_code == 200
    assert response.json["stale"] is True
    assert response.json["history"] == saved["history"]
