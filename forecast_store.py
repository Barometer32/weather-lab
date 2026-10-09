"""A private object bucket in production; atomic local JSON for development."""
import json
import os
from pathlib import Path


def read_forecast():
    bucket = os.environ.get("FORECAST_BUCKET")
    if bucket:
        from google.cloud import storage
        from google.api_core.exceptions import NotFound
        try:
            return json.loads(storage.Client().bucket(bucket).blob("forecast/latest.json").download_as_bytes())
        except NotFound as exc:
            raise FileNotFoundError("No forecast yet") from exc
    return json.loads(Path(os.environ.get("FORECAST_FILE", "data/forecast.json")).read_text())


def write_forecast(data):
    text = json.dumps(data, allow_nan=False, separators=(",", ":"))
    bucket = os.environ.get("FORECAST_BUCKET")
    if bucket:
        from google.cloud import storage
        from google.api_core.exceptions import PreconditionFailed
        blob = storage.Client().bucket(bucket).blob("forecast/latest.json")
        # A retry or overlapping job must never replace a newer forecast.
        for _ in range(3):
            blob.reload() if blob.exists() else None
            generation = blob.generation or 0
            if generation:
                old = json.loads(blob.download_as_bytes(if_generation_match=generation))
                if old["cycle"] >= data["cycle"]:
                    return False
            try:
                blob.upload_from_string(text, content_type="application/json", if_generation_match=generation)
                return True
            except PreconditionFailed:
                continue
        raise RuntimeError("Forecast changed during publication; retry later")
    path = Path(os.environ.get("FORECAST_FILE", "data/forecast.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and json.loads(path.read_text())["cycle"] >= data["cycle"]:
        return False
    temp = path.with_suffix(".tmp")
    temp.write_text(text)
    temp.replace(path)
    return True
