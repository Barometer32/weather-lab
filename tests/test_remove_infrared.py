from types import SimpleNamespace
from remove_infrared_data import purge


def test_cleanup_preserves_other_satellite_products_and_shared_boundaries():
    names = ['live/satellite-13.json', 'live/satellite-13.json.backup',
             'satellite/13/20261102120000.jpg', 'live/satellite-truecolor.json',
             'satellite/truecolor/20261102120000.jpg', 'satellite/maps/abc.png',
             'live/air-quality.json']
    removed = []
    class Blob:
        generation = 7
        def __init__(self, name): self.name = name
        def delete(self, *, if_generation_match, timeout):
            assert if_generation_match == 7 and timeout == 30
            removed.append(self.name)
    bucket = SimpleNamespace(list_blobs=lambda prefix: [Blob(n) for n in names if n.startswith(prefix)])
    assert purge(bucket) == ['live/satellite-13.json', 'satellite/13/20261102120000.jpg']
    assert removed == ['live/satellite-13.json', 'satellite/13/20261102120000.jpg']
