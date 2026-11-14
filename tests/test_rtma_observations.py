from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

import app
import collector
import rtma_observations as rtma
import verify_weather_release as verify

NOW = datetime(2026, 11, 14, 15, 3, tzinfo=timezone.utc)
CYCLE = NOW.replace(hour=14, minute=45)


class Store:
    def __init__(self, data=None): self.data = data; self.writes = []
    def read_json(self, key): assert key == rtma.KEY; return deepcopy(self.data)
    def write_json(self, key, data): assert key == rtma.KEY; self.data = deepcopy(data); self.writes.append(data)


def stations(cycle=CYCLE):
    return [{**station, 'analysisTime': rtma.iso(cycle), 'tempC': t, 'dewpointC': d,
             'tempF': t * 1.8 + 32, 'dewpointF': d * 1.8 + 32,
             'wind': {'speedMph': speed, 'direction': direction},
             'gridLat': station['lat'], 'gridLon': station['lon'], 'gridDistanceKm': .5}
            for station, t, d, speed, direction in zip(rtma.STATIONS, [1, 2, 2], [-6, -5, -5], [5, 7, 6], [350, 0, 10])]


def prepared(cycle=CYCLE):
    rows = stations(cycle)
    return dict(version=rtma.VERSION, source='NOAA RTMA-RU', sourceType='gridded-analysis',
                analysisTime=rtma.iso(cycle), checkedAt=rtma.iso(NOW), stations=rows,
                mean=rtma.average(rows))


def inventory(cycle=CYCLE):
    prefix = f'rtma2p5_ru.{cycle:%Y%m%d}/rtma2p5_ru.t{cycle:%H%M}z'
    return (f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f'<IsTruncated>false</IsTruncated><Contents><Key>{prefix}.2dvaranl_ndfd.grb2.idx</Key>'
            f'<LastModified>{rtma.iso(NOW-timedelta(minutes=1))}</LastModified></Contents>'
            f'<Contents><Key>{prefix}.2dvarges_ndfd.grb2.idx</Key></Contents></ListBucketResult>').encode()


INDEX = b'1:0:d=2026111414:TMP:2 m above ground:anl:\n2:100:d=2026111414:DPT:2 m above ground:anl:\n3:200:d=2026111414:WIND:10 m above ground:anl:\n4:300:d=2026111414:WDIR:10 m above ground:anl:\n5:400:d=2026111414:GUST:10 m above ground:anl:\n'


def test_average_rounds_only_at_display_and_wraps_north():
    result = rtma.average(stations())
    assert result['tempF'] == pytest.approx(35)
    assert result['dewpointF'] == pytest.approx(22.4)
    assert result['wind']['speedMph'] == 6
    assert result['wind']['direction'] < 2
    rows = stations(); rows[1]['analysisTime'] = rtma.iso(CYCLE-timedelta(minutes=15))
    with pytest.raises(ValueError): rtma.average(rows)
    with pytest.raises(ValueError): rtma.average(stations()[:2])


def test_discovery_handles_utc_midnight_and_excludes_forecast_and_old_cycles():
    now = datetime(2026, 11, 15, 0, 5, tzinfo=timezone.utc)
    cycle = now.replace(day=14, hour=23, minute=45)
    calls = []
    def download(url):
        calls.append(url)
        return b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated></ListBucketResult>' if '20261115' in url else inventory(cycle)
    found = rtma.available_cycles(now, download=download)
    assert len(found) == 1 and found[0][0] == cycle
    assert len(calls) == 2
    assert rtma.available_cycles(now, previous=cycle, download=download) == []


def test_collection_downloads_only_four_fields_then_reuses_cycle_without_grib_reads():
    calls = []
    def download(url, start=None, end=None):
        calls.append((url, start, end))
        return inventory() if '?' in url else INDEX if url.endswith('.idx') else b'grib'
    store = Store()
    result = rtma.collect(store, NOW, download, lambda messages, cycle: stations(cycle))
    assert result['newCycle'] is True and len(store.data['stations']) == 3
    assert store.data['analysisTime'] == rtma.iso(CYCLE)
    assert len([call for call in calls if call[1] is not None]) == 4
    calls.clear()
    assert rtma.collect(store, NOW+timedelta(minutes=1), download)['newCycle'] is False
    assert len(calls) == 1 and '?' in calls[0][0]
    assert store.data['analysisTime'] == rtma.iso(CYCLE)


def test_corrupt_new_cycle_keeps_previous_snapshot_and_time():
    old = prepared(CYCLE-timedelta(minutes=15)); store = Store(old)
    def download(url, start=None, end=None): return inventory() if '?' in url else INDEX if url.endswith('.idx') else b'broken'
    with pytest.raises(ValueError): rtma.collect(store, NOW, download)
    assert store.writes == [] and store.data == old
    with pytest.raises(ValueError): rtma.message_ranges(INDEX.replace(b'DPT', b'GUST'))


def test_public_route_only_reads_prepared_data_and_marks_old_data_honestly():
    store = Store(prepared()); client = app.app.test_client()
    app._cache.clear()
    with patch('app.get_store', return_value=store), patch('app.utcnow', return_value=NOW), patch('rtma_observations.fetch') as download, patch('rtma_observations.decode') as decoder:
        response = client.get('/api/observations/rtma')
        assert response.status_code == 200 and response.json['analysisTime'] == rtma.iso(CYCLE)
        assert response.json['stale'] is False
        download.assert_not_called(); decoder.assert_not_called()
    delayed = rtma.public_snapshot(prepared(), NOW+timedelta(hours=1))
    assert delayed['sourceDelayed'] and delayed['collectionDelayed'] and delayed['stale']
    assert delayed['analysisTime'] == rtma.iso(CYCLE)
    app._cache.clear()
    with patch('app.get_store', return_value=Store()): assert client.get('/api/observations/rtma').status_code == 503


def test_collector_private_route_publishes_and_old_metar_observations_stay_removed():
    with patch('collector.get_store', return_value=Store()), patch('rtma_observations.collect', return_value={'newCycle': True}) as collect:
        assert collector.app.test_client().post('/collect/rtma-observations').status_code == 200
        collect.assert_called_once()
    assert collector.app.test_client().post('/collect/rtmetar').status_code == 404


def test_release_retries_transient_503_but_not_expected_404():
    response = BytesIO(b'healthy')
    unavailable = HTTPError('https://example.test/', 503, 'Unavailable', {}, None)
    with patch.object(verify, 'urlopen', side_effect=[unavailable, response]) as request, patch.object(verify.time, 'sleep'):
        assert verify.read('https://example.test', '/') == 'healthy'
        assert request.call_count == 2
    missing = HTTPError('https://example.test/', 404, 'Missing', {}, None)
    with patch.object(verify, 'urlopen', side_effect=missing) as request:
        with pytest.raises(HTTPError): verify.read('https://example.test', '/')
        assert request.call_count == 1


def test_actual_grib_decoder_units_cycle_and_missing_values():
    ec = pytest.importorskip('eccodes')
    import numpy as np
    messages = {}
    for field, short, level, value in [('TMP','2t',2,275.15), ('DPT','2d',2,270.15), ('WIND','10si',10,4), ('WDIR','10wdir',10,350)]:
        handle = ec.codes_grib_new_from_samples('GRIB2')
        try:
            for key, entry in [('gridType','lambert'),('Nx',32),('Ny',32),('latitudeOfFirstGridPointInDegrees',44.6),('longitudeOfFirstGridPointInDegrees',266.2),('LoVInDegrees',265),('LaDInDegrees',25),('Latin1InDegrees',25),('Latin2InDegrees',25),('DxInMetres',2500),('DyInMetres',2500),('jScansPositively',1),('typeOfLevel','heightAboveGround'),('level',level),('shortName',short),('dataDate',20261114),('dataTime',1445),('step',0)]:
                ec.codes_set(handle,key,entry)
            ec.codes_set_values(handle,np.full(32*32,value))
            messages[field] = ec.codes_get_message(handle)
        finally: ec.codes_release(handle)
    rows = rtma.decode(messages,CYCLE)
    assert len(rows) == 3
    assert all(row['tempC'] == pytest.approx(2,abs=.001) and row['wind']['direction'] == 350 for row in rows)
    assert all(row['wind']['speedMph'] == pytest.approx(4*rtma.MPS_TO_MPH) for row in rows)
    with pytest.raises(ValueError,match='Mixed RTMA cycles'): rtma.decode(messages,CYCLE+timedelta(minutes=15))
    with pytest.raises(ValueError,match='Corrupt GRIB'): rtma.decode({**messages,'DPT':b'broken'},CYCLE)
