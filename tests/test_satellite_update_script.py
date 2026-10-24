"""Verify satellite preparation, publication order and schedule recovery offline."""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261024-133205'


def run_update(tmp_path,**options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['SAT_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
project='weather-lab-261024-133205'
if name=='git':
 if a[0]=='clone':pathlib.Path(a[-1]).mkdir()
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':
 path=pathlib.Path(a[a.index('-o')+1])
 if path.name=='page.html':path.write_text((pathlib.Path(os.environ['SAT_ROOT'])/'static/index.html').read_text())
 else:path.write_text(json.dumps({'frameLimit':24,'historyPolicy':'latest-24-images','frames':[{'time':f'2026-10-24T12:{i:02}:00Z'} for i in range(24)]}))
elif a[:3]==['run','services','describe']:
 if os.environ.get('SAT_DENIED'):sys.exit(1)
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'existing-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/existing-images/app@sha256:123','env':[{'name':'WEATHER_DATA_BUCKET','value':'existing-data-bucket'}]}]}}}}))
elif a[:3]==['scheduler','jobs','describe']:print('PAUSED' if os.environ.get('SAT_PAUSED') else 'ENABLED')
elif a[:2]==['builds','submit'] and os.environ.get('SAT_BUILD_FAIL'):sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('SAT_SEED_FAIL'):sys.exit(1)
'''
    for name in ['gcloud','git','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'SAT_LOG':str(log),'SAT_ROOT':str(ROOT),**{'SAT_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'update-weather-lab-satellite.sh')],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_build_collector_seed_web_order_and_existing_identity_bucket_and_schedule(tmp_path):
    result,calls=run_update(tmp_path);assert result.returncode==0,result.stderr
    build=next(i for i,c in enumerate(calls) if c[:3]==['gcloud','builds','submit'])
    collector=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-collector'])
    seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    web=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-lab'])
    assert build<collector<seed<web
    assert any('/existing-images/app:satellite-24-' in v for v in calls[build])
    prepare=next(c for c in calls if c[:4]==['gcloud','run','jobs','deploy'])
    assert '--service-account=existing-collector@'+PROJECT+'.iam.gserviceaccount.com' in prepare
    assert '--set-env-vars=WEATHER_DATA_BUCKET=existing-data-bucket' in prepare
    assert '--args=refresh_satellite.py' in prepare
    scheduler=[c for c in calls if c[:3]==['gcloud','scheduler','jobs']]
    assert all(c[4]=='weather-live-satellite' for c in scheduler)
    assert [c[3] for c in scheduler if c[3] in ['pause','resume']]==['pause','resume']
    assert not any('delete' in c or c[:4] in [['gcloud','scheduler','jobs','update'],['gcloud','scheduler','jobs','create']] or c[:3]==['gcloud','services','enable'] for c in calls)
    assert 'truecolor: 24/24 available images' in result.stdout


def test_failed_seed_preserves_website_and_resumes_satellite_collection(tmp_path):
    result,calls=run_update(tmp_path,seed_fail=1);assert result.returncode!=0
    assert not any(c[:5]==['gcloud','run','services','update','weather-lab'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-satellite'] for c in calls)


def test_failed_build_or_settings_read_does_not_change_running_services_or_schedule(tmp_path):
    for kind in ['denied','build_fail']:
        d=tmp_path/kind;d.mkdir();result,calls=run_update(d,**{kind:1});assert result.returncode!=0
        assert not any(c[:4]==['gcloud','run','services','update'] or c[:4]==['gcloud','scheduler','jobs','pause'] for c in calls)


def test_previously_paused_satellite_job_stays_paused(tmp_path):
    result,calls=run_update(tmp_path,paused=1);assert result.returncode==0,result.stderr
    assert not any(c[:4] in [['gcloud','scheduler','jobs','pause'],['gcloud','scheduler','jobs','resume']] for c in calls)
