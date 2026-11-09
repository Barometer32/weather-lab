from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import app
import hrmetar


class Store:
    def read_json(self, key):
        assert key == hrmetar.KEY
        return getattr(self, "snapshot", None)

    def write_json(self, key, snapshot):
        assert key == hrmetar.KEY
        self.snapshot = snapshot


def test_latest_by_airport_and_inclusive_30_minute_window():
    now = datetime(2026, 11, 9, 18, tzinfo=timezone.utc)
    t = now.timestamp()
    store = Store()

    def row(station, stamp, speed=10, temp=9.99999, kind="HFMETAR"):
        return {"icaoId": station, "obsTime": stamp, "metarType": kind,
                "lat": 44.9, "lon": -93.4, "name": station, "wspd": speed,
                "wdir": 260, "temp": temp, "dewp": -2.00001, "layers": []}

    with patch("madis_observations.parse_file", return_value=[
        row("KMSP", t-300), row("KMSP", t-600), row("KFCM", t-1800), row("KMIC", t-1801),
        row("KSTP", t+1), row("KFAR", t, speed=None, temp=10.4), row("KMSP", t, kind="METAR"),
    ]) as parser:
        assert hrmetar.prepare(store, now, [b"report"]) == 3
    assert "KCFE" not in parser.call_args.args[1]
    assert "KMSP" in parser.call_args.args[1] and "KFAR" in parser.call_args.args[1]
    assert parser.call_args.kwargs == {"high_frequency_only": True}
    result = hrmetar.present(store.snapshot, now)
    assert {r["station"]: r["observedEpoch"] for r in result["stations"]} == {
        "KMSP": t-300, "KFCM": t-1800, "KFAR": t,
    }
    assert result["temperatureUnit"] == "C"
    msp = next(r for r in result["stations"] if r["station"] == "KMSP")
    assert (msp["tempC"], msp["dewpointC"], msp["state"]) == (10, -2, "MN")
    far = next(r for r in result["stations"] if r["station"] == "KFAR")
    assert far["tempC"] is None and far["state"] == "ND"
    assert "tempF" not in msp and "dewpointF" not in msp
    assert next(r["wind"]["speedMph"] for r in result["stations"] if r["station"] == "KMSP") == 11.5
    app._cache.pop("prepared-hrmetar", None)
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=now+timedelta(seconds=1)):
        response = app.app.test_client().get("/api/hrmetar")
    assert response.status_code == 200
    assert {r["station"] for r in response.json["stations"]} == {"KMSP", "KFAR"}
    assert response.headers["Cache-Control"] == "no-store"
