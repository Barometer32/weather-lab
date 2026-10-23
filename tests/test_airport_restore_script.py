"""Exercise the complete airport-only restore without contacting Google Cloud."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='j-weather-261020012817'


def run_restore(tmp_path, **options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir()
    stub='''#!/usr/bin/env python3
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='j-weather-261020012817'
with open(os.environ['AIRPORT_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  dst=pathlib.Path(a[-1]);dst.mkdir(parents=True)
  for file in ['deploy.sh','data-lifecycle.json']:shutil.copyfile(pathlib.Path(os.environ['AIRPORT_ROOT'])/file,dst/file)
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':
 path=pathlib.Path(a[a.index('-o')+1])
 if path.name=='page.html':path.write_text((pathlib.Path(os.environ['AIRPORT_ROOT'])/'static/index.html').read_text())
 else:
  frame={'hour':'2026-10-23T12:00:00Z','stations':[{'station':'KDEH','time':'2026-10-23T11:53:00Z','reportType':'METAR'}]}
  path.write_text(json.dumps({'sourcePolicy':'airport-routine-only','stationPolicy':'all-airports-v1','history':[frame]*(1 if os.environ.get('AIRPORT_BAD_HISTORY') else 12)}))
elif a[:2]==['projects','describe']:print('ACTIVE')
elif a[:3]==['billing','projects','describe']:print('False' if os.environ.get('AIRPORT_BILLING_OFF') else 'True')
elif a[:3]==['run','services','list']:print('[]')
elif a[:3]==['run','services','describe']:
 if a[3]=='weather-models':sys.exit(1)
 print('https://weather.example.run.app')
elif a[:3]==['scheduler','jobs','list']:
 if os.environ.get('AIRPORT_DENIED'):print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 print(json.dumps([{'name':'projects/'+project+'/locations/us-central1/jobs/'+j} for j in ['weather-live-current','weather-live-madis','weather-live-observations','unrelated-job','weather-live-metar-clouds']]))
elif a[:3]==['scheduler','jobs','describe']:
 if a[3] in ['weather-hourly','weather-live-radar-KEVX','weather-live-observations','weather-live-models']:sys.exit(1)
 print('ENABLED')
elif a[:3]==['storage','buckets','describe'] and a[3].endswith('-forecast'):sys.exit(1)
elif a[:3]==['storage','objects','describe']:sys.exit(1)
elif a[:3]==['run','jobs','describe']:sys.exit(1)
elif a[:2]==['builds','submit'] and os.environ.get('AIRPORT_FAIL_BUILD'):sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('AIRPORT_FAIL_SEED'):sys.exit(1)
'''
    for name in ['gcloud','git','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    log=tmp_path/'calls.jsonl'
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'AIRPORT_ROOT':str(ROOT),'AIRPORT_LOG':str(log),**{'AIRPORT_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'restore-j-weather-airport-metars.sh')],env=env,capture_output=True,text=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_hourly_airport_cron_only_seed_before_publish_and_retired_rapid_jobs_removed(tmp_path):
    result,calls=run_restore(tmp_path)
    assert result.returncode==0,result.stderr
    seed=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','jobs','execute','weather-airports-restore'])
    web=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','deploy','weather-lab','--project='+PROJECT])
    verify=next(i for i,c in enumerate(calls) if c[0]=='curl' and c[-1].endswith('metars.json'))
    retired=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','scheduler','jobs','delete','weather-live-current'])
    assert seed<web<verify<retired
    scheduled=[c for c in calls if c[:5] in (['gcloud','scheduler','jobs','update','http'],['gcloud','scheduler','jobs','create','http'])]
    assert {c[5] for c in scheduled}=={'weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds'}
    metar=next(c for c in scheduled if c[5]=='weather-live-metar-clouds')
    assert '--schedule=0 * * * *' in metar and '--max-retry-attempts=0' in metar
    assert '--http-method=POST' in metar and '--oidc-token-audience=https://weather.example.run.app' in metar
    removed=[c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','delete']]
    assert removed==['weather-live-current','weather-live-madis','weather-live-observations']
    bootstrap=next(c for c in calls if c[:5]==['gcloud','run','jobs','deploy','weather-airports-restore'])
    assert any('metar_history.main(); refresh_media.main()' in arg for arg in bootstrap)
    assert not any('regional_madis.main()' in arg or 'local_current.py' in arg for arg in bootstrap)
    assert 'twelve routine hourly frames' in result.stdout


def test_failed_import_never_publishes_new_web_or_deletes_rapid_jobs_and_resumes_paused_jobs(tmp_path):
    result,calls=run_restore(tmp_path,fail_seed=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','deploy','weather-lab'] for c in calls)
    assert not any(c[:5]==['gcloud','scheduler','jobs','delete','weather-live-current'] for c in calls)
    resumed={c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','resume']}
    assert resumed=={'weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds'}


def test_incomplete_history_keeps_rapid_jobs_until_verification_succeeds(tmp_path):
    result,calls=run_restore(tmp_path,bad_history=1)
    assert result.returncode!=0
    assert not any(c[:5]==['gcloud','scheduler','jobs','delete','weather-live-current'] for c in calls)


def test_billing_and_read_permissions_stop_before_building(tmp_path):
    result,calls=run_restore(tmp_path,denied=1)
    assert result.returncode!=0 and 'PERMISSION_DENIED' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)


def test_build_failure_does_not_deploy_services(tmp_path):
    result,calls=run_restore(tmp_path,fail_build=1)
    assert result.returncode!=0
    assert not any(c[:3]==['gcloud','run','deploy'] for c in calls)
