"""Delete only the retired TEST feature's shared caches and observation archives."""
import re

LIVE_KEYS = {'live/test-weather.json','live/test-input-airports.json','live/test-history-cleanup.json'}
INPUT = re.compile(r'live/test-input-(mesonet|rwis|hfmetar)-[01]\.json\Z')
HISTORY_PREFIX = 'test-history/v1/'


def owned(key):
    return key in LIVE_KEYS or bool(INPUT.fullmatch(key)) or key.startswith(HISTORY_PREFIX)


def purge(bucket):
    removed=[]
    for prefix in ('live/test-',HISTORY_PREFIX):
        for blob in bucket.list_blobs(prefix=prefix):
            if not owned(blob.name):continue
            # A concurrently revised object is not silently deleted under an
            # old generation. A failed cleanup can be safely rerun.
            blob.delete(if_generation_match=blob.generation,timeout=30)
            removed.append(blob.name)
    return removed


def main():
    from realtime import get_store
    store=get_store()
    if store is None:raise ValueError('WEATHER_DATA_BUCKET is required')
    removed=purge(store.bucket)
    print('Removed '+str(len(removed))+' TEST cache/archive objects. Other weather data was preserved.',flush=True)


if __name__=='__main__':main()
