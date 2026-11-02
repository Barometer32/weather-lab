"""Retire TEST only; preserve the five weather pages and radar geolocation."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


def test_only_test_cache_and_archive_objects_are_removed():
    from remove_test_data import purge
    deleted=[]
    names=['live/test-weather.json','live/test-input-mesonet-0.json','live/test-input-rwis-1.json',
           'live/test-input-hfmetar-1.json','live/test-input-airports.json','live/test-history-cleanup.json',
           'test-history/v1/20261101_1800/mesonet.jsonl.gz',
           'live/forecast.json','live/metar-clouds.json','radar/scan.bin','live/test-input-unrelated-0.json',
           'live/test-weather.json.backup','test-history/unrelated/data.json']
    class Blob:
        generation=7
        def __init__(self,name):self.name=name
        def delete(self,**kwargs):
            assert kwargs['if_generation_match']==7
            deleted.append(self.name)
    class Bucket:
        def list_blobs(self,prefix):return [Blob(name) for name in names if name.startswith(prefix)]
    purge(Bucket())
    assert set(deleted)==set(names[:7])


def test_removed_routes_return_404_without_touching_data(monkeypatch):
    import app,collector
    def no_read(*args):pytest.fail('Retired TEST must not read or collect observations')
    monkeypatch.setattr(app,'get_store',no_read);monkeypatch.setattr(collector,'get_store',no_read)
    client=app.app.test_client()
    for endpoint in ['conditions','history','location','forecast']:
        assert client.get('/api/test/'+endpoint).status_code==404
    assert client.get('/static/test-weather.js').status_code==404
    assert collector.app.test_client().post('/collect/test-weather').status_code==404
    html=(ROOT/'static/index.html').read_text()
    import re
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['metar','radar','satellite','forecast','air-quality']
    assert 'id="radar-location"' in html and 'radar-location.js?v=radar-location-v2' in html
    assert 'const historyHours=4;' in (ROOT/'static/metar-views.js').read_text()
    assert "weather_schedule metar-clouds '0,5,10 * * * *'" in (ROOT/'deploy.sh').read_text()
    assert 'WeatherTest' not in (ROOT/'static/app.js').read_text()
    assert not (ROOT/'point_weather.py').exists() and not (ROOT/'point_history.py').exists()


@pytest.mark.parametrize('mode',['present','absent','build-fail','denied'])
def test_remove_installer_only_mutates_test_jobs_and_preserves_service_settings(tmp_path,mode):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!REALPY
import os,sys,json,pathlib,shutil
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d';root=pathlib.Path(os.environ['REMOVE_TEST_ROOT']);mode=os.environ['REMOVE_TEST_MODE']
with open(os.environ['REMOVE_TEST_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='python3':
 if a and a[0]=='-' and len(a)==3 and a[1].endswith('/page.html'):print('verified');sys.exit(0)
 os.execv(sys.executable,[sys.executable,*a])
elif name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);p.mkdir();(p/'verify_weather_site.py').write_text('print("five pages ready")')
 elif 'rev-parse' in a:print('a'*40)
elif name=='curl':pathlib.Path(a[a.index('-o')+1]).write_text((root/'static/index.html').read_text())
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/existing/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3]==['scheduler','jobs','describe']:
 if mode=='denied':print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 if mode=='absent':print('NOT_FOUND',file=sys.stderr);sys.exit(1)
 print(json.dumps({'state':'ENABLED'}))
elif a[:3]==['run','jobs','describe']:
 if mode=='absent' or a[3]=='weather-test-cleanup':print('NOT_FOUND',file=sys.stderr);sys.exit(1)
 print('{}')
elif a[:4]==['run','jobs','executions','list']:
 print(json.dumps([{'metadata':{'name':'weather-test-seed-active'},'status':{'conditions':[{'type':'Completed','status':'Unknown'}]}},{'metadata':{'name':'weather-test-seed-done'},'status':{'completionTime':'2026-11-02T01:00:00Z'}}]))
elif a[:2]==['builds','submit'] and mode=='build-fail':sys.exit(1)
'''.replace('REALPY',sys.executable)
    for name in ['python3','git','gcloud','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'HOME':str(home),'REMOVE_TEST_ROOT':str(ROOT),'REMOVE_TEST_LOG':str(log),'REMOVE_TEST_MODE':mode}
    result=subprocess.run(['bash',str(ROOT/'remove-weather-test.sh'),PROJECT],env=env,text=True,capture_output=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert (result.returncode==0)==(mode in ['present','absent']),result.stderr
    schedules=[c for c in calls if c[:3]==['gcloud','scheduler','jobs']]
    assert all('weather-live-test-weather' in c for c in schedules)
    canceled=[c[5] for c in calls if c[:5]==['gcloud','run','jobs','executions','cancel']]
    assert canceled==(['weather-test-seed-active'] if mode in ['present','build-fail'] else [])
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    assert [c[4] for c in updates]==(['weather-collector','weather-lab'] if mode in ['present','absent'] else [])
    assert all(not any(v.startswith(('--memory','--min','--set-env','--service-account')) for v in c) for c in updates)
    jobs=[c for c in calls if c[:3]==['gcloud','run','jobs'] and c[3] in ('delete','deploy','execute')]
    assert all(c[4] in ['weather-test-seed','weather-test-cleanup'] for c in jobs)
    if mode=='denied':assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)
    if mode in ['present','absent']:
        assert any(c[:5]==['gcloud','run','jobs','delete','weather-test-cleanup'] for c in calls)
        assert not any('domain-mappings' in c or c[:3]==['gcloud','billing','projects'] for c in calls)
