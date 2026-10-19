from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import json
import pytest

import app as weather
import collector
import metar_clouds
import metar_history

NOW = datetime(2026, 10, 19, 18, 2, tzinfo=timezone.utc)
HOUR = NOW.replace(minute=0)


def xml_report(stamp, station="KMSP", kind="METAR", layers=None):
    layers = layers if layers is not None else [("SCT", 1500), ("BKN", 2700), ("OVC", 5000)]
    skies = "".join(f'<sky_condition sky_cover="{cover}" cloud_base_ft_agl="{height}"/>' for cover, height in layers)
    return (f"<METAR><station_id>{station}</station_id><latitude>44.9</latitude><longitude>-93.4</longitude>"
            f"<observation_time>{stamp.isoformat()}</observation_time><metar_type>{kind}</metar_type>"
            f"<raw_text>{kind} {station} {stamp.strftime('%d%H%M')}Z 27010KT BKN027 OVC050 15/10</raw_text>"
            f"<temp_c>15</temp_c><dewpoint_c>10</dewpoint_c><wind_speed_kt>10</wind_speed_kt>"
            f"<wind_dir_degrees>270</wind_dir_degrees>{skies}</METAR>")


def xml(*reports):
    return ("<response><data>"+"".join(reports)+"</data></response>").encode()


class Store:
    def __init__(self):
        self.data = {}
        self.writes = []
    def read_json(self, name):
        return self.data.get(name)
    def write_json(self, name, data):
        self.data[name] = data
        self.writes.append(name)


def archive(hours=12):
    rows = metar_clouds.parse_reports(xml(*(xml_report(HOUR-timedelta(hours=i, minutes=7))
                                         for i in range(hours))), HOUR)
    return {"source": metar_history.SOURCE, "targetHour": metar_clouds.iso(HOUR), "reports": rows}


def test_twelve_real_hours_are_published_to_the_existing_api_with_clouds():
    store = Store()
    counts = metar_history.publish_history(archive(), store, NOW)
    assert len(counts) == 12 and all(frame["stations"] == 1 for frame in counts)
    saved = store.read_json("live/metar-clouds.json")
    assert store.writes == ["live/metar-clouds.json"]
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=NOW), patch("app.download") as upstream:
        weather._cache.clear()
        response = weather.app.test_client().get("/api/metar-clouds")
    assert response.status_code == 200
    upstream.assert_not_called()
    data = response.json
    assert len(data["history"]) == 12
    assert all(frame["stations"] for frame in data["history"])
    row = data["stations"][0]
    assert row["skyCover"]["code"] == "OVC"
    assert row["ceiling"]["baseFtAGL"] == 2700
    assert row["wind"]["speedMph"] == pytest.approx(11.5)
    assert row["tempF"] == 59


def test_empty_archive_hour_preserves_the_previous_canonical_object():
    store = Store()
    store.data["live/metar-clouds.json"] = {"saved": True}
    with pytest.raises(ValueError, match="saved history was not replaced"):
        metar_history.publish_history(archive(11), store, NOW)
    assert store.data["live/metar-clouds.json"] == {"saved": True}
    assert store.writes == []


def test_window_and_official_report_filter_selects_closest_to_53():
    reports = [xml_report(HOUR-timedelta(minutes=m)) for m in [1, 7, 10, 11, 20]]
    reports += [xml_report(HOUR-timedelta(minutes=7), station="KSPE", kind="SPECI"),
                xml_report(HOUR-timedelta(minutes=7), station="KHF1", kind="HFMETAR")]
    data = metar_clouds.snapshot(metar_clouds.parse_reports(xml(*reports), HOUR), HOUR)
    assert [row["station"] for row in data["stations"]] == ["KMSP"]
    assert data["stations"][0]["time"] == metar_clouds.iso(HOUR-timedelta(minutes=7))


@pytest.mark.parametrize("minute,expected", [(44,False),(45,True),(49,True),(50,True),(59,True),(0,False)])
def test_widened_window_boundaries_apply_to_canonical_and_public_history(minute, expected):
    stamp = (HOUR-timedelta(hours=1)).replace(minute=minute)
    rows = metar_clouds.parse_reports(xml(xml_report(stamp)), HOUR)
    data = metar_clouds.snapshot(rows, HOUR)
    public = metar_clouds.current(data, HOUR)
    assert bool(data["stations"]) is expected
    assert bool(public["stations"]) is expected
    if expected:
        assert data["stations"][0]["time"] == metar_clouds.iso(stamp)
        assert len(data["history"]) == 12


def test_earlier_report_fills_missing_station_without_replacing_preferred_53():
    stamps = [HOUR-timedelta(minutes=m) for m in [15,11,7]]
    rows = metar_clouds.parse_reports(xml(*(xml_report(t) for t in stamps),
        xml_report(stamps[0], station="KFCM"),
        xml_report(stamps[0], station="KSPE", kind="SPECI"),
        xml_report(stamps[0], station="KHF1", kind="HFMETAR")), HOUR)
    result = {r["station"]: r for r in metar_clouds.snapshot(rows, HOUR)["stations"]}
    assert set(result) == {"KMSP","KFCM"}
    assert result["KMSP"]["time"] == metar_clouds.iso(HOUR-timedelta(minutes=7))
    assert result["KFCM"]["time"] == metar_clouds.iso(HOUR-timedelta(minutes=15))


def test_archive_discovery_batches_split_at_the_noaa_cap():
    catalog = [{"icaoId": s, "lat": 44.9, "lon": -93.4} for s in ["KAAA", "KBBB"]]
    calls = []
    def download(url):
        calls.append(url)
        if url == metar_history.STATIONS_URL:
            return json.dumps(catalog).encode()
        ids = parse_qs(urlsplit(url).query)["ids"][0].split(",")
        return xml(*(xml_report(HOUR-timedelta(minutes=7), station=s) for s in ids))
    result = metar_history.fetch_history(download, NOW, limit=2, workers=1, pause=lambda _: None, interval=0)
    assert len(result["reports"]) == 2
    assert len(calls) == 4  # Metadata, capped parent, two complete children.


def test_cap_at_one_station_is_not_published_as_complete():
    def download(url):
        if url == metar_history.STATIONS_URL:
            return json.dumps([{"icaoId": "KAAA", "lat": 44.9, "lon": -93.4}]).encode()
        return xml(xml_report(HOUR-timedelta(minutes=7), station="KAAA"))
    with pytest.raises(ValueError, match="capped for one airport"):
        metar_history.fetch_history(download, NOW, limit=1, workers=1, pause=lambda _: None, interval=0)


def test_hourly_updates_request_one_hour_and_preserve_imported_history():
    store = Store()
    metar_history.publish_history(archive(), store, NOW)
    next_time = NOW+timedelta(hours=1)
    fresh = metar_clouds.parse_reports(xml(xml_report(HOUR+timedelta(minutes=53))), next_time)
    with patch("metar_history.fetch_history", return_value={"reports": fresh}) as read:
        collector.collect_metar_clouds(store, next_time)
        collector.collect_metar_clouds(store, next_time)
    assert read.call_count == 1
    assert read.call_args.kwargs == {"hours": 1}
    saved = store.read_json("live/metar-clouds.json")
    assert all(frame["stations"] for frame in saved["history"])
    assert saved["history"][-1]["hour"] == "2026-10-19T19:00:00Z"


def test_missing_sky_is_unknown_and_unknown_ceiling_is_not_invented():
    from cloud_conditions import summarize
    assert summarize({})["skyCover"]["displayFraction"] is None
    conditions = summarize({"layers": [{"cover": "BKN", "baseFtAGL": None}, {"cover": "OVC", "baseFtAGL": 5000}]})
    assert conditions["ceiling"]["baseFtAGL"] is None

