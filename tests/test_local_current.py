from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import copy
import math
import pytest
import local_current as local
import regional_madis

NOW=datetime(2026,10,23,1,tzinfo=timezone.utc)

class Store:
    def __init__(self,data=None):self.data=copy.deepcopy(data or {})
    def read_json(self,key):return copy.deepcopy(self.data.get(key))
    def write_json(self,key,value):self.data[key]=copy.deepcopy(value)


def row(station='HPN20',minutes=7,**changes):
    return {'station':station,'name':'Hopkins MN US HENNEPIN','network':'Hennepin West','source':'NOAA MADIS',
            'lat':local.CENTER[0],'lon':local.CENTER[1],'time':local.iso(NOW-timedelta(minutes=minutes)),
            'tempF':60.,'dewpointF':40.,'wind':{'speedMph':10.,'direction':225},**changes}


def rows():return [row('HPN20',7),row('HPN24',12,name='Edina MN US HENNEPIN'),row('HPN25',17,name='Minnetonka MN US HENNEPIN')]


def saved(reports=None):
    reports=reports or rows()
    return {'version':local.VERSION,'reports':reports,'checkedAt':local.iso(NOW),'lastGood':local.candidate(reports,NOW),'files':{}}


def test_strict_radius_uses_actual_coordinates_and_excludes_crystal_msp():
    assert local.distance_miles(*local.CENTER)==0
    data=local.normalize([row('KFCM',lat=44.827,lon=-93.457),row('KMIC',lat=45.062,lon=-93.354),
                          row('KMSP',lat=44.882,lon=-93.222),row('NORTH',lat=local.CENTER[0]+.146),
                          row('INSIDE',lat=local.CENTER[0]+.14)],NOW)
    assert {r['station'] for r in data}=={'KFCM','INSIDE'}
    airport=next(r for r in data if r['station']=='KFCM')
    assert airport['displayName']=='Eden Prairie · Flying Cloud Airport'
    assert 6.4<airport['distanceMiles']<6.9


def test_city_names_replace_ids_and_remove_cwop_callsigns():
    assert local.place(row())=='Hopkins'
    assert local.place(row(network='CWOP',name='DW1234 MINNETONKA MN US'))=='Minnetonka'
    assert local.place(row(network='Hennepin West',name='Eden Prairie (HE30B) MN US HENNEPIN'))=='Eden Prairie'
    assert local.place(row(name=None))=='Unnamed local station'


def test_relative_15_minute_cohort_and_arithmetic_time_average():
    reports=[row('A',2),row('B',7),row('C',17),row('OLD',18)]
    data=local.candidate(reports,NOW)
    assert data['available'] and data['stationCount']==3
    assert data['timestampSpreadSeconds']==900
    expected=datetime.fromtimestamp(sum((NOW-timedelta(minutes=m)).timestamp() for m in [2,7,17])/3,timezone.utc)
    assert data['observedAt']==local.iso(expected)
    old=next(r for r in data['stations'] if r['station']=='OLD')
    assert not old['included'] and '15 min' in old['status']
    assert local.candidate(reports,NOW+timedelta(hours=2))['available'],'clock age is separate from station-to-station coherence'


def test_partial_field_qc_keeps_other_fields_but_requires_three_per_summary_field():
    reports=rows()+[row('D',10,tempF=None)]
    data=local.candidate(reports,NOW)
    assert data['available'] and data['counts']=={'temperature':3,'dewpoint':4,'wind':4}
    d=next(r for r in data['stations'] if r['station']=='D')
    assert d['includedFields']==['Dewpoint','Wind']
    reports[0]['tempF']=None
    assert not local.candidate(reports,NOW)['available']


def test_station_deduplication_latest_invalid_report_and_circular_wind():
    data=local.candidate([row('A',wind={'speedMph':10.,'direction':359}),
                          row('B',wind={'speedMph':10.,'direction':1}),
                          row('C',wind={'speedMph':0.,'direction':None}),row('A',minutes=15,tempF=90)],NOW)
    assert data['available'] and data['stationCount']==3 and data['tempF']==60
    assert math.isclose(data['wind']['direction']%360,0,abs_tol=1e-8) or math.isclose(data['wind']['direction'],360,abs_tol=1e-8)
    assert data['wind']['speedMph']==pytest.approx(20/3)
    bad=row('HPN20',1,tempF=None,dewpointF=None,wind={'speedMph':None,'direction':None})
    result=local.candidate(rows()+[bad],NOW)
    assert not result['available']
    assert next(r for r in result['stations'] if r['station']=='HPN20')['status'].startswith('No usable')


def test_source_outage_preserves_observation_time_and_has_no_legacy_cache_fallback():
    store=Store({local.KEY:saved()})
    def fail(url,metadata):raise TimeoutError('offline')
    result=local.collect(store,NOW+timedelta(minutes=10),download=fail)
    assert result['current']['observedAt']==saved()['lastGood']['observedAt']
    assert len(result['sourceFailures'])==4
    assert 'history' not in result
    legacy={'version':'madis-five-minute-three-airports-v3','lastGood':{'tempF':99}}
    assert local.present(legacy,NOW)['current'] is None


def test_collect_reads_this_hour_and_previous_and_publishes_incoming_five_minute_reports():
    store=Store();calls=[]
    def download(url,metadata):calls.append(url);return b'file',{'etag':'v1'}
    with patch('regional_madis.parse_file',return_value=rows()) as mesonet,patch('madis_observations.parse_file',return_value=[]):
        result=local.collect(store,NOW,download=download)
    assert result['available']
    assert len(calls)==4 and all('madisPublic1' in url for url in calls)
    assert any('20261023_0100' in url for url in calls) and any('20261023_0000' in url for url in calls)
    assert mesonet.call_args.kwargs['window_end']>NOW
    assert mesonet.call_args.kwargs['include_invalid'] is True
    assert mesonet.call_args.kwargs['bounds'][0]<local.CENTER[0]


def test_minimum_counts_hold_last_complete_group_and_timestamp():
    store=Store({local.KEY:saved()})
    fresh=[row('HPN20',1,tempF=None,dewpointF=None,wind={'speedMph':None,'direction':None})]
    with patch('regional_madis.parse_file',return_value=fresh),patch('madis_observations.parse_file',return_value=[]):
        result=local.collect(store,NOW,download=lambda url,meta:(b'new',{}))
    assert result['held']
    assert result['current']==saved()['lastGood']
    assert not result['candidate']['available']


def test_api_and_initial_page_only_read_saved_local_state():
    import app
    app._cache.clear();store=Store({local.KEY:saved()})
    with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('regional_madis.fetch') as source,patch('app.download') as other:
        client=app.app.test_client();response=client.get('/api/observations');page=client.get('/').get_data(as_text=True)
    assert response.status_code==200 and response.json['version']==local.VERSION
    assert response.json['current']['stationCount']==3
    assert 'tab-metar-clouds' in page and 'cloud-views.js' in page
    assert 'local-station-details' not in page and '10-MILE RADIUS' not in page
    assert 'id="sun-angle"' in page and 'id="history"' not in page
    source.assert_not_called();other.assert_not_called()
