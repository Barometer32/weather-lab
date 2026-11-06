from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from app import app
from nbm import KEY, collect, daily_outlook, parse_extended, parse_station

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
    collect(store, CYCLE + timedelta(minutes=50), lambda _: (rows, [{"endAt": (CYCLE + timedelta(days=1)).isoformat()}], 264))
    before = store.read_json(KEY).copy()

    def unavailable(_):
        raise HTTPError("https://example.test", 404, "not published", {}, None)

    assert collect(store, CYCLE + timedelta(hours=1, minutes=50), unavailable)["status"] == "current bulletin retained"
    assert store.read_json(KEY) == before


def test_api_hides_expired_rows_and_marks_old_cycle():
    store = Store()
    days = [{"endAt": (CYCLE + timedelta(hours=1)).isoformat()},
            {"endAt": (CYCLE + timedelta(days=1)).isoformat()}]
    collect(store, CYCLE + timedelta(minutes=50), lambda _: (parse_station(station_card(), CYCLE), days, 264))
    with patch("app.prepared_snapshot", return_value={**store.read_json(KEY), "stale": False}), patch("app.utcnow", return_value=CYCLE+timedelta(hours=2, minutes=5)):
        response = app.test_client().get("/api/nbm")
    assert response.status_code == 200
    assert response.json["station"] == "KFCM"
    assert response.json["stale"] is True
    assert response.json["hours"][0]["validAt"] == "2026-11-07T02:00:00+00:00"
    assert response.json["days"] == days[1:]


def test_far_range_columns_keep_blanks_and_ignore_climatology():
    cycle = CYCLE.replace(hour=0)
    labels = {
        "FHR": [192, 204, 216, 228, 240, 252, 264, ""],
        "UTC": ["00", "12", "00", "12", "00", "12", "00", ""],
        "TXN": [44, "", 43, 28, 45, 29, 41, 77],
        "Q12": [15, 0, "", 100, 0, 0, 0, 77],
        "S12": [0, 2, 0, 19, 0, 0, 0, 77],
    }
    lines = [b" KFCM   NBM V5.1 NBX GUIDANCE    11/06/2026  0000 UTC"]
    lines.extend(f" {label}  ".encode() + b"".join(f"{v:>4}".encode() for v in values)
                 for label, values in labels.items())
    rows = parse_extended(lines, cycle, "NBX")
    assert [r["extremeF"] for r in rows] == [44, None, 43, 28, 45, 29, 41]
    assert rows[2]["liquidPrecipHundredths"] is None
    assert rows[3]["snowTenths"] == 19
    assert rows[-1]["validAt"] == "2026-11-17T00:00:00+00:00"


def test_complete_day_and_night_use_each_periods_samples_and_precip():
    cycle = CYCLE.replace(hour=12)

    def point(hours, **fields):
        return {"validAt": (cycle + timedelta(hours=hours)).isoformat(), **fields}

    hourly = [point(h, temperatureF=30+h, cloudCoverPct=h*5) for h in range(13)]
    short = [point(6, liquidPrecipHundredths=90), point(12, liquidPrecipHundredths=80)]
    extended = [
        point(12, temperatureF=42, extremeF=46, cloudCoverPct=60, precipChancePct=65,
              liquidPrecipHundredths=30, snowTenths=0, rainTypePct=90),
        point(24, temperatureF=28, extremeF=25, cloudCoverPct=100, precipChancePct=80,
              liquidPrecipHundredths=10, snowTenths=15, snowTypePct=80),
        point(36, temperatureF=43, cloudCoverPct=40, precipChancePct=35, snowTenths=0),
    ]
    [first] = daily_outlook(cycle, hourly, short, extended)
    day, night = first["periods"]
    assert first["date"] == "2026-11-06"
    assert day["endAt"] == night["startAt"] == "2026-11-07T00:00:00+00:00"
    assert (day["highF"], day["lowF"], day["cloudPct"]) == (46, None, 30)
    assert (night["highF"], night["lowF"], night["cloudPct"]) == (None, 25, 80)
    assert day["cloudBlocks"] == [8, 22, 38, 52]
    assert (day["liquidPrecipHundredths"], night["liquidPrecipHundredths"]) == (30, 10)
    assert day["precipTypes"] == ["rain"]
    assert night["precipTypes"] == ["snow"]
    assert (day["peakPrecipChancePct"], night["peakPrecipChancePct"]) == (65, 80)
    assert night["snowTenths"] == 15
    assert night["sparse"] and not day["sparse"]


def test_includes_current_day_caps_ten_and_honors_central_daylight_time():
    cycle = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
    points = [{"validAt": (cycle + timedelta(hours=h)).isoformat(), "temperatureF": 50,
               "cloudCoverPct": 70, "liquidPrecipHundredths": 12, "precipChancePct": 30}
              for h in range(12, 12*24+1, 12)]
    days = daily_outlook(cycle, [], [], points)
    assert len(days) == 10
    assert days[0]["date"] == "2026-07-01"
    assert days[0]["periods"][0]["startAt"] == cycle.isoformat()
    day, night = days[1]["periods"]
    assert day["startAt"] == "2026-07-02T11:00:00+00:00"
    assert day["endAt"] == "2026-07-02T23:00:00+00:00"
    assert night["endAt"] == "2026-07-03T11:00:00+00:00"
    assert day["liquidPrecipHundredths"] == 12 and day["amountsApproximate"]
    assert day["precipChanceApproximate"]
    assert day["snowTenths"] is None



def test_current_overnight_low_uses_that_nights_samples_when_bulletin_lacks_low():
    cycle = CYCLE.replace(hour=2)
    hourly = [{"validAt": (cycle + timedelta(hours=h)).isoformat(), "temperatureF": 37-h}
              for h in range(1, 11)]
    extended = [{"validAt": (cycle + timedelta(hours=h)).isoformat(), "extremeF": value}
                for h, value in [(22, 47), (34, 32)]]
    overnight, tomorrow = daily_outlook(cycle, hourly, [], extended)
    assert overnight["date"] == "2026-11-05"
    assert overnight["periods"][1]["lowF"] == 27
    assert overnight["periods"][1]["temperatureSource"] == "sampled"
    assert tomorrow["periods"][0]["highF"] == 47
    assert tomorrow["periods"][1]["lowF"] == 32
