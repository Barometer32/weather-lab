"""Exercise the Cloud Shell installer with command stubs, never live mutations."""
import json
import os
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


@pytest.mark.parametrize('failure',['none','build','seed'])
def test_new_page_installer_preserves_existing_services_and_jobs(tmp_path,failure):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    code='''#!/usr/bin/env python3
import os,sys,json,pathlib,shutil
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d';root=pathlib.Path(os.environ['TEST_SETUP_ROOT'])
with open(os.environ['TEST_SETUP_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);p.mkdir();(p/'verify_weather_site.py').write_text('print("old pages verified")');(p/'verify_test_weather.py').write_text('print("test verified")')
 elif 'rev-parse' in a:print('a'*40)
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/existing/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3]==['scheduler','jobs','describe']:
 if a[3]=='weather-live-metar-clouds':print('weather-scheduler@'+project+'.iam.gserviceaccount.com')
 elif '--format=json' in a:print('NOT_FOUND',file=sys.stderr);sys.exit(1)
 else:print('ENABLED')
elif a[:2]==['builds','submit'] and os.environ['TEST_SETUP_FAILURE']=='build':sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ['TEST_SETUP_FAILURE']=='seed':sys.exit(1)
'''
    for name in ['git','gcloud']:
        p=binary/name;p.write_text(code);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'HOME':str(home),'TEST_SETUP_ROOT':str(ROOT),'TEST_SETUP_LOG':str(log),'TEST_SETUP_FAILURE':failure}
    result=subprocess.run(['bash',str(ROOT/'setup-weather-lab-test.sh'),PROJECT],env=env,text=True,capture_output=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert (result.returncode==0)==(failure=='none'),result.stderr
    updates=[c for c in calls if c[:3]==['gcloud','run','services'] and c[3]=='update']
    assert all('--image=' in ' '.join(c) and not any(x.startswith(('--set-env-vars','--min','--memory','--service-account')) for x in c) for c in updates)
    assert not any(c[:3] in [['gcloud','projects','create'],['gcloud','billing','projects']] for c in calls)
    mutating_schedules=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3]!='describe']
    assert all('weather-live-test-weather' in c for c in mutating_schedules)
    if failure=='build':assert not updates and not mutating_schedules
    elif failure=='seed':assert len(updates)==1 and updates[0][4]=='weather-collector' and not mutating_schedules
    else:
        assert [c[4] for c in updates]==['weather-collector','weather-lab']
        execution=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
        publish=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-lab'])
        assert execution<publish
        assert any('--schedule=*/5 * * * *' in c and '--max-retry-attempts=0' in c for c in mutating_schedules)
