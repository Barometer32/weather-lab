"""Exercise the Cloud Shell helper without mutating any cloud resources."""
import json
import os
from pathlib import Path
import subprocess

SCRIPT=Path(__file__).resolve().parents[1]/'update-j-weather-models.sh'


def run_helper(tmp_path, **options):
    binary=tmp_path/'bin';binary.mkdir()
    home=tmp_path/'home';home.mkdir()
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;args=sys.argv[1:]
with open(os.environ['MODEL_TEST_LOG'],'a') as stream:stream.write(json.dumps([name,*args])+'\\n')
if name=='git':
 if args[0]=='clone':pathlib.Path(args[-1]).mkdir(parents=True)
 else:print('1234567890abcdef1234567890abcdef12345678')
elif name=='curl':
 target=pathlib.Path(args[args.index('-o')+1])
 if target.name=='page.html':target.write_text(''.join('<button role="tab" id="tab-'+tab+'">' for tab in ['current','radar','metar-clouds','satellite','models','forecast','air-quality']))
 else:target.write_text(json.dumps({'available':False,'status':{'state':'collecting'}}))
elif name=='gcloud':
 if args[:3]==['run','services','list']:
  if os.environ.get('MODEL_TEST_DENIED')=='1':print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
  if os.environ.get('MODEL_TEST_EXISTING')=='1':print('weather-models')
 elif args[:3]==['scheduler','jobs','list']:
  if os.environ.get('MODEL_TEST_EXISTING')=='1':print('projects/j-weather-261020012817/locations/us-central1/jobs/weather-live-models')
 elif args[:3]==['run','services','describe']:
  if '--format=value(status.url)' in args:print('https://weather.example.run.app')
  else:print('metadata: {}')
 elif args[:3]==['scheduler','jobs','describe']:
  print('ENABLED' if '--format=value(state)' in args else '{}')
 elif args[:4]==['artifacts','docker','images','describe']:sys.exit(1)
 elif args[:2]==['builds','submit'] and os.environ.get('MODEL_TEST_FAIL_BUILD')=='1':sys.exit(1)
'''
    for tool in ['gcloud','git','curl']:
        path=binary/tool;path.write_text(stub);path.chmod(0o755)
    logfile=tmp_path/'calls.jsonl'
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'MODEL_TEST_LOG':str(logfile),
         **{'MODEL_TEST_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(SCRIPT)],env=env,capture_output=True,text=True)
    return result,[json.loads(line) for line in logfile.read_text().splitlines()]


def test_first_install_private_worker_and_only_new_scheduler_job(tmp_path):
    result,calls=run_helper(tmp_path)
    assert result.returncode==0,result.stderr
    gcloud=[c[1:] for c in calls if c[0]=='gcloud']
    assert all('--project=j-weather-261020012817' in c for c in gcloud)
    deploy=next(c for c in gcloud if c[:3]==['run','deploy','weather-models'])
    assert '--no-allow-unauthenticated' in deploy and '--concurrency=1' in deploy and '--timeout=900' in deploy
    assert '--min-instances=0' in deploy and '--max-instances=1' in deploy
    jobs=[c for c in gcloud if c[:2]==['scheduler','jobs'] and c[2] in ['create','update','run']]
    assert all('weather-live-models' in c for c in jobs)
    assert '--schedule=35 * * * *' in jobs[0]
    assert '--max-retry-attempts=0' in jobs[0]
    assert any(c[:4]==['run','services','update','weather-lab'] for c in gcloud)
    assert not any('delete' in c for c in gcloud)
    assert not any(c[:4]==['run','services','update','weather-collector'] for c in gcloud)
    assert 'First model collection requested' in result.stdout


def test_rerun_updates_existing_model_job(tmp_path):
    result,calls=run_helper(tmp_path,existing=1)
    assert result.returncode==0,result.stderr
    assert any(c[:5]==['gcloud','scheduler','jobs','update','http'] for c in calls)
    assert not any(c[:5]==['gcloud','scheduler','jobs','create','http'] for c in calls)


def test_build_failure_stops_before_deployment(tmp_path):
    result,calls=run_helper(tmp_path,fail_build=1)
    assert result.returncode!=0
    assert not any(c[:3]==['gcloud','run','deploy'] for c in calls)
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)


def test_permissions_error_does_not_fall_through_to_create(tmp_path):
    result,calls=run_helper(tmp_path,denied=1)
    assert result.returncode!=0 and 'PERMISSION_DENIED' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)
