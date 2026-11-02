import json
import os
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


@pytest.mark.parametrize('fail_build',[False,True])
def test_location_update_only_publishes_the_website(tmp_path,fail_build):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d';root=pathlib.Path(os.environ['RADAR_LOC_ROOT'])
with open(os.environ['RADAR_LOC_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);(p/'static').mkdir(parents=True);shutil.copyfile(root/'static/radar-location.js',p/'static/radar-location.js')
 elif 'rev-parse' in a:print('a'*40)
elif name=='curl':
 target=pathlib.Path(a[a.index('-o')+1]);target.write_bytes((root/('static/index.html' if target.name=='page.html' else 'static/radar-location.js')).read_bytes())
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/existing/app:latest'}]}}}}))
elif a[:2]==['builds','submit'] and os.environ.get('RADAR_LOC_FAIL')=='1':sys.exit(1)
'''
    for name in ['gcloud','git','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'HOME':str(home),'RADAR_LOC_ROOT':str(ROOT),'RADAR_LOC_LOG':str(log),'RADAR_LOC_FAIL':str(int(fail_build))}
    result=subprocess.run(['bash',str(ROOT/'update-weather-radar-location.sh'),PROJECT],env=env,text=True,capture_output=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert (result.returncode==0)==(not fail_build),result.stderr
    assert not any('weather-collector' in c or c[:3]==['gcloud','scheduler','jobs'] or c[:3]==['gcloud','run','jobs'] for c in calls)
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    assert len(updates)==(0 if fail_build else 1)
    if updates:
        assert updates[0][4]=='weather-lab'
        assert not any(a.startswith(('--min','--memory','--set-env','--service-account')) for a in updates[0])
