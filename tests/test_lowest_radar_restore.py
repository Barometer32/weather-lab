"""Restore the morning source, not the experimental all-elevation branch."""
import json
from pathlib import Path
import pytest
from test_latest_site_restore import run_restore
from test_site_cutover_readiness import fixture
from verify_lowest_radar_site import verify_lowest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure',['','build','seed'])
def test_restore_lowest_only_and_preserve_existing_web_settings(tmp_path,failure):
    options={failure+'_fail':1} if failure else {}
    result,calls=run_restore(tmp_path,extra_env={'LATEST_LOWEST':'1'},script='restore-weather-lowest-radar.sh',**options)
    updates=[c for c in calls if c[:5]==['gcloud','run','services','update','weather-lab']]
    assert result.returncode!=0 if failure else result.returncode==0,result.stderr
    assert any(c[0]=='git' and 'restore-lowest-radar-20261103' in c for c in calls)
    if failure:
        assert not updates
    else:
        assert len(updates)==1
        assert not any(arg.startswith(('--min','--max','--memory','--cpu','--set-env-vars')) for arg in updates[0])
        seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
        publish=calls.index(updates[0]);assert seed<publish
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-radar'] for c in calls)
    assert not any(c[:3]==['gcloud','projects','create'] for c in calls)


def lowest_fixture():
    data=fixture()
    radar=json.loads(data['/api/radar?site=KMPX'])
    radar['elevationDegrees']=.5
    radar['frames'][0]['elevationDegrees']=.5
    data['/api/radar?site=KMPX']=json.dumps(radar).encode()
    data['/static/metar-views.js?v=rolling-observations-v1']=(ROOT/'static/metar-views.js').read_bytes()
    return data


def test_verifier_accepts_twelve_internal_hours_and_four_displayed_frames():
    data=lowest_fixture()
    verify_lowest('https://weather.example.run.app',data.__getitem__)


@pytest.mark.parametrize('mode',['selector','higher-frame','higher-default','products'])
def test_verifier_rejects_experimental_radar(mode):
    data=lowest_fixture()
    radar=json.loads(data['/api/radar?site=KMPX'])
    if mode=='selector':data['/']+=b'<select id="radar-product"></select>'
    if mode=='higher-frame':radar['frames'][0]['elevationDegrees']=1.8
    if mode=='higher-default':radar['elevationDegrees']=1.8
    if mode=='products':radar['products']=[{'id':'storm-total'}]
    data['/api/radar?site=KMPX']=json.dumps(radar).encode()
    with pytest.raises(ValueError):verify_lowest('https://weather.example.run.app',data.__getitem__)


@pytest.mark.parametrize('hours,ready',[(3,False),(4,True)])
def test_forecast_cutover_requires_only_the_working_four_hour_loop(hours, ready):
    from datetime import datetime, timedelta, timezone

    data = lowest_fixture()
    metars = json.loads(data['/api/station-plots'])
    start = datetime(2026,11,6,12,tzinfo=timezone.utc)
    metars['history'] = [
        {'hour':(start + timedelta(hours=i)).isoformat(),
         'stations':[{'station':'KFCM','reportType':'METAR','time':(start + timedelta(hours=i, minutes=-7)).isoformat()}]}
        for i in range(hours)
    ]
    data['/api/station-plots'] = json.dumps(metars).encode()
    if ready:
        verify_lowest('https://weather.example.run.app', data.__getitem__, metar_hours=4)
    else:
        with pytest.raises(ValueError, match='4 usable all-airport METAR frames'):
            verify_lowest('https://weather.example.run.app', data.__getitem__, metar_hours=4)
