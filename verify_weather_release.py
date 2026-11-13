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
    assert 'id="tab-observations"' not in html and '<section id="observations"' not in html
    assert 'current-observations.js' not in html and '/api/observations/' not in html
    assert '<section id="metar" role="tabpanel" aria-labelledby="tab-metar">' in html
    assert '/static/metar-model.js?v=slightly-denser-v19' in html
    assert re.findall(r'<button role="tab" id="tab-([^\"]+)"', html) == ["metar", "radar", "satellite", "forecast", "air-quality"]
    assert 'id="tab-metar" aria-selected="true"' in html
    assert re.findall(r'<option value="([^\"]+)"[^>]*>[^<]+</option>', html.split('id="metar-product"', 1)[1].split('</select>', 1)[0]) == ["plots", "clouds"]
    assert '<option value="plots" selected>PLOTS</option>' in html
    assert 'rtmetar' not in html.lower()
    assert 'mesonet-views.js' not in html and 'id="mesonet-map"' not in html
    assert 'id="tab-mesonet"' not in html and '<section id="mesonet"' not in html
    assert '<option value="clouds">CLOUDS</option>' in html
    assert '/static/metar-views.js?v=slightly-denser-v19' in html
    assert 'id="metar-notice"' not in html
    options = html.split('id="satellite-product"', 1)[1].split('</select>', 1)[0]
    assert re.findall(r'<option value="([^\"]+)"', options) == ["02", "truecolor", "dcphase", "ntmicro"]
    assert '<option value="02" selected>Visible (red)</option>' in options
    assert '/static/app.js?v=slightly-denser-v19' in html
    print("Verified METAR PLOTS home, CLOUDS retained, and OBSERVATIONS removed.")


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
            assert station["reportType"] == "METAR"
            stamp = datetime.fromisoformat(station["time"].replace("Z", "+00:00"))
            assert 45 <= stamp.minute <= 59
    assert any(s.get("layers") for frame in frames for s in frame["stations"]), "No CLOUDS reports are ready"
    print("Verified prepared CLOUDS/PLOTS: four consecutive hours with independent airport reports.")


def check_removed(base):
    for path in ("/api/rtmetar", "/api/mesonet", "/api/observations/current", "/static/current-observations.js"):
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
        if args.all_products:
            check_products(args.url)
