"""Retire only the MADIS schedule and preserve the existing weather services."""
import json, os, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


def run_update(tmp_path,fail='',existing=True):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub=r'''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project=os.environ['VIEW_PROJECT']
with open(os.environ['VIEW_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);p.mkdir();(p/'verify_weather_site.py').write_text('print("PLOTS and CLOUDS ready")')
 else:print('99cfa45689a74f6c18955b4afb20e57111fd1a26')
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3]==['scheduler','jobs','list']:
 names=['weather-live-metar-clouds','weather-live-radar','unrelated']
 if os.environ['VIEW_EXISTING']=='yes':names.append('weather-live-madis-map')
 print(json.dumps([{'name':'projects/'+project+'/locations/us-central1/jobs/'+n,'state':'ENABLED'} for n in names]))
elif a[:2]==['builds','submit'] and os.environ['VIEW_FAIL']=='build':sys.exit(1)
elif a[:3]==['scheduler','jobs','delete'] and os.environ['VIEW_FAIL']=='delete':sys.exit(1)
'''
    for name in ('git','gcloud'):
        p=binary/name;p.write_text(stub.replace('#!/usr/bin/env python3','#!'+sys.executable,1));p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'VIEW_LOG':str(log),'VIEW_PROJECT':PROJECT,'VIEW_FAIL':fail,'VIEW_EXISTING':'yes' if existing else 'no'}
    result=subprocess.run(['bash',str(ROOT/'update-weather-lab-airport-views.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_removes_only_madis_after_build_and_preserves_service_settings(tmp_path):
    result,calls=run_update(tmp_path);assert result.returncode==0,result.stderr
    mutations=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3]!='list']
    assert len(mutations)==1 and mutations[0][3:5]==['delete','weather-live-madis-map']
    build=next(i for i,c in enumerate(calls) if c[:3]==['gcloud','builds','submit'])
    removal=calls.index(mutations[0])
    updates=[(i,c) for i,c in enumerate(calls) if c[:4]==['gcloud','run','services','update']]
    assert build<removal<updates[0][0] and [c[4] for _,c in updates]==['weather-collector','weather-lab']
    assert not any(v.startswith(('--min=','--min-instances=','--update-env-vars=')) for c in calls for v in c)
    assert not any('billing' in c or 'add-iam-policy-binding' in c or c[:3]==['gcloud','run','jobs'] for c in calls)


def test_no_madis_schedule_is_a_valid_idempotent_state(tmp_path):
    result,calls=run_update(tmp_path,existing=False);assert result.returncode==0,result.stderr
    assert not any(c[:3]==['gcloud','scheduler','jobs'] and c[3]!='list' for c in calls)


def test_build_failure_preserves_running_services_and_all_schedules(tmp_path):
    result,calls=run_update(tmp_path,fail='build');assert result.returncode!=0
    assert not any(c[:4] in (['gcloud','run','services','update'],['gcloud','scheduler','jobs','delete']) for c in calls)


def test_delete_failure_stops_before_replacing_collector(tmp_path):
    result,calls=run_update(tmp_path,fail='delete');assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)


def test_retired_madis_routes_cannot_collect_or_serve_data():
    import app, collector
    assert app.app.test_client().get('/api/madis-map').status_code==404
    assert collector.app.test_client().post('/collect/madis-map').status_code==404
