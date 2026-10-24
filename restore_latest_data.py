"""Repopulate the latest saved site's products using its collector identity."""
from datetime import datetime, timezone
import json


def main():
    from realtime import get_store
    import observation_stations
    import metar_history
    import refresh_media
    import air_quality
    store = get_store()
    if store is None:
        raise ValueError("WEATHER_DATA_BUCKET is required")
    print("Data 1/4: latest public Hennepin West observations", flush=True)
    result=observation_stations.collect(store,datetime.now(timezone.utc))
    print(json.dumps({"hennepinWestStations":len(result['stations']),"sourceFailures":result['sourceFailures']}),flush=True)
    print("Data 2/4: twelve hourly airport frames for CLOUDS",flush=True)
    metar_history.main()
    print("Data 3/4: two-hour radar, latest satellite images and NWS forecast",flush=True)
    refresh_media.main()
    print("Data 4/4: latest Minnesota Air Q map",flush=True)
    air_quality.main()
    print("Latest Weather Lab data prepared. Existing Air Q history is retained when available; lost source-hour snapshots rebuild over time.",flush=True)


if __name__ == "__main__":
    main()
