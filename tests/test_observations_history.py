"""Hourly observations reuse the reports saved by the cloud collector."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import app


NOW = datetime(2026, 11, 28, 4, 5, tzinfo=timezone.utc)
CODES = ("KMSP", "KFCM", "KMIC")
REMARKS = ("T00231010", "T00471020", "T00121030")


def reports(hours_ago, *, minute=53):
    previous = NOW.replace(minute=0) - timedelta(hours=hours_ago + 1)
    stamp = previous.replace(minute=minute)
    return [
        {"icaoId": code, "obsTime": stamp.timestamp(), "metarType": "METAR",
         "rawOb": f"{code} {stamp:%d%H%M}Z 10SM CLR 08/05 A3000 RMK {remark}",
         "wspd": speed, "wdir": direction, "temp": 8, "dewp": 5}
        for code, remark, speed, direction in zip(CODES, REMARKS, (10, 20, 10), (350, "VRB", 10))
    ]


def test_precision_and_variable_wind_use_three_complete_airport_reports():
    history = app.observation_history(reports(0), NOW)
    assert len(history) == 1
    row = history[0]
    assert row["hour"] == "2026-11-28T04:00:00Z"
    assert (row["tempF"], row["dewpointF"]) == (37, 28)
    assert row["wind"]["speedMph"] == 15
    assert row["wind"]["direction"] % 360 == 0


def test_incomplete_special_off_schedule_and_out_of_window_hours_are_skipped():
    special = reports(2)
    special[-1]["metarType"] = "SPECI"
    missing_precision = reports(4)
    missing_precision[-1]["rawOb"] = missing_precision[-1]["rawOb"].split(" RMK")[0]
    history = app.observation_history(
        reports(0)[:2] + reports(1) + special + reports(3, minute=49)
        + missing_precision + reports(11) + reports(12), NOW)
    assert [row["hour"] for row in history] == [app.iso(NOW.replace(minute=0) - timedelta(hours=i)) for i in (1, 11)]


def test_observations_api_reads_prepared_reports_without_source_download():
    prepared = {"checkedAt": app.iso(NOW), "observationReports": reports(0)}
    with patch("app.prepared_snapshot", return_value=prepared) as read, \
         patch("app.utcnow", return_value=NOW), patch("app.download") as download:
        response = app.app.test_client().get("/api/observations")
    assert response.status_code == 200
    assert response.json["history"] == app.observation_history(reports(0), NOW)
    assert response.headers["Cache-Control"] == "no-store"
    read.assert_called_once_with("metar-clouds", 3600)
    download.assert_not_called()
