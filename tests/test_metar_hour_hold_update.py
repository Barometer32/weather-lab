"""The scoped updater preserves runtime settings and recurring schedules."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


@pytest.mark.parametrize('failure',['','build'])
def test_update_scope_and_build_failure(tmp_path,failure):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub=r'''import io,json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project=os.environ['HOLD_PROJECT']
with open(os.environ['HOLD_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
 if a[0]=='clone':shutil.copytree(os.environ['HOLD_ROOT'],a[-1],ignore=shutil.ignore_patterns('.git','__pycache__','.pytest_cache'))
 elif 'rev-parse' in a:print('a'*40)
elif name=='python3':
 code=sys.stdin.read();sys.argv=['-',*a[1:]]
 if len(a)>1 and a[1].startswith('https://'):
  import urllib.request
  source=pathlib.Path(a[2]);base=a[1]
  def urlopen(req,timeout=90):
   path=req.full_url.removeprefix(base).split('?')[0]
   if path=='/':return io.BytesIO((source/'static/index.html').read_bytes())
   if path.startswith('/static/'):return io.BytesIO((source/path.lstrip('/')).read_bytes())
   d={'pendingHour':None,'checkedAt':'2026-11-03T17:10:00Z','sourcePolicy':'airport-routine-only','history':[{'hour':f'2026-11-03T{h:02}:00:00Z','stations':[{}]} for h in range(14,18)]}
   return io.BytesIO(json.dumps(d).encode())
  urllib.request.urlopen=urlopen
 exec(compile(code,'updater-python','exec'))
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:restore-1afc'}]}}}}))
elif a[:3]==['scheduler','jobs','list']:print('[]')
elif a[:2]==['builds','submit'] and os.environ['HOLD_FAIL']=='build':sys.exit(1)
'''
    for name in ['gcloud','git','python3']:
        p=binary/name;p.write_text('#!'+sys.executable+'\n'+stub);p.chmod(0o755)
    env={**os.environ,'HOME':str(home),'PATH':str(binary)+os.pathsep+os.environ['PATH'],
         'HOLD_ROOT':str(ROOT),'HOLD_PROJECT':PROJECT,'HOLD_LOG':str(log),'HOLD_FAIL':failure,
         'WEATHER_SOURCE_COMMIT':'a'*40}
    result=subprocess.run(['bash',str(ROOT/'update-weather-metar-hour-hold.sh'),PROJECT],env=env,capture_output=True,text=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    if failure:
        assert result.returncode!=0
        assert not updates
        assert not any(c[:4]==['gcloud','scheduler','jobs','run'] for c in calls)
    else:
        assert result.returncode==0,result.stderr
        assert [c[4] for c in updates]==['weather-collector','weather-lab']
        assert not any(v.startswith(('--min','--max','--cpu','--memory','--concurrency','--set-env','--update-env','--command','--args')) for c in updates for v in c)
        scheduler=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3] not in ['list','describe']]
        assert len(scheduler)==1 and scheduler[0][3:5]==['run','weather-live-metar-clouds']
    assert not any('billing' in c or 'delete' in c or 'enable' in c or 'add-iam-policy-binding' in c for c in calls)
