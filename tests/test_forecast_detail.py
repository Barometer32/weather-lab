from datetime import datetime, timedelta, timezone
import copy
import json
from unittest.mock import patch

import app
import collector
import nws_forecast as nws
from test_forecast import document
from test_realtime import MemoryStore

NOW = datetime(2026, 10, 9, 17, tzinfo=timezone.utc)


def hourly():
    return {"properties": {"updateTime": "2026-10-09T16:00:00Z", "periods": [
        {"startTime": (NOW+timedelta(hours=i)).isoformat(),
         "endTime": (NOW+timedelta(hours=i+1)).isoformat(),
         "shortForecast": "Rain" if i == 3 else "Partly Cloudy",
         "probabilityOfPrecipitation": {"value": [None, 0, 10, 60, 60, 80][i]}}
        for i in range(6)]}}


def layer(values, unit="wmoUnit:percent"):
    return {"uom": unit, "values": [
        {"validTime": (NOW+timedelta(hours=i)).isoformat()+"/PT1H", "value": value}
        for i, value in enumerate(values)]}


def test_custom_cloud_thresholds_and_missing_values():
    assert [nws.cloud_label(v) for v in [None, 0, 20, 20.1, 39.9, 40, 59.9, 60, 79.9, 80, 100]] == [
        None, "Clear", "Clear", "Mostly clear", "Mostly clear", "Partly cloudy", "Partly cloudy",
        "Mostly cloudy", "Mostly cloudy", "Cloudy", "Cloudy"]


def test_timed_windows_use_grid_clouds_preserve_weather_and_keep_unknown_pop_unknown():
    forecast=nws.normalize_forecast(document(), NOW)
    original=copy.deepcopy(forecast)
    grid={"properties": {"skyCover": layer([100, 90, 85, 50, 50, None])}}
    nws.add_hourly_windows(forecast, hourly(), grid, NOW)
    windows=forecast['periods'][0]['hourlyWindows']
    assert windows[0]['condition']=='Cloudy' and windows[0]['minCloudPct']==100
    assert windows[0]['minChancePct'] is None
    assert windows[1]['startTime']==(NOW+timedelta(hours=1)).isoformat()
    assert windows[1]['minCloudPct']==85 and windows[1]['maxCloudPct']==90
    assert windows[1]['minChancePct']==0 and windows[1]['maxChancePct']==10
    assert windows[2]['condition']=='Partly cloudy' and windows[2]['weather']==['Rain']
    assert windows[-1]['minCloudPct'] is None and windows[-1]['condition']=='Partly Cloudy'
    assert forecast['periods'][0]['detailedForecast']==original['periods'][0]['detailedForecast']
    assert windows[-1]['endTime']==forecast['periods'][0]['endTime']


def test_hourly_gaps_and_category_changes_are_not_smoothed_over():
    forecast=nws.normalize_forecast(document(), NOW)
    hours=hourly();del hours['properties']['periods'][2]
    grid={"properties": {"skyCover": layer([20, 21, 39, 40, 60, 80])}}
    nws.add_hourly_windows(forecast, hours, grid, NOW)
    windows=forecast['periods'][0]['hourlyWindows']
    assert [w['condition'] for w in windows]==['Clear','Mostly clear','Partly cloudy','Mostly cloudy','Cloudy']
    assert nws.timestamp(windows[1]['endTime'])<nws.timestamp(windows[2]['startTime'])


def test_amounts_are_day_night_totals_not_hourly_and_partial_windows_are_omitted():
    forecast=nws.normalize_forecast(document(), NOW)
    day_start,day_end=nws.amount_window(forecast['periods'][0])
    grid={"properties":{key:{'uom':'wmoUnit:mm','values':[
        {'validTime':day_start.isoformat()+'/PT6H','value':value},
        {'validTime':(day_start+timedelta(hours=6)).isoformat()+'/PT6H','value':value}]}
        for key,value in [('quantitativePrecipitation',2.54),('snowfallAmount',25.4),('iceAccumulation',None)]}}
    nws.add_precip_amounts(forecast, grid, NOW)
    amounts=forecast['periods'][0]['precipAmounts']
    assert [(a['kind'],round(a['inches'],4)) for a in amounts]==[('Liquid precipitation',.2),('Snow',2.)]
    assert all(nws.timestamp(a['endTime'])-nws.timestamp(a['startTime'])==timedelta(hours=12) for a in amounts)
    assert 'precipAmounts' not in forecast['periods'][1]
    assert nws.interval_total([(day_start,day_start+timedelta(hours=6),1)],day_start,day_end) is None
    assert nws.interval_total([(day_start-timedelta(hours=1),day_end,1)],day_start,day_end) is None
    assert nws.interval_total([(day_start-timedelta(hours=1),day_end+timedelta(hours=1),0)],day_start,day_end)==0


def test_amount_windows_shift_to_seven_during_daylight_saving_time():
    for date,hour in [('2026-11-17',6),('2026-07-17',7)]:
        for day in [True,False]:
            period={'startTime':date+('T06:00:00-06:00' if day else 'T18:00:00-06:00'),'isDaytime':day}
            start,end=nws.amount_window(period)
            assert start.astimezone(nws.CENTRAL).hour==hour+(0 if day else 12)
            assert end.astimezone(nws.CENTRAL).hour==hour+(12 if day else 0)
            assert end-start==timedelta(hours=12)


def test_falling_target_overrides_high_even_in_json_without_rewriting_narrative():
    upstream=document();upstream['data']['text'][0]='Rain likely. Temperature falling to around 47 by 5pm.'
    forecast=nws.normalize_forecast(upstream,NOW)
    p=forecast['periods'][0]
    assert p['temperature']==47 and p['temperatureTrend']=='falling' and p['trendTargetTime']=='5pm'
    assert p['detailedForecast']==upstream['data']['text'][0]


def test_details_extend_beyond_48_hours_and_dont_invent_missing_sky_cover():
    h=hourly();h['properties']['periods']=h['properties']['periods'][:1]
    for k in ('startTime','endTime'):
        h['properties']['periods'][0][k]=(nws.timestamp(h['properties']['periods'][0][k])+timedelta(days=3)).isoformat()
    _,rows=nws.normalize_hourly(h,{},NOW)
    assert len(rows)==1 and rows[0][-1] is None


def test_collector_prepares_detail_and_public_request_uses_only_saved_data():
    store=MemoryStore();forecast=nws.normalize_forecast(document(),NOW)
    grid_url='https://api.weather.gov/gridpoints/MPX/104,70'
    responses={nws.POINT_URL:{'properties':{'forecastHourly':grid_url+'/forecast/hourly','forecastGridData':grid_url}},
        grid_url+'/forecast/hourly':hourly(),grid_url:{'properties':{'updateTime':'2026-10-09T16:00:00Z','skyCover':layer([100]*6)}}}
    with patch('app.get_forecast',return_value=forecast),patch('app.download',side_effect=lambda url:json.dumps(responses[url]).encode()) as upstream:
        collector.collect_forecast(store,NOW)
    assert upstream.call_count==3
    saved=store.read_json('live/forecast.json')
    assert saved['periods'][0]['hourlyWindows'][0]['condition']=='Cloudy'
    assert saved['gridSourceUrl']==grid_url
    app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as upstream:
        response=app.app.test_client().get('/api/forecast')
    assert response.status_code==200 and response.json['periods'][0]['hourlyWindows']
    upstream.assert_not_called()


def test_detail_outage_keeps_official_narrative_and_removes_old_detail():
    forecast=nws.normalize_forecast(document(),NOW)
    forecast['periods'][0]['hourlyWindows']=[{'condition':'old'}]
    forecast['hourlyUpdatedAt']='old'
    store=MemoryStore()
    with patch('app.get_forecast',return_value=forecast),patch('app.download',side_effect=TimeoutError):
        collector.collect_forecast(store,NOW)
    saved=store.read_json('live/forecast.json')
    assert saved['periods'][0]['detailedForecast']==forecast['periods'][0]['detailedForecast']
    assert 'hourlyWindows' not in saved['periods'][0] and 'hourlyUpdatedAt' not in saved
