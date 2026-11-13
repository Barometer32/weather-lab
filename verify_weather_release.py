"""Verify prepared weather products and PLOTS default with standard-library tools."""
import argparse
from datetime import datetime, timezone
import json
import re
from urllib.request import urlopen
from urllib.error import HTTPError


def read(base, path):
    with urlopen(base.rstrip("/") + path, timeout=25) as response:
        return response.read().decode()


def check_layout(base):
    html = read(base, "/")
    assert 'id="tab-observations"' in html and 'id="observations"' in html
    assert all('id="'+name+'"' in html for name in ("observations-temperature","observations-dewpoint","observations-wind","observations-sun"))
    assert 'hourly-observation-views.js' not in html
    assert re.findall(r'<button role="tab" id="tab-([^\"]+)"', html) == ["metar", "observations", "radar", "satellite", "forecast", "air-quality"]
    assert 'id="tab-metar" aria-selected="true"' in html
    assert re.findall(r'<option value="([^\"]+)"[^>]*>[^<]+</option>', html.split('id="metar-product"', 1)[1].split('</select>', 1)[0]) == ["plots", "clouds"]
    assert '<option value="plots" selected>PLOTS</option>' in html
    assert 'rtmetar' not in html.lower()
    assert 'mesonet-views.js' not in html and 'id="mesonet-map"' not in html
    assert 'id="tab-mesonet"' not in html and '<section id="mesonet"' not in html
    assert '<option value="clouds">CLOUDS</option>' in html
    assert '/static/metar-views.js?v=rapid-observations-v11' in html
    assert 'id="metar-notice"' not in html
    options = html.split('id="satellite-product"', 1)[1].split('</select>', 1)[0]
    assert re.findall(r'<option value="([^\"]+)"', options) == ["02", "truecolor", "dcphase", "ntmicro"]
    assert '<option value="02" selected>Visible (red)</option>' in options
    assert '/static/app.js?v=rapid-observations-v11' in html
    print("Verified METAR home with PLOTS default, PLOTS/CLOUDS retained, OBSERVATIONS added, and RTMETAR/MESONET removed.")


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


def check_removed(base):
    for path in ("/api/rtmetar", "/api/mesonet"):
        try:
            read(base, path)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError(f"Retired endpoint still exists: {path}")
    print("Verified RTMETAR and MESONET endpoints are removed.")


def check_observations(base):
    from five_minute_observations import VERSION, STATIONS, average
    now = datetime.now(timezone.utc)
    data = json.loads(read(base, "/api/observations/current"))
    assert data["version"]==VERSION and data["available"] and not data["stale"]
    assert data["updateIntervalSeconds"]==300 and data["stationIds"]==list(STATIONS)
    value = data["current"]
    assert {r["station"] for r in value["stations"]}==set(STATIONS)
    assert all(r["time"]==value["observedAt"] and "MADISHF" in r["rawOb"].partition(" RMK")[2] for r in value["stations"])
    assert average(value["stations"],now)==value, "Three-airport raw-Celsius mean is inconsistent"
    print(f"Verified OBSERVATIONS: three matching five-minute reports at {value['observedAt']}, checked {data['checkedAt']}.")
    if data["sourceDelayed"]:
        print("OBSERVATIONS: upstream delivery is delayed; original report timestamps are preserved.")


def check_products(base):
    """Verify every retained tab reads fresh prepared data and saved imagery."""
    products = [("RADAR", "/api/radar?site=KMPX", "frames"),
                ("SATELLITE Visible (red)", "/api/satellite/02", "frames"),
                ("SATELLITE truecolor", "/api/satellite/truecolor", "frames"),
                ("SATELLITE dcphase", "/api/satellite/dcphase", "frames"),
                ("SATELLITE ntmicro", "/api/satellite/ntmicro", "frames"),
                ("FORECAST", "/api/forecast", "periods"),
                ("AIR Q", "/api/air-quality", "frames")]
    for name, path, items in products:
        data = json.loads(read(base, path))
        assert data.get("checkedAt") and data.get("stale") is False, f"{name}: background data is stale"
        assert data.get(items), f"{name}: no prepared {items}"
        if path == "/api/satellite/02":
            assert data.get("product") == "02" and len(data["frames"]) == 24, "Default visible band loop is still preparing"
        if items == "frames":
            asset = data[items][-1]["url"]
            assert asset.startswith("/api/prepared/"), f"{name}: asset is not prepared"
            with urlopen(base.rstrip("/") + asset, timeout=30) as response:
                assert response.read(), f"{name}: prepared asset is empty"
        print(f"Verified {name}: {len(data[items])} prepared {items}, checked {data['checkedAt']}.")
        if data.get("sourceDelayed"):
            print(f"{name}: upstream source is delayed; the original observation time is preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--all-products", action="store_true")
    args = parser.parse_args()
    check_layout(args.url)
    if not args.layout_only:
        check_hourly(args.url)
        check_removed(args.url)
        check_observations(args.url)
        if args.all_products:
            check_products(args.url)
