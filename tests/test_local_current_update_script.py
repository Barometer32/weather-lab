"""Exercise the local Current rollout with isolated CLIs, never a cloud account."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='j-weather-261020012817'


def run_helper(tmp_path, **options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir()
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='j-weather-261020012817'
with open(os.environ['LOCAL_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':pathlib.Path(a[-1]).mkdir(parents=True)
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':
 path=pathlib.Path(a[a.index('-o')+1])
 if path.name=='page.html':path.write_text(''.join('<button role="tab" id="tab-'+t+'">' for t in ['current','radar','satellite','forecast','air-quality']))
 else:path.write_text(json.dumps({'version':'madis-hopkins-ten-mile-v1','current':None if os.environ.get('LOCAL_BAD_API') else {'stationCount':3,'observedAt':'2026-10-23T01:00:00Z'},'candidate':{'stations':[]}}))
elif a[:2]==['projects','describe']:print('ACTIVE')
elif a[:3]==['billing','projects','describe']:print('False' if os.environ.get('LOCAL_BILLING_OFF') else 'True')
elif a[:3]==['run','services','describe']:
 if '--format=json' in a:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
 else:print('https://weather.example.run.app' if '--format=value(status.url)' in a else 'metadata: {}')
elif a[:3]==['scheduler','jobs','list']:
 if os.environ.get('LOCAL_DENIED'):print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 if '--format=json' in a:
  jobs=['weather-live-metar-clouds','weather-live-madis','weather-live-observations','weather-live-radar','weather-live-satellite','weather-live-forecast','unrelated-job']
  if not os.environ.get('LOCAL_NO_CURRENT'):jobs+=['weather-live-current']
  print(json.dumps([{'name':'projects/'+project+'/locations/us-central1/jobs/'+j} for j in jobs]))
elif a[:3]==['scheduler','jobs','describe']:print('PAUSED')
elif a[:3]==['run','jobs','execute'] and os.environ.get('LOCAL_FAIL_SEED'):sys.exit(1)
elif a[:4]==['artifacts','docker','images','describe']:sys.exit(1 if os.environ.get('LOCAL_FAIL_BUILD') else 0)
elif a[:2]==['builds','submit'] and os.environ.get('LOCAL_FAIL_BUILD'):sys.exit(1)
'''
    for name in ['gcloud','curl','git']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    log=tmp_path/'calls.jsonl'
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'LOCAL_LOG':str(log),'LOCAL_ROOT':str(ROOT),**{'LOCAL_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'update-j-weather-local-current.sh')],env=env,capture_output=True,text=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_seed_before_web_publish_verify_before_cleanup_and_preserve_other_tabs_jobs(tmp_path):
    result,calls=run_helper(tmp_path)
    assert result.returncode==0,result.stderr
    seed=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','jobs','execute','weather-current-start'])
    web=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-lab'])
    verify=next(i for i,c in enumerate(calls) if c[0]=='curl' and c[-1].endswith('current.json'))
    cleanup=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','scheduler','jobs','delete'])
    assert seed<web<verify<cleanup
    removed=[c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','delete']]
    assert removed==['weather-live-metar-clouds','weather-live-madis','weather-live-observations']
    assert not any(c[:4]==['gcloud','run','services','delete'] or c[:3]==['gcloud','storage','rm'] for c in calls)
    job=next(c for c in calls if c[:5]==['gcloud','scheduler','jobs','update','http'])
    for arg in ['--schedule=*/2 * * * *','--http-method=POST','--attempt-deadline=300s','--max-retry-attempts=0',
                '--uri=https://weather.example.run.app/collect/current','--oidc-token-audience=https://weather.example.run.app',
                '--oidc-service-account-email=weather-scheduler@'+PROJECT+'.iam.gserviceaccount.com']:
        assert arg in job
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-current'] for c in calls)
    assert 'Verified local Current with 3' in result.stdout
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)


def test_create_current_schedule_when_absent(tmp_path):
    result,calls=run_helper(tmp_path,no_current=1)
    assert result.returncode==0,result.stderr
    assert any(c[:6]==['gcloud','scheduler','jobs','create','http','weather-live-current'] for c in calls)


def test_seed_failure_keeps_existing_web_and_retired_schedules(tmp_path):
    result,calls=run_helper(tmp_path,fail_seed=1)
    assert result.returncode!=0
    assert not any(c[:5]==['gcloud','run','services','update','weather-lab'] for c in calls)
    assert not any(c[:4]==['gcloud','scheduler','jobs','delete'] for c in calls)
    assert 'update complete' not in result.stdout


def test_api_not_ready_keeps_retired_schedules(tmp_path):
    result,calls=run_helper(tmp_path,bad_api=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','scheduler','jobs','delete'] for c in calls)


def test_permission_denied_stops_before_build_deploy_or_delete(tmp_path):
    result,calls=run_helper(tmp_path,denied=1)
    assert result.returncode!=0 and 'PERMISSION_DENIED' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] or c[:4]==['gcloud','run','services','update'] or c[:4]==['gcloud','scheduler','jobs','delete'] for c in calls)


def test_build_failure_stops_before_deploy_or_delete(tmp_path):
    result,calls=run_helper(tmp_path,fail_build=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] or c[:4]==['gcloud','scheduler','jobs','delete'] for c in calls)
