"""Backfill radar products before publishing the updated viewer."""
from datetime import datetime, timezone
import json
from app import PALETTE
from native_radar import collect_site
from radar_precipitation import collect
from realtime import get_store


def main():
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET is required")
    palette = [{"dbz": value, "color": color} for value, color in PALETTE]
    for attempt in range(6):
        now = datetime.now(timezone.utc)
        radar = collect_site(store, now, "KMPX", palette, budget=180)
        precip = collect(store, datetime.now(timezone.utc), budget=90)
        print(json.dumps({"pass": attempt+1, "reflectivity": radar, "precipitation": precip}), flush=True)
        data = store.read_json("live/radar-all-KMPX.json")
        if not radar["historyPending"] and len(data.get("products", {})) > 1 and precip["frames"]:
            print("All available elevation loops and storm totals are prepared.", flush=True)
            return
    raise ValueError("Radar backfill remains incomplete; leave the website image unchanged and retry the seed job")


if __name__ == "__main__":
    main()
