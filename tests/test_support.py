import json

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

