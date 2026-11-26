"""Verify prepared weather products and AVGMETAR default with standard-library tools."""
import argparse
from datetime import datetime
import json
import re
import time
from urllib.request import urlopen
from urllib.error import HTTPError, URLError


def read_bytes(base, path):
    # Domain routing can briefly return 503 after a Cloud Run traffic change.
    # A single transient response must not roll back a healthy replacement.
    for attempt in range(3):
        try:
            with urlopen(base.rstrip("/") + path, timeout=25) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)


def read(base, path):
    return read_bytes(base, path).decode()


def check_layout(base):
    html = read(base, "/")
    assert 'id="tab-metar" aria-selected="true"' in html
    assert 'id="tab-current"' not in html and '<section id="current"' not in html
    assert 'current-hourly.js' not in html
    assert 'id="tab-observations"' not in html and '<section id="observations"' not in html
    assert 'airport-observations.js' not in html
    assert 'rtma-observations.js' not in html
    assert 'id="tab-conditions"' not in html and 'conditions-views.js' not in html
    assert 'current-observations.js' not in html and '/api/observations/' not in html
    assert '<section id="metar" role="tabpanel" aria-labelledby="tab-metar">' in html
    assert '/static/metar-model.js?v=current-home-v35' in html
    assert re.findall(r'<button role="tab" id="tab-([^\"]+)"', html) == ["metar", "radar", "satellite", "forecast", "air-quality"]
    assert re.findall(r'<option value="([^\"]+)"[^>]*>[^<]+</option>', html.split('id="metar-product"', 1)[1].split('</select>', 1)[0]) == ["avgmetar", "plots", "clouds"]
    assert '<option value="avgmetar" selected>AVGMETAR</option>' in html
    assert 'rapmet' not in html.lower()
    assert 'rtmetar' not in html.lower()
    assert 'mesonet-views.js' not in html and 'id="mesonet-map"' not in html
    assert 'id="tab-mesonet"' not in html and '<section id="mesonet"' not in html
    assert '/static/avgmetar.js?v=avgmetar-v52' in html
    assert '/static/metar-views.js?v=avgmetar-v52' in html
    assert '/static/prepared-data.js?v=satellite-truecolor-v51' in html
    assert '/static/sun-angle.js?v=metar-sun-v48' in html
    assert 'id="metar-notice"' not in html
    assert 'id="sun-angle"' in html and 'id="current-sun"' not in html
    options = html.split('id="satellite-product"', 1)[1].split('</select>', 1)[0]
    assert re.findall(r'<option value="([^\"]+)"', options) == ["truecolor", "dcphase", "ntmicro"]
    assert '<option value="truecolor" selected>True Color</option>' in options
    assert '/static/app.js?v=satellite-truecolor-v51' in html
    assert 'id="forecast-periods"' in html
    assert 'lamp-forecast.js' not in html and 'id="forecast-hourly"' not in html and 'forecast-switch' not in html
    assert 'tempest' not in html.lower()
    print("Verified AVGMETAR home with PLOTS, CLOUDS and all other retained tabs.")


def check_hourly(base):
    data = json.loads(read(base, "/api/station-plots?view=loop"))
    assert data.get("loopVersion") == "prepared-hourly-loop-v1"
    assert not data.get("historyPending") and not data.get("stale")
    frames = data["history"]
    assert len(frames) == 4 and all(frame["stations"] for frame in frames)
    hours = [datetime.fromisoformat(frame["hour"].replace("Z", "+00:00")) for frame in frames]
    assert all((b - a).total_seconds() == 3600 for a, b in zip(hours, hours[1:]))
    for frame in frames:
        for station in frame["stations"]:
            assert station["station"] != "METRO" and station["reportType"] == "METAR"
            stamp = datetime.fromisoformat(station["time"].replace("Z", "+00:00"))
            assert 45 <= stamp.minute <= 59
    assert any(s.get("layers") for frame in frames for s in frame["stations"]), "No CLOUDS reports are ready"
    print("Verified prepared CLOUDS/PLOTS: four consecutive hours with independent airport reports.")


def check_removed(base):
    for path in ("/api/tempest", "/static/tempest-views.js", "/api/airport-observations", "/static/airport-observations.js", "/api/rapmet", "/static/rapmet-views.js", "/static/rapmet-stations.json", "/api/satellite/02", "/api/prepared/satellite/02/20261114230000.jpg", "/api/conditions", "/static/conditions-model.js", "/static/conditions-views.js", "/api/rtmetar", "/api/mesonet", "/static/mesonet-views.js", "/api/observations/current", "/api/observations/rtma", "/static/current-observations.js", "/static/rtma-observations.js",
                 "/api/rapmetar", "/static/rapmetar-views.js"):
        try:
            read(base, path)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError(f"Retired endpoint still exists: {path}")
    print("Verified retired observation endpoints and page script are removed.")


def check_products(base):
    """Verify every retained tab reads fresh prepared data and saved imagery."""
    products = [("RADAR", "/api/radar?site=KMPX", "frames"),
                ("SATELLITE True Color", "/api/satellite/truecolor", "frames"),
                ("SATELLITE dcphase", "/api/satellite/dcphase", "frames"),
                ("SATELLITE ntmicro", "/api/satellite/ntmicro", "frames"),
                ("FORECAST", "/api/forecast", "periods"),
                ("AIR Q", "/api/air-quality", "frames")]
    for name, path, items in products:
        data = json.loads(read(base, path))
        assert data.get("checkedAt") and data.get("stale") is False, f"{name}: background data is stale"
        assert data.get(items), f"{name}: no prepared {items}"
        if path == "/api/satellite/truecolor":
            assert data.get("product") == data.get("defaultProduct") == "truecolor" and len(data["frames"]) == 24, "Default True Color loop is still preparing"
        if path == "/api/forecast":
            assert "lamp" not in data and "hourly" not in data, "Expected the text forecast only"
        if items == "frames":
            asset = data[items][-1]["url"]
            assert asset.startswith("/api/prepared/"), f"{name}: asset is not prepared"
            assert read_bytes(base, asset), f"{name}: prepared asset is empty"
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
        if args.all_products:
            check_products(args.url)
