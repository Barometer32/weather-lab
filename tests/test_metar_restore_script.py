"""Run the recovery script against CLI doubles, including failed history recovery."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='j-weather-261020012817'

def run_restore(tmp_path, **options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir()
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='j-weather-261020012817'
with open(os.environ['RESTORE_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':pathlib.Path(a[-1]).mkdir(parents=True)
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':
 path=pathlib.Path(a[a.index('-o')+1])
 if path.name=='page.html':path.write_text((pathlib.Path(os.environ['RESTORE_ROOT'])/'static/index.html').read_text())
 else:path.write_text(json.dumps({'history':[{'hour':str(i),'stations':[{'station':'KFCM'}]} for i in range(12)]}))
elif a[:2]==['projects','describe']:print('ACTIVE')
elif a[:3]==['billing','projects','describe']:print('False' if os.environ.get('RESTORE_BILLING_OFF') else 'True')
elif a[:3]==['run','services','describe']:
 if '--format=json' in a:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
 else:print('https://weather.example.run.app' if '--format=value(status.url)' in a else 'metadata: {}')
elif a[:3]==['scheduler','jobs','list']:
 if os.environ.get('RESTORE_DENIED'):print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 if '--format=json' in a:print(json.dumps([{'name':'projects/'+project+'/locations/us-central1/jobs/weather-live-metar-clouds'}]))
 else:
  for j in ['weather-live-current','weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds','unrelated-job','weather-live-models']:print(j+'\\tENABLED')
elif a[:3]==['scheduler','jobs','describe']:print('ENABLED')
elif a[:3]==['run','jobs','execute'] and os.environ.get('RESTORE_FAIL_HISTORY'):sys.exit(1)
elif a[:4]==['artifacts','docker','images','describe']:sys.exit(0)
'''
    for name in ['gcloud','curl','git']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    log=tmp_path/'calls.jsonl'
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'RESTORE_LOG':str(log),'RESTORE_ROOT':str(ROOT),**{'RESTORE_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'restore-j-weather-metars.sh')],env=env,capture_output=True,text=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]

def test_restores_original_map_history_and_only_weather_jobs(tmp_path):
    result,calls=run_restore(tmp_path)
    assert result.returncode==0,result.stderr
    updates=[c[4] for c in calls if c[:4]==['gcloud','run','services','update']]
    assert updates==['weather-collector','weather-lab']
    job=next(c for c in calls if c[:5]==['gcloud','scheduler','jobs','update','http'])
    assert '--schedule=0 * * * *' in job
    assert '--oidc-token-audience=https://weather.example.run.app' in job
    assert '--http-method=POST' in job
    assert any(c[:5]==['gcloud','run','jobs','deploy','weather-metar-history'] and '--args=metar_history.py' in c for c in calls)
    assert 'Verified full METAR page and all 12 hourly snapshots.' in result.stdout
    runs=[c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','run']]
    assert runs==['weather-live-current','weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds']
    assert not any('delete' in c for c in calls)

def test_failed_backfill_resumes_metar_schedule_without_claiming_success(tmp_path):
    result,calls=run_restore(tmp_path,fail_history=1)
    assert result.returncode!=0
    assert any(c[:5]==['gcloud','scheduler','jobs','pause','weather-live-metar-clouds'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-metar-clouds'] for c in calls)
    assert 'Verified full METAR' not in result.stdout

def test_billing_disabled_stops_before_deploying(tmp_path):
    result,calls=run_restore(tmp_path,billing_off=1)
    assert result.returncode!=0 and 'Enable billing' in result.stderr
    assert not any(c[:3]==['gcloud','run','services'] for c in calls)

def test_job_permission_error_never_treated_as_a_missing_job(tmp_path):
    result,calls=run_restore(tmp_path,denied=1)
    assert result.returncode!=0 and 'PERMISSION_DENIED' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] or c[:4]==['gcloud','run','services','update'] for c in calls)
