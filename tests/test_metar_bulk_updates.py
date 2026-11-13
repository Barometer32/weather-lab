"""Bulk checks advance official hourly maps without a full archive download."""
from datetime import timedelta
from unittest.mock import patch

import pytest
import collector
import metar_clouds as metar
from test_metar_history_restore import HOUR, Store, archive, xml, xml_report


def saved_store():
    store = Store()
    saved = metar.snapshot(archive(5)["reports"], HOUR)
    saved.update(collectionMode="official-hourly-archive", hourlyTarget=metar.iso(HOUR))
    store.data["live/metar-clouds.json"] = saved
    return store


@pytest.mark.parametrize("minute", [0, 2, 20, 22, 58])
def test_one_bulk_download_advances_the_hour_at_each_two_minute_check(minute):
    store = saved_store()
    target = HOUR + timedelta(hours=1)
    observed = target - timedelta(minutes=7)
    payload = xml(xml_report(observed).replace("15/10", "15/10 RMK T01540102"))
    with patch("collector.weather.download", return_value=payload) as bulk, patch("metar_history.fetch_history") as slow:
        collector.collect_metar_clouds(store, target+timedelta(minutes=minute))
    bulk.assert_called_once_with(metar.SOURCE_URL)
    slow.assert_not_called()
    saved = store.data["live/metar-clouds.json"]
    assert saved["collectionFeed"] == "awc-bulk-cache"
    loop = store.data[metar.LOOP_KEY]
    assert loop["history"][-1]["hour"] == metar.iso(target)
    assert len(loop["history"]) == 4
    row = loop["history"][-1]["stations"][0]
    assert row["time"] == metar.iso(observed)
    assert row["tempF"] == 59.7 and row["dewpointF"] == 50.4


def test_one_missing_metro_report_does_not_hold_other_airports_in_old_hour():
    store = saved_store()
    target = HOUR + timedelta(hours=1)
    payload = xml(xml_report(target-timedelta(minutes=7), station="KSTP"))
    with patch("collector.weather.download", return_value=payload), patch("metar_history.fetch_history") as source:
        collector.collect_metar_clouds(store, target+timedelta(minutes=2))
    source.assert_not_called()
    assert store.data["live/metar-clouds.json"]["collectionFeed"] == "awc-bulk-cache"
    frames = store.data[metar.LOOP_KEY]["history"]
    assert frames[-1]["hour"]==metar.iso(target)
    assert [s["station"] for s in frames[-1]["stations"]]==["KSTP"]
    assert any(s["station"]=="KMSP" for s in frames[-2]["stations"])


@pytest.mark.parametrize("error", [TimeoutError("bulk timeout"), EOFError("truncated gzip"), ValueError("bad bulk response")])
def test_bulk_failure_still_recovers_current_hour_from_the_official_archive(error):
    store = saved_store()
    target = HOUR + timedelta(hours=1)
    complete = metar.parse_reports(xml(xml_report(target-timedelta(minutes=7))), target)
    with patch("collector.weather.download", side_effect=error), patch("metar_history.fetch_history", return_value={"reports": complete}) as source:
        collector.collect_metar_clouds(store, target+timedelta(minutes=2))
    assert source.call_args.kwargs == {"hours": 2}
    assert store.data[metar.LOOP_KEY]["history"][-1]["hour"] == metar.iso(target)


def test_later_correction_is_published_after_20_without_duplicate_slot_downloads():
    store = saved_store()
    first = xml(xml_report(HOUR-timedelta(minutes=7)))
    corrected = first.replace(b"<temp_c>15</temp_c>", b"<temp_c>17</temp_c>")
    with patch("collector.weather.download", side_effect=[first, corrected]) as source:
        collector.collect_metar_clouds(store, HOUR+timedelta(minutes=22))
        collector.collect_metar_clouds(store, HOUR+timedelta(minutes=23))
        assert source.call_count == 1
        collector.collect_metar_clouds(store, HOUR+timedelta(minutes=24))
    assert source.call_count == 2
    assert store.data[metar.LOOP_KEY]["history"][-1]["stations"][0]["tempF"] == 62.6


def test_current_canonical_republishes_an_old_loop_without_fetching_again():
    store = saved_store()
    old = metar.prepared_loop(store.data["live/metar-clouds.json"])
    store.data[metar.LOOP_KEY] = old
    store.data["live/metar-clouds.json"]["checkedAt"] = metar.iso(HOUR+timedelta(minutes=24))
    with patch("collector.weather.download") as source:
        collector.collect_metar_clouds(store, HOUR+timedelta(minutes=25))
    source.assert_not_called()
    assert store.data[metar.LOOP_KEY]["checkedAt"] == metar.iso(HOUR+timedelta(minutes=24))
