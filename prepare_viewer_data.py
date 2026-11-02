"""Prepare new viewer data before the updated website is published."""
from datetime import datetime, timezone
import json
from realtime import get_store
from collector import collect_satellite
from air_quality import collect


def main():
    store=get_store()
    if store is None:raise ValueError('WEATHER_DATA_BUCKET is required')
    print('Preparing the latest 24 images for each satellite product',flush=True)
    print(json.dumps({'satellite':collect_satellite(store,datetime.now(timezone.utc))}),flush=True)
    print('Recovering real hourly Air Q contours from the EPA 24-hour archive',flush=True)
    print(json.dumps({'airQuality':collect(store,datetime.now(timezone.utc))}),flush=True)


if __name__=='__main__':main()
