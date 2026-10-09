"""Persistent prepared data. Cloud Run instances may safely scale to zero."""
from functools import lru_cache
import json
import os


class BucketStore:
    def __init__(self, name):
        from google.cloud import storage
        self.bucket = storage.Client().bucket(name)

    def read(self, key):
        from google.api_core.exceptions import NotFound
        try:
            return self.bucket.blob(key).download_as_bytes(timeout=30)
        except NotFound:
            return None

    def write(self, key, data, content_type):
        blob = self.bucket.blob(key)
        blob.cache_control = "no-cache" if key.startswith("live/") else "public, max-age=86400, immutable"
        blob.upload_from_string(data, content_type=content_type, timeout=30)

    def read_json(self, key):
        value = self.read(key)
        return json.loads(value) if value is not None else None

    def write_json(self, key, value):
        self.write(key, json.dumps(value).encode(), "application/json")


@lru_cache(maxsize=1)
def get_store():
    name = os.environ.get("WEATHER_DATA_BUCKET")
    return BucketStore(name) if name else None
