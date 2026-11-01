"""Ensure the experimental installer cannot reschedule existing weather feeds."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


@pytest.mark.parametrize('seed_failure',[False,True])
def test_setup_preserves_other_schedules_and_only_publishes_after_seed(tmp_path,seed_failure):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    script='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d'
with open(os.environ['EXPMET_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);p.mkdir();(p/'expmet.py').write_text('');(p/'verify_weather_site.py').write_text('print("verified")')
 elif 'rev-parse' in a:print('a'*40)
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}},'status':{'url':'https://collector.example.run.app'}}))
elif a[:3]==['scheduler','jobs','describe']:
 if a[3]=='weather-live-metar-clouds':print(json.dumps({'httpTarget':{'oidcToken':{'serviceAccountEmail':'scheduler@'+project+'.iam.gserviceaccount.com'}}}))
 elif '--format=value(state)' in a:print('ENABLED')
 else:print('NOT_FOUND',file=sys.stderr);sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('EXPMET_SEED_FAIL'):sys.exit(1)
'''
    for name in ['gcloud','git']:
        p=binary/name;p.write_text(script);p.chmod(0o755)
    env={**os.environ,'HOME':str(home),'PATH':str(binary)+os.pathsep+os.environ['PATH'],'EXPMET_LOG':str(log)}
    if seed_failure:env['EXPMET_SEED_FAIL']='1'
    result=subprocess.run(['bash',str(ROOT/'setup-weather-lab-expmet.sh'),PROJECT],env=env,text=True,capture_output=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    web=[c for c in calls if c[:5]==['gcloud','run','services','update','weather-lab']]
    schedule=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3] in ['create','update']]
    if seed_failure:
        assert result.returncode!=0
        assert not web and not schedule,'A failed initial analysis must not publish an empty experimental page'
    else:
        assert result.returncode==0,result.stderr
        assert len(web)==1 and not any(arg.startswith(('--min','--max','--set-env','--cpu')) for arg in web[0])
        assert len(schedule)==1 and 'weather-live-expmet' in schedule[0]
        assert '--schedule=5 * * * *' in schedule[0] and '--max-retry-attempts=0' in schedule[0]
    assert not any('delete' in c or 'billing' in c for c in calls)
