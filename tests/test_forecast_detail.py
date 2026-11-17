from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import app
import collector
import nws_forecast as nws
from test_forecast import document
from test_realtime import MemoryStore

NOW=datetime(2026,10,9,17,tzinfo=timezone.utc)


def hourly(count=6):
    return {'properties':{'updateTime':'2026-10-09T16:00:00Z','periods':[
        {'startTime':(NOW+timedelta(hours=i)).isoformat(),'endTime':(NOW+timedelta(hours=i+1)).isoformat(),
         'temperature':50+i,'temperatureUnit':'F','shortForecast':'Rain' if i==3 else 'Partly Cloudy',
         'isDaytime':True,'windSpeed':'5 to 10 mph','windDirection':'NW',
         'dewpoint':{'value':5,'unitCode':'wmoUnit:degC'},
         'probabilityOfPrecipitation':{'value':None if i==0 else 60 if i==3 else 0}}
        for i in range(count)]}}


def layer(values,unit='wmoUnit:percent'):
    return {'uom':unit,'values':[{'validTime':(NOW+timedelta(hours=i)).isoformat()+'/PT1H','value':value} for i,value in enumerate(values)]}


def test_custom_cloud_categories_and_missing_data():
    assert [nws.cloud_label(v) for v in [None,0,20,20.1,39.9,40,59.9,60,79.9,80,100]]==[
        None,'Clear','Clear','Mostly clear','Mostly clear','Partly cloudy','Partly cloudy','Mostly cloudy','Mostly cloudy','Cloudy','Cloudy']


def test_hourly_values_preserve_official_weather_and_unknown_chance():
    forecast=nws.normalize_forecast(document(),NOW)
    original=[p['detailedForecast'] for p in forecast['periods']]
    grid={'properties':{'skyCover':layer([100,90,85,50,20,None]),'apparentTemperature':layer([10]*6,'wmoUnit:degC')}}
    nws.add_hourly_forecast(forecast,hourly(),grid,NOW)
    rows=forecast['hourly']
    assert len(rows)==6 and rows[0]['temperatureF']==50 and rows[0]['condition']=='Cloudy'
    assert rows[0]['precipChancePct'] is None and rows[1]['precipChancePct']==0
    assert rows[0]['dewpointF']==41 and rows[0]['feelsLikeF']==50
    assert rows[0]['windSpeed']=='5 to 10 mph' and rows[0]['windDirection']=='NW'
    assert rows[3]['condition']=='Rain' and rows[3]['cloudCoverPct']==50
    assert rows[-1]['cloudCoverPct'] is None and rows[-1]['condition']=='Partly Cloudy'
    assert [p['detailedForecast'] for p in forecast['periods']]==original
    assert all('hourlyWindows' not in p and 'precipAmounts' not in p for p in forecast['periods'])


def test_hourly_horizon_stays_48_hours_for_refresh_but_gaps_and_invalid_temps_not_filled():
    data=hourly(60);data['properties']['periods'][2]['temperature']=None
    del data['properties']['periods'][3]
    forecast=nws.normalize_forecast(document(),NOW)
    nws.add_hourly_forecast(forecast,data,{},NOW)
    rows=forecast['hourly']
    assert len(rows)==46 and nws.timestamp(rows[-1]['startTime'])==NOW+timedelta(hours=47)
    assert rows[1]['endTime']!=rows[2]['startTime']
    assert all(r['cloudCoverPct'] is None and r['feelsLikeF'] is None for r in rows)


def test_falling_target_remains_without_rewriting_narrative():
    upstream=document();upstream['data']['text'][0]='Rain likely. Temperature falling to around 47 by 5pm.'
    p=nws.normalize_forecast(upstream,NOW)['periods'][0]
    assert p['temperature']==47 and p['temperatureTrend']=='falling' and p['trendTargetTime']=='5pm'
    assert p['detailedForecast']==upstream['data']['text'][0]


def test_collector_prepares_hourly_and_public_request_uses_saved_data_only():
    store=MemoryStore();forecast=nws.normalize_forecast(document(),NOW);grid_url='https://api.weather.gov/gridpoints/MPX/104,70'
    responses={nws.POINT_URL:{'properties':{'forecastHourly':grid_url+'/forecast/hourly','forecastGridData':grid_url}},
        grid_url+'/forecast/hourly':hourly(),grid_url:{'properties':{'skyCover':layer([100]*6)}}}
    with patch('app.get_forecast',return_value=forecast),patch('app.download',side_effect=lambda url:json.dumps(responses[url]).encode()) as upstream:
        collector.collect_forecast(store,NOW)
    assert upstream.call_count==3
    saved=store.read_json('live/forecast.json');assert saved['hourly'][0]['condition']=='Cloudy'
    assert 'hourlyWindows' not in saved['periods'][0] and 'precipAmounts' not in saved['periods'][0]
    app._cache.clear()
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as upstream:
        response=app.app.test_client().get('/api/forecast')
    assert response.status_code==200 and response.json['hourly']
    upstream.assert_not_called()


def test_hourly_outage_does_not_break_text_forecast_or_leave_stale_detail():
    forecast=nws.normalize_forecast(document(),NOW)
    forecast['periods'][0]['hourlyWindows']=[{'condition':'old'}];forecast['hourly']=[{'condition':'old'}]
    forecast['hourlyUpdatedAt']='old';store=MemoryStore()
    with patch('app.get_forecast',return_value=forecast),patch('app.download',side_effect=TimeoutError):collector.collect_forecast(store,NOW)
    saved=store.read_json('live/forecast.json')
    assert saved['periods'][0]['detailedForecast']==forecast['periods'][0]['detailedForecast']
    assert 'hourly' not in saved and 'hourlyWindows' not in saved['periods'][0] and 'hourlyUpdatedAt' not in saved
