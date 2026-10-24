"""Exercise the deployment helper without mutating cloud resources."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261024-133205'


def run_update(tmp_path,**options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['OBS_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
root=pathlib.Path(os.environ['OBS_ROOT']);project='weather-lab-261024-133205'
if name=='git':
 if a[0]=='clone':pathlib.Path(a[-1]).mkdir()
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':
 target=pathlib.Path(a[a.index('-o')+1])
 if 'initial-collection' in str(target):target.write_text(json.dumps({'status':'prepared'}))
 elif 'stations.json' in str(target):target.write_text(json.dumps({'version':'hennepin-west-station-list-v1','stations':[{'station':'HPN20','displayName':'Hopkins','network':'Hennepin West','time':'2026-10-24T18:03:00Z'}],'average':None}))
 else:target.write_text((root/'static/index.html').read_text())
elif a[:3]==['run','services','describe']:
 if '--format=json' in a:print(json.dumps({'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/recovery-images/app@sha256:abc'}]}}}}))
 else:print('https://weather.example.run.app')
elif a[:3]==['scheduler','jobs','list']:
 ids=['weather-live-metar-clouds','weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-air-quality']
 if os.environ.get('OBS_EXISTING'):ids.append('weather-live-observation-stations')
 print(json.dumps([{'name':'projects/'+project+'/locations/us-central1/jobs/'+id} for id in ids]))
elif a[:3]==['scheduler','jobs','describe']:print('PAUSED' if os.environ.get('OBS_EXISTING') else 'ENABLED')
elif a[:2]==['auth','print-identity-token']:print('test-token')
elif a[:2]==['builds','submit'] and os.environ.get('OBS_BUILD_FAIL'):sys.exit(1)
'''
    for name in ('gcloud','git','curl'):
        path=binary/name;path.write_text(stub);path.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'OBS_LOG':str(log),'OBS_ROOT':str(ROOT),**{'OBS_'+key.upper():str(value) for key,value in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'update-weather-observations.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_builds_in_existing_registry_and_keeps_clouds_and_other_collection_jobs(tmp_path):
    result,calls=run_update(tmp_path)
    assert result.returncode==0,result.stderr
    build=next(c for c in calls if c[:3]==['gcloud','builds','submit'])
    assert '--tag=us-central1-docker.pkg.dev/'+PROJECT+'/recovery-images/app:observations-abc123456789' in build
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    assert [c[4] for c in updates]==['weather-collector','weather-lab']
    mutations=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3] in ('create','update','delete','resume','pause')]
    assert len(mutations)==1 and mutations[0][3:6]==['create','http','weather-live-observation-stations']
    assert '--schedule=*/2 * * * *' in mutations[0]
    assert not any('delete' in c or 'billing' in c or 'enable' in c for c in calls)
    assert not any('--set-env-vars' in arg or arg.startswith('--set-env-vars=') for c in updates for arg in c)


def test_rerun_updates_and_resumes_only_new_inventory_job(tmp_path):
    result,calls=run_update(tmp_path,existing=1)
    assert result.returncode==0,result.stderr
    assert any(c[:6]==['gcloud','scheduler','jobs','update','http','weather-live-observation-stations'] for c in calls)
    resumes=[c for c in calls if c[:4]==['gcloud','scheduler','jobs','resume']]
    assert len(resumes)==1 and resumes[0][4]=='weather-live-observation-stations'


def test_build_failure_does_not_change_services_or_jobs(tmp_path):
    result,calls=run_update(tmp_path,build_fail=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)
    assert not any(c[:3]==['gcloud','scheduler','jobs'] and c[3] in ('create','update','delete','resume','pause') for c in calls)
