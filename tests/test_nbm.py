from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from app import app
from nbm import KEY, collect, parse_station

CYCLE = datetime(2026, 11, 6, 23, tzinfo=timezone.utc)


def row(label, values):
    return f" {label} ".encode() + b"".join(f"{v:>3}".encode() for v in values) + b"\n"


def station_card():
    return [
        b" KMSP   NBM  NBH GUIDANCE    11/06/2026  2300 UTC\n",
        b" KFCM   NBM  NBH GUIDANCE    11/06/2026  2300 UTC\n",
        row("UTC", [f"{h:02}" for h in range(24)] + ["00"]).rstrip() + b" \n",
        row("TMP", [-10, "", -8] + [0]*22),
        row("Q01", [0, 100, 110] + [0]*22),
        row("WSP", [0, -99, 12] + [0]*22),
        b" KMSP   NBM  NBH GUIDANCE    11/06/2026  2300 UTC\n",
        row("TMP", [99]*25),
    ]


class Store:
    def __init__(self):
        self.data = {}

    def read_json(self, key):
        return self.data.get(key)

    def write_json(self, key, value):
        self.data[key] = value


def test_hourly_station_parser_keeps_column_alignment_and_rolls_dates():
    rows = parse_station(station_card(), CYCLE)
    assert len(rows) == 25
    assert rows[0]["validAt"] == "2026-11-07T00:00:00+00:00"
    assert rows[-1]["validAt"] == "2026-11-08T00:00:00+00:00"
    assert [r["temperatureF"] for r in rows[:3]] == [-10, None, -8]
    assert [r["windKnots"] for r in rows[:3]] == [0, None, 12]
    assert [r["liquidPrecipHundredths"] for r in rows[:3]] == [0, 100, 110]
    with pytest.raises(ValueError, match="cycle"):
        parse_station(station_card(), CYCLE - timedelta(hours=1))


def test_unavailable_new_cycle_retains_prepared_bulletin():
    store = Store()
    rows = parse_station(station_card(), CYCLE)
    collect(store, CYCLE + timedelta(minutes=50), lambda _: rows)
    before = store.read_json(KEY).copy()

    def unavailable(_):
        raise HTTPError("https://example.test", 404, "not published", {}, None)

    assert collect(store, CYCLE + timedelta(hours=1, minutes=50), unavailable)["status"] == "current bulletin retained"
    assert store.read_json(KEY) == before


def test_api_hides_expired_rows_and_marks_old_cycle():
    store = Store()
    collect(store, CYCLE + timedelta(minutes=50), lambda _: parse_station(station_card(), CYCLE))
    with patch("app.prepared_snapshot", return_value={**store.read_json(KEY), "stale": False}), patch("app.utcnow", return_value=CYCLE+timedelta(hours=2, minutes=5)):
        response = app.test_client().get("/api/nbm")
    assert response.status_code == 200
    assert response.json["station"] == "KFCM"
    assert response.json["stale"] is True
    assert response.json["hours"][0]["validAt"] == "2026-11-07T02:00:00+00:00"
