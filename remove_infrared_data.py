"""Remove only cached imagery belonging to the retired Infrared product."""


def purge(bucket):
    removed = []
    for prefix in ('live/satellite-13.json', 'satellite/13/'):
        for blob in bucket.list_blobs(prefix=prefix):
            if blob.name != 'live/satellite-13.json' and not blob.name.startswith('satellite/13/'):
                continue
            blob.delete(if_generation_match=blob.generation, timeout=30)
            removed.append(blob.name)
    return removed


def main():
    from realtime import get_store
    store = get_store()
    if store is None:
        raise ValueError('WEATHER_DATA_BUCKET is required')
    print(f'Removed {len(purge(store.bucket))} retired Infrared objects.', flush=True)


if __name__ == '__main__':
    main()
