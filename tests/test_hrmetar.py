"""Test complete, time-aligned blends using a compressed MADIS-shaped fixture."""
from datetime import datetime, timedelta, timezone
import gzip

from scipy.io import netcdf_file

from hrmetar import latest_average, station_rows


def test_only_complete_five_minute_groups_use_whole_celsius(tmp_path):
    now = datetime(2026, 11, 28, 15, 15, tzinfo=timezone.utc)
    stamp = int((now - timedelta(minutes=10)).timestamp())
    reports = [
        (b"KMSP", stamp, -1, -5, 4, 350),
        (b"KFCM", stamp, -2, -6, 4, 10),
        (b"MIC ", stamp, -2, -7, 4, 999),
        (b"KMSP", stamp + 300, 3, -1, 4, 20),
        (b"KFCM", stamp + 300, 3.5, -1, 4, 20),
        (b"KMIC", stamp + 300, 2, -1, 4, 20),
        (b"KMSP", stamp + 480, 4, 0, 4, 40),
        (b"KFCM", stamp + 480, 4, 0, 4, 40),
        (b"KMIC", stamp + 480, 4, 0, 4, 40),
    ]
    path = tmp_path / "asos.nc"
    with netcdf_file(path, "w") as data:
        data.createDimension("recNum", None)
        data.createDimension("idLen", 4)
        ids = data.createVariable("stationId", "c", ("recNum", "idLen"))
        ids[:] = [list(bytes([character]) for character in row[0]) for row in reports]
        for index, (name, kind, offset) in enumerate([
            ("observationTime", "d", 0), ("temperature", "f", 273.15),
            ("dewpoint", "f", 273.15), ("windSpeed", "f", 0), ("windDir", "f", 0),
        ], start=1):
            data.createVariable(name, kind, ("recNum",))[:] = [row[index] + offset for row in reports]

    result = latest_average(station_rows(gzip.compress(path.read_bytes()), now))
    assert result == {
        "observedAt": "2026-11-28T15:05:00Z", "tempC": -5 / 3, "dewpointC": -6,
        "windMph": 9, "windDirection": 0,
    }
