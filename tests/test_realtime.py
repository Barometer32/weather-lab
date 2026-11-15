import json
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

from PIL import Image

import app as weather
import collector
from satellite import BASE

NOW = datetime(2026, 10, 9, 18, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.writes = []

    def read(self, key):
        return self.objects.get(key)

    def write(self, key, data, content_type):
        self.objects[key] = data
        self.writes.append(key)

    def read_json(self, key):
        raw = self.read(key)
        return json.loads(raw) if raw is not None else None

    def write_json(self, key, data):
        self.write(key, json.dumps(data).encode(), "application/json")


def frame(minutes):
    moment = NOW - timedelta(minutes=minutes)
    return {"id": moment.strftime("%Y%m%d%H%M"), "time": weather.iso(moment)}




if __name__ == "__main__": unittest.main()

