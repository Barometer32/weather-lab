"""Verify staged/live RTMETAR using only Python's standard library."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import re
from urllib.request import urlopen


def read(base, path):
    with urlopen(base.rstrip("/") + path, timeout=25) as response:
        return response.read().decode()


def check_layout(base):
    html = read(base, "/")
    assert 'id="tab-observations"' not in html and 'id="observations"' not in html
    assert 'hourly-observation-views.js' not in html
    assert re.findall(r'<button role="tab" id="tab-([^\"]+)"', html) == ["metar", "radar", "satellite", "forecast", "air-quality"]
    assert 'id="tab-metar" aria-selected="true"' in html
    assert '<option value="rtmetar" selected>RTMETAR</option>' in html
    for product in ["plots", "clouds"]:
        assert f'<option value="{product}">' in html
    assert '/static/metar-views.js?v=rtmetar-ready-v2' in html
    print("Verified METAR home, RTMETAR default, retained PLOTS/CLOUDS, and removed Observations.")


def check_data(base):
    from rtmetar import VERSION, STATES
    data = json.loads(read(base, "/api/rtmetar"))
    assert data["version"] == VERSION and data["temperatureUnit"] == "C" and data["windUnit"] == "mph"
    assert data["temperatureBasis"] == "main-XX/XX" and not data["stale"]
    assert data["stations"], "No five-minute reports have arrived yet"
    for station in data["stations"]:
        assert station["state"] in STATES and station["reportType"] == "HFMETAR"
        observed = datetime.fromisoformat(station["time"].replace("Z", "+00:00"))
        assert observed.minute % 5 == 0 and observed.second == 0
        assert 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 3600
        body, _, remarks = station["rawOb"].partition(" RMK")
        assert re.search(r"\bMADISHF\b", remarks)
        group = re.search(r"(?:^|\s)(M?\d{2}|//)/(M?\d{2}|//)(?=\s|$)", body)
        if group:
            for key, text in [("tempC", group[1]), ("dewpointC", group[2])]:
                expected = None if text == "//" else int(text.replace("M", "-"))
                assert station[key] is None or station[key] == expected
        else:
            assert station["tempC"] is None and station["dewpointC"] is None
        assert "tempF" not in station and "speedKnots" not in station["wind"]
    print("Verified five-minute-only Celsius/mph reports:", dict(Counter(s["state"] for s in data["stations"])))
    if data["sourceDelayed"]:
        print("Some upstream reports are delayed; their real timestamps are preserved and labeled.")


def check_hourly(base):
    data = json.loads(read(base, "/api/station-plots?view=loop"))
    assert data.get("loopVersion") == "prepared-hourly-loop-v1"
    assert not data.get("historyPending") and not data.get("stale")
    frames = data["history"]
    assert len(frames) == 4 and all(frame["stations"] for frame in frames)
    hours = [datetime.fromisoformat(frame["hour"].replace("Z", "+00:00")) for frame in frames]
    assert all((b - a).total_seconds() == 3600 for a, b in zip(hours, hours[1:]))
    sites = set.intersection(*({s["station"] for s in frame["stations"]} for frame in frames))
    assert sites, "No stations have a complete four-hour plotting window"
    for frame in frames:
        for station in frame["stations"]:
            assert station["reportType"] == "METAR"
            stamp = datetime.fromisoformat(station["time"].replace("Z", "+00:00"))
            assert 45 <= stamp.minute <= 59
    clouds = [{s["station"] for s in frame["stations"] if s.get("layers")} for frame in frames]
    assert set.intersection(*clouds), "No complete CLOUDS history is ready"
    print(f"Verified prepared CLOUDS/PLOTS loop: four consecutive hours, {len(sites)} common stations.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--all-products", action="store_true")
    args = parser.parse_args()
    check_layout(args.url)
    if not args.layout_only:
        check_data(args.url)
        if args.all_products:
            check_hourly(args.url)
