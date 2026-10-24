"""Prepare the latest satellite images using the private collector identity."""
from datetime import datetime, timezone
import json
from collector import collect_satellite
from realtime import get_store


def main():
    store=get_store()
    if store is None:raise ValueError('WEATHER_DATA_BUCKET is required')
    result=collect_satellite(store,datetime.now(timezone.utc))
    print(json.dumps(result),flush=True)
    if any('error' in product for product in result.values()):
        raise RuntimeError('A satellite product failed; existing images were retained')


if __name__=='__main__':main()
