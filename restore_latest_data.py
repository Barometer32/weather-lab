"""Repopulate the latest saved site's products using its collector identity."""
from datetime import datetime, timezone
import json


def main():
    from realtime import get_store
    import metar_history
    import refresh_media
    import air_quality
    import madis_map
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET is required")
    print("Data 1/3: twelve hourly airport frames for all four METAR products",flush=True)
    metar_history.main()
    print("Data 2/3: two-hour radar, latest satellite images and NWS forecast",flush=True)
    refresh_media.main()
    print("Data 3/3: latest Minnesota Air Q map",flush=True)
    air_quality.main()
    print("Preparing twelve separate public mesonet hours",flush=True)
    madis_map.collect(store, datetime.now(timezone.utc), hours=12)
    print("Latest Weather Lab data prepared. Existing Air Q history is retained when available; lost source-hour snapshots rebuild over time.",flush=True)


if __name__ == "__main__":
    main()
