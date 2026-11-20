from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import app
import collector
from lamp_forecast import STATIONS, bulletin_url, parse_bulletin, refresh_lamp
from test_forecast import document
from test_realtime import MemoryStore
from nws_forecast import normalize_forecast

CYCLE = datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc)


def bulletin(cycle=CYCLE):
    blocks = []
    for i, station in enumerate(STATIONS):
        rows = {
            "UTC": [f"{(cycle + timedelta(hours=j)):%H}" for j in range(1, 26)],
            "TMP": [50+i]*25, "DPT": [32+i]*25,
            "WSP": [10]*25, "WDR": [[35, 36, 1][i]]*25,
            "P01": [0, 100, 100, 100, 40+i*10] + [0]*20,
            "CLD": [["SC", "BK", "OV"][i]]*25,
            "CIG": [[3, 5, 8][i]]*25,
        }
        header = f" {station}   GFS LAMP GUIDANCE  {cycle:%m/%d/%Y}  {cycle:%H%M} UTC"
        blocks.append(header + "\n" + "\n".join(
            f" {key} " + "".join(f"{value:>3}" for value in values) for key, values in rows.items()))
    return ("\n\n".join(blocks)+"\n").encode("ascii")


def test_bulletin_averages_wrap_north_and_align_p01_to_the_forward_hour():
    result = parse_bulletin(bulletin(), CYCLE)
    assert len(result["hours"]) == 24
    first = result["hours"][0]
    assert first["startTime"] == "2026-10-10T00:00:00+00:00"
    assert first["precipChancePct"] == 100  # Column 01, not column 00.
    assert (first["temperatureF"], first["dewpointF"]) == (51, 33)
    assert first["windDirection"] in (0, 360) and first["windMph"] == 11.5
    assert first["skyCover"] == "Broken" and first["ceiling"] == "2,000–3,000 ft AGL"
    assert result["hours"][2]["startTime"] == "2026-10-10T02:00:00+00:00"
    assert result["hours"][2]["endTime"] == "2026-10-10T03:00:00+00:00"
    assert result["hours"][2]["precipChancePct"] == 100
    assert result["hours"][3]["precipChancePct"] == 50


def test_collection_checks_new_cycle_and_keeps_previous_until_it_is_ready():
    prior_cycle = CYCLE-timedelta(hours=1)
    prior = parse_bulletin(bulletin(prior_cycle), prior_cycle)
    download = Mock(side_effect=[OSError("not posted"), bulletin()])
    assert refresh_lamp(prior, download, CYCLE-timedelta(minutes=5)) is prior
    download.assert_not_called()
    assert refresh_lamp(prior, download, CYCLE) is prior
    result = refresh_lamp(prior, download, CYCLE+timedelta(minutes=5))
    assert result["cycleTime"] == CYCLE.isoformat()
    assert refresh_lamp(result, download, CYCLE+timedelta(minutes=10)) is result
    assert [c.args[0] for c in download.call_args_list] == [bulletin_url(CYCLE)]*2


def test_missing_station_does_not_publish_and_cold_start_uses_previous_run():
    prior = CYCLE-timedelta(hours=1)
    partial = bulletin().split(b" KMIC   GFS LAMP")[0]
    download = Mock(side_effect=[partial, bulletin(prior)])
    saved = refresh_lamp(None, download, CYCLE)
    assert saved["cycleTime"] == prior.isoformat()
    assert saved["stations"] == list(STATIONS)


def test_collector_prepares_lamp_and_forecast_api_reads_only_saved_data():
    store = MemoryStore()
    forecast = normalize_forecast(document(), CYCLE)
    with patch("app.get_forecast", return_value=forecast), patch("app.download", return_value=bulletin()) as upstream:
        collector.collect_forecast(store, CYCLE)
    upstream.assert_called_once_with(bulletin_url(CYCLE))
    app._cache.clear()
    with patch("app.get_store", return_value=store), patch("app.utcnow", return_value=CYCLE), patch("app.download") as upstream:
        response = app.app.test_client().get("/api/forecast")
    assert response.status_code == 200
    assert len(response.json["lamp"]["hours"]) == 24
    assert response.json["periods"][0]["detailedForecast"] == forecast["periods"][0]["detailedForecast"]
    upstream.assert_not_called()
