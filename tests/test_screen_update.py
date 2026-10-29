"""Only the current site's services and Air Q schedule may change."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-211000-abcd'


def run_update(tmp_path,fail=''):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    work=home/'weather-lab-fresh-weather-lab-261027-024631-5ff2';work.mkdir();(work/'project-id.txt').write_text(PROJECT)
    stub=r'''#!/usr/bin/env python3
import json,os,pathlib,sys,shutil
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-211000-abcd'
with open(os.environ['SCREEN_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
 if a[0]=='clone':
  dst=pathlib.Path(a[-1]);dst.mkdir();(dst/'verify_weather_site.py').write_text('print("all pages ready")')
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':shutil.copyfile(pathlib.Path(os.environ['SCREEN_ROOT'])/'static/index.html',a[a.index('-o')+1])
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:
  account='weather-collector@'+project+'.iam.gserviceaccount.com'
  print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':account,'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3]==['scheduler','jobs','describe']:print('{"state":"ENABLED"}')
elif a[:2]==['builds','submit'] and os.environ.get('SCREEN_FAIL')=='build':sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('SCREEN_FAIL')=='seed':sys.exit(1)
'''
    for name in ('gcloud','git','curl'):
        path=binary/name;path.write_text(stub.replace('#!/usr/bin/env python3','#!'+sys.executable,1));path.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'SCREEN_LOG':str(log),'SCREEN_ROOT':str(ROOT),'SCREEN_FAIL':fail}
    result=subprocess.run(['bash',str(ROOT/'update-weather-lab-screen.sh')],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_current_migration_project_is_used_and_data_is_prepared_before_web_publication(tmp_path):
    result,calls=run_update(tmp_path);assert result.returncode==0,result.stderr
    updates=[(i,c) for i,c in enumerate(calls) if c[:4]==['gcloud','run','services','update']]
    seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    assert updates[0][1][4]=='weather-collector' and updates[0][0]<seed<updates[1][0] and updates[1][1][4]=='weather-lab'
    assert all('--project='+PROJECT in c for _,c in updates)
    schedules=[c for c in calls if c[:4]==['gcloud','scheduler','jobs','update']]
    assert len(schedules)==1 and 'weather-live-air-quality' in schedules[0] and '--schedule=3-58/5 * * * *' in schedules[0]
    assert not any('delete' in c or 'billing' in c or 'add-iam-policy-binding' in c or c[:3]==['gcloud','projects','create'] for c in calls)
    assert 'screen update complete' in result.stdout


def test_failed_build_does_not_modify_services(tmp_path):
    result,calls=run_update(tmp_path,fail='build');assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)


def test_failed_data_preparation_does_not_publish_web_layout_or_change_schedules(tmp_path):
    result,calls=run_update(tmp_path,fail='seed');assert result.returncode!=0
    assert not any(c[:5]==['gcloud','run','services','update','weather-lab'] or c[:4]==['gcloud','scheduler','jobs','update'] for c in calls)
