"""Exercise deployment ordering without access to Google Cloud."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'weather-lab-261028-205713-506d'


def run_update(tmp_path, fail=''):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub=r'''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d'
with open(os.environ['IR_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
 if 'clone' in a:
  dst=pathlib.Path(a[-1]);dst.mkdir();(dst/'verify_weather_site.py').write_text('print("all pages ready")')
 else:print('a'*40)
elif name=='python3':
 if any(x.startswith('https://weather.example') for x in a):sys.stdin.read()
 else:os.execv(os.environ['IR_PYTHON'],[os.environ['IR_PYTHON'],*a])
elif name=='gcloud':
 if a[:3]==['run','services','describe']:
  if '--format=value(status.url)' in a:print('https://weather.example.run.app')
  else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
 elif a[:2]==['builds','submit'] and os.environ.get('IR_FAIL')=='build':sys.exit(1)
 elif a[:3]==['run','jobs','execute'] and os.environ.get('IR_FAIL')=='cleanup':sys.exit(1)
'''
    for name in ('gcloud','git','curl','python3'):
        path=binary/name;path.write_text(stub.replace('#!/usr/bin/env python3','#!'+sys.executable,1));path.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'IR_LOG':str(log),'IR_FAIL':fail,'IR_PYTHON':sys.executable,'WEATHER_SOURCE_COMMIT':'a'*40}
    result=subprocess.run(['bash',str(ROOT/'remove-weather-infrared.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(row) for row in log.read_text().splitlines()]


def test_updates_only_service_images_and_runs_scoped_cleanup_after_build(tmp_path):
    result,calls=run_update(tmp_path)
    assert result.returncode==0,result.stderr
    build=next(i for i,c in enumerate(calls) if c[:3]==['gcloud','builds','submit'])
    updates=[(i,c) for i,c in enumerate(calls) if c[:4]==['gcloud','run','services','update']]
    cleanup=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','deploy'])
    assert [c[4] for _,c in updates]==['weather-collector','weather-lab']
    assert all(build<i<cleanup for i,_ in updates)
    assert all(any(x.startswith('--image=') for x in c) for _,c in updates)
    assert not any(c[:2]==['gcloud','scheduler'] or 'billing' in c or 'add-iam-policy-binding' in c for c in calls)
    assert '--args=-u,remove_infrared_data.py' in calls[cleanup]


def test_failed_build_preserves_both_live_services_and_all_data(tmp_path):
    result,calls=run_update(tmp_path,fail='build')
    assert result.returncode!=0
    assert not any(c[:3]==['gcloud','run','services'] and c[3]!='describe' or c[:3]==['gcloud','run','jobs'] for c in calls)
