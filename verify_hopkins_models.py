"""Verify the fixed 23Z snapshot and its forward precipitation intervals."""
from datetime import datetime, timedelta
import json
import sys


def verify(data):
    cycle = datetime.fromisoformat(data["run"])
    assert cycle == datetime.fromisoformat("2026-11-09T23:00:00Z")
    assert datetime.fromisoformat(data["rrfsCloudRun"]) == cycle - timedelta(hours=5)
    assert (data["latitude"], data["longitude"]) == (44.9244, -93.414)
    assert len(data["rows"]) == 15
    for lead, row in enumerate(data["rows"], start=3):
        valid = datetime.fromisoformat(row["valid"])
        assert valid == cycle + timedelta(hours=lead)
        assert datetime.fromisoformat(row["precipEnds"]) == valid + timedelta(hours=1)
        assert set(row["models"]) == {"RAP", "HRRR", "RRFS"}
        for v in [row["blend"], *row["models"].values()]:
            assert -100 < v["dewF"] <= v["tempF"] + 1 < 150
            assert v["windMph"] >= 0 and v["precipIn"] >= 0
            assert v["windDegrees"] is None or 0 <= v["windDegrees"] < 360
            assert all(0 <= v[k] <= 100 for k in ("low", "mid", "high"))
        for k in ("tempF", "dewF", "precipIn", "low", "mid", "high"):
            assert abs(row["blend"][k] - sum(v[k] for v in row["models"].values()) / 3) < .00011


if __name__ == "__main__":
    verify(json.load(sys.stdin))
    print("Verified 15 Hopkins rows, three model inputs and 15 forward precipitation intervals.")
