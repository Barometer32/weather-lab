from datetime import datetime,timezone
from unittest.mock import patch
import os
import app
from test_realtime import MemoryStore
from metar_clouds import snapshot

NOW=datetime(2026,10,24,18,5,tzinfo=timezone.utc)


def test_prepared_only_public_pages_never_download_upstream_data_when_empty():
    app._cache.clear()
    with patch.dict(os.environ,{'WEATHER_PREPARED_ONLY':'true'}),patch('app.get_store',return_value=None),patch('app.download') as source:
        client=app.app.test_client()
        assert client.get('/api/forecast').status_code==503
        assert client.get('/api/satellite/truecolor').status_code==503
        assert client.get('/api/station-plots').status_code==503
    source.assert_not_called()


def test_slim_station_payload_retains_four_products_and_actual_routine_report_time():
    from metar_clouds import cloud_summary
    row={'station':'KDEH','lat':43.27,'lon':-91.74,'time':'2026-10-24T17:53:00Z','reportType':'METAR','rawOb':'KDEH 241753Z 27005KT 10SM BKN025 20/10 A3000','temp':20.,'dewp':10.,'wspd':5.,'wdir':270.,'layers':[{'cover':'BKN','baseFtAGL':2500}]}
    saved=snapshot([row],NOW);saved['checkedAt']=NOW.isoformat();store=MemoryStore();store.write_json('live/metar-clouds.json',saved);app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as source:
        response=app.app.test_client().get('/api/station-plots')
    assert response.status_code==200
    value=response.json['history'][-1]['stations'][0]
    assert value['station']=='KDEH' and value['time']==row['time']
    assert value['tempF']==68. and value['dewpointF']==50.
    assert value['wind']['direction']==270 and value['layers'][0]['baseFtAGL']==2500
    assert 'rawOb' not in value and 'cloudLayers' not in value
    assert response.json['sourcePolicy']=='airport-routine-only' and 'metro' not in response.json
    source.assert_not_called()


def test_missing_prepared_asset_does_not_flush_other_warmed_images():
    app.prepared_image.cache_clear();store=MemoryStore()
    existing='satellite/truecolor/20261024175000.jpg';missing='satellite/truecolor/20261024175500.jpg';store.write(existing,b'jpeg','image/jpeg')
    with patch('app.get_store',return_value=store),patch.object(store,'read',wraps=store.read) as reads:
        client=app.app.test_client()
        assert client.get('/api/prepared/'+existing).status_code==200
        assert client.get('/api/prepared/'+missing).status_code==404
        assert client.get('/api/prepared/'+existing).status_code==200
        assert [c.args[0] for c in reads.call_args_list].count(existing)==1
        store.write(missing,b'now ready','image/jpeg')
        assert client.get('/api/prepared/'+missing).status_code==200
