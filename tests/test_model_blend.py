from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from unittest.mock import patch

import pytest
import app as weather
import model_blend as models
from test_realtime import MemoryStore

CYCLE = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
NOW = CYCLE + timedelta(hours=2, minutes=35)


def point(**changes):
    return dict(tempK=283.15, dewK=278.15, u=0, v=-5, precipMm=2.54,
                cloudPct=75, ceilingFtAGL=2700, **changes)


def points():
    return {model: {station: point() for station in models.STATIONS} for model in models.ROOTS}


def idx(hour=2, cycle=CYCLE):
    names = [('HGT','surface',f'{hour} hour fcst'),('TMP','2 m above ground',f'{hour} hour fcst'),
             ('DPT','2 m above ground',f'{hour} hour fcst'),('UGRD','10 m above ground',f'{hour} hour fcst'),
             ('VGRD','10 m above ground',f'{hour} hour fcst'),('APCP','surface',f'0-{hour} hour acc fcst'),
             ('APCP','surface',f'{hour-1}-{hour} hour acc fcst'),
             ('TCDC','entire atmosphere (considered as a single layer)',f'{hour} hour fcst'),
             ('HGT','cloud ceiling',f'{hour} hour fcst'),('OTHER','surface',f'{hour} hour fcst')]
    return '\n'.join(f'{i+1}:{100*i}:d={cycle:%Y%m%d%H}:{v}:{lev}:{period}:' for i,(v,lev,period) in enumerate(names))


def test_precip_selects_exact_hour_not_cumulative_or_average_cloud():
    selected=models.inventory(idx(),CYCLE,2)
    assert selected['precipMm']==(600,699)
    assert selected['cloudPct']==(700,799)
    with pytest.raises(ValueError,match='missing'):
        models.inventory(idx().replace('1-2 hour acc fcst','0-2 hour acc fcst'),CYCLE,2)
    with pytest.raises(ValueError):models.inventory(idx(),CYCLE-timedelta(hours=1),2)


def test_equal_model_and_station_weights_and_hour_end_precipitation():
    data=points()
    data['HRRR']['KFCM']['tempK']=289.15
    data['RRFS']['KMIC']['precipMm']=17.78
    row=models.blend_hour(CYCLE,2,data)
    assert row['tempF']==pytest.approx(51.8)
    assert row['precipIn']==pytest.approx(.2)
    assert row['precipStart']=='2026-10-20T13:00:00Z'
    assert row['precipEnd']==row['validTime']=='2026-10-20T14:00:00Z'
    assert row['ceilingFtAGL']==2700
    assert row['cloudCategory']=='BK'
    assert row['wind']['speedKt']==pytest.approx(9.719222462)
    assert row['wind']['direction']==0


def test_wind_wraps_around_north_and_opposing_winds_cancel():
    data=points()
    for model, angle in [('HRRR',350),('RRFS',10)]:
        for p in data[model].values():
            p['u']=-5*math.sin(math.radians(angle));p['v']=-5*math.cos(math.radians(angle))
    assert models.blend_hour(CYCLE,2,data)['wind']['direction']==pytest.approx(0,abs=1e-8)
    for p in data['HRRR'].values():p.update(u=0,v=5)
    for p in data['RRFS'].values():p.update(u=0,v=-5)
    assert models.blend_hour(CYCLE,2,data)['wind']=={'speedKt':0,'direction':None}


def test_lambert_grid_winds_rotated_to_earth():
    u,v=models.earth_wind(0,10,-93,262.5,38.5,38.5)
    assert u>0 and v>9.9
    assert math.hypot(u,v)==pytest.approx(10)
    assert models.earth_wind(2,3,-97.5,262.5,38.5,38.5)==pytest.approx((2,3))


def test_missing_clouds_and_ceiling_are_not_zero_or_cloudy_subset_mean():
    data=points();data['RRFS']['KMIC'].update(cloudPct=None,ceilingFtAGL=None)
    row=models.blend_hour(CYCLE,2,data)
    assert row['cloudPct'] is None and row['cloudCategory'] is None
    assert row['ceilingFtAGL'] is None and row['precipIn']==pytest.approx(.1)
    data['HRRR'].pop('KMSP')
    with pytest.raises(ValueError):models.blend_hour(CYCLE,2,data)


@pytest.mark.parametrize('key,value',[('precipMm',-1),('tempK',None),('dewK',310),('u',float('nan'))])
def test_bad_required_point_rejects_blend(key,value):
    data=points();data['HRRR']['KFCM'][key]=value
    with pytest.raises(ValueError):models.blend_hour(CYCLE,2,data)


def test_atomic_complete_cycle_progress_and_failed_refresh_retains_old():
    store=MemoryStore();probe=lambda url:idx(17).encode()
    with patch('model_blend.read_hour',side_effect=lambda model,*args:points()[model]):
        result=models.collect(store,NOW,downloader=probe)
    data=store.read_json('live/models.json')
    assert result['hours']==16 and data['cycleTime']==models.iso(CYCLE)
    assert [h['forecastHour'] for h in data['hours']]==list(range(2,18))
    assert store.read_json('live/models-status.json')['completed']==32
    assert store.writes.index('live/models.json')>0
    previous=deepcopy(data)
    with patch('model_blend.read_hour',side_effect=ValueError('missing point')):
        with pytest.raises(ValueError):models.collect(store,NOW+timedelta(hours=1),downloader=lambda u:idx(17,CYCLE+timedelta(hours=1)).encode())
    assert store.read_json('live/models.json')==previous
    assert store.read_json('live/models-status.json')['state']=='error'


def test_saved_same_cycle_skips_all_grib_downloads():
    store=MemoryStore();store.write_json('live/models.json',{'modelVersion':models.VERSION,'cycleTime':models.iso(CYCLE)})
    def source(url):
        raise FileNotFoundError('new cycle not yet available')
    with patch('model_blend.read_hour') as download:
        result=models.collect(store,NOW,downloader=source)
    assert result['status']=='unchanged';download.assert_not_called()


def test_saved_api_never_starts_collection_and_keeps_prior_table_with_warning():
    store=MemoryStore();client=weather.app.test_client()
    with patch('app.get_store',return_value=store),patch('app.download') as download,patch('app.utcnow',return_value=NOW):
        assert client.get('/api/models').json['available'] is False
        store.write_json('live/models.json',{'modelVersion':models.VERSION,'cycleTime':models.iso(CYCLE),'hours':[]})
        store.write_json('live/models-status.json',{'state':'error'})
        response=client.get('/api/models')
        assert response.json['stale'] and response.json['available']
        assert response.headers['Cache-Control']=='no-store'
        download.assert_not_called()


def test_range_response_must_be_206_and_exact_length():
    from io import BytesIO
    class Response(BytesIO):
        status=200
        headers={}
    with patch('model_blend.urlopen',side_effect=lambda *a,**k:Response(b'GRIB')),patch('model_blend.time.sleep'):
        with pytest.raises(ValueError,match='range'):models.fetch('https://example.org/file',(1,4))


def test_live_grib_decode_metadata_and_nearest_cells():
    # Tiny real GRIB generated by ecCodes, not a mock of the extraction code.
    import eccodes as ec
    handle=ec.codes_grib_new_from_samples('regular_ll_sfc_grib2')
    try:
        for key,value in {'Ni':9,'Nj':7,'latitudeOfFirstGridPointInDegrees':45.1,
                          'longitudeOfFirstGridPointInDegrees':266.5,'latitudeOfLastGridPointInDegrees':44.8,
                          'longitudeOfLastGridPointInDegrees':266.9,'iDirectionIncrementInDegrees':.05,
                          'jDirectionIncrementInDegrees':.05,'dataDate':20261020,'dataTime':1200,
                          'step':2,'typeOfLevel':'heightAboveGround','level':2,'shortName':'2t'}.items():
            ec.codes_set(handle,key,value)
        ec.codes_set_values(handle,[280+i*.05 for i in range(63)])
        payload=ec.codes_get_message(handle)
    finally:ec.codes_release(handle)
    data,rotation=models.PointDecoder().decode(payload,CYCLE,2,'tempK')
    assert set(data)==set(models.STATIONS) and all(280<=v<=285 for v in data.values())
    assert rotation is None
    with pytest.raises(ValueError,match='cycle or valid time'):
        models.PointDecoder().decode(payload,CYCLE,3,'tempK')
