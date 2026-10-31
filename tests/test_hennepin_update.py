"""The Current updater must preserve other products, schedules and warm instances."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'weather-lab-261028-205713-506d'


def run_update(tmp_path, fail='', existing=False):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub=r'''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project=os.environ['HC_PROJECT']
with open(os.environ['HC_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
 if a[0]=='clone':
  dst=pathlib.Path(a[-1]);dst.mkdir();(dst/'verify_weather_site.py').write_text('print("six weather tabs ready")')
 else:print('d5169658cf5352604bfbc80c49a184ab2c70a445')
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3]==['scheduler','jobs','list']:
 jobs=[{'name':'projects/'+project+'/locations/us-central1/jobs/weather-live-radar','state':'ENABLED'}]
 if os.environ.get('HC_EXISTING')=='yes':jobs.append({'name':'projects/'+project+'/locations/us-central1/jobs/weather-live-hennepin-current','state':'PAUSED'})
 print(json.dumps(jobs))
elif a[:2]==['builds','submit'] and os.environ.get('HC_FAIL')=='build':sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('HC_FAIL')=='seed':sys.exit(1)
'''
    for name in ('gcloud','git'):
        p=binary/name;p.write_text(stub.replace('#!/usr/bin/env python3','#!'+sys.executable,1));p.chmod(0o755)
    env={**os.environ,'HOME':str(home),'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HC_PROJECT':PROJECT,'HC_LOG':str(log),'HC_FAIL':fail,'HC_EXISTING':'yes' if existing else 'no'}
    result=subprocess.run(['bash',str(ROOT/'update-weather-lab-hennepin-current.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_current_updater_seeds_before_publishing_and_changes_only_new_schedule(tmp_path):
    result,calls=run_update(tmp_path);assert result.returncode==0,result.stderr
    collector=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-collector'])
    seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    web=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-lab'])
    assert collector < seed < web
    changes=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3]!='list']
    assert len(changes)==1 and changes[0][3:6]==['create','http','weather-live-hennepin-current']
    assert '--schedule=*/5 * * * *' in changes[0] and '--max-retry-attempts=0' in changes[0]
    assert '--oidc-service-account-email=weather-scheduler@'+PROJECT+'.iam.gserviceaccount.com' in changes[0]
    for c in calls:
        assert not any(v in c for v in ['delete','billing','add-iam-policy-binding'])
        assert not any(v.startswith(('--min=', '--min-instances=', '--max-instances=', '--update-env-vars=')) for v in c)
        if c[:4]==['gcloud','run','services','update']:assert '--project='+PROJECT in c
    assert 'Current page update complete' in result.stdout


def test_existing_paused_current_job_updated_and_resumed(tmp_path):
    result,calls=run_update(tmp_path,existing=True);assert result.returncode==0,result.stderr
    assert any(c[:6]==['gcloud','scheduler','jobs','update','http','weather-live-hennepin-current'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-hennepin-current'] for c in calls)


def test_failed_build_does_not_change_services_or_schedules(tmp_path):
    result,calls=run_update(tmp_path,fail='build');assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)
    assert not any(c[:3]==['gcloud','scheduler','jobs'] and c[3]!='list' for c in calls)


def test_failed_seed_does_not_publish_current_tab_or_change_schedules(tmp_path):
    result,calls=run_update(tmp_path,fail='seed');assert result.returncode!=0
    assert not any(c[:5]==['gcloud','run','services','update','weather-lab'] for c in calls)
    assert not any(c[:3]==['gcloud','scheduler','jobs'] and c[3]!='list' for c in calls)
