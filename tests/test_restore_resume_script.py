"""Resume a successful build; never publish after a failed history job."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261024-133205'
IMAGE=f'us-central1-docker.pkg.dev/{PROJECT}/weather-lab/app:airports-b282a16b56c6'
WEB_IMAGE=f'us-central1-docker.pkg.dev/{PROJECT}/weather-lab/app:plots-newer'


def run_resume(tmp_path, **options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];p='weather-lab-261024-133205'
with open(os.environ['RESUME_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='curl':
 out=pathlib.Path(a[a.index('-o')+1])
 if out.name=='page.html':out.write_text((pathlib.Path(os.environ['RESUME_ROOT'])/'static/index.html').read_text())
 else:
  frame={'hour':'2026-10-24T17:00:00Z','stations':[{'station':'KMSP','time':'2026-10-24T16:53:00Z','reportType':'METAR'}]}
  out.write_text(json.dumps({'sourcePolicy':'airport-routine-only','stationPolicy':'all-airports-v1','history':[frame]*(1 if os.environ.get('RESUME_BAD_HISTORY') else 12)}))
elif a[:2]==['projects','describe']:print('ACTIVE')
elif a[:3]==['billing','projects','describe']:print('False' if os.environ.get('RESUME_BILLING_OFF') else 'True')
elif a[:3]==['run','services','describe']:
 if a[3]=='weather-collector':
  if os.environ.get('RESUME_DENIED'):print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
  print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+p+'.iam.gserviceaccount.com','containers':[{'image':'bad.example/app:tag' if os.environ.get('RESUME_BAD_IMAGE') else 'us-central1-docker.pkg.dev/'+p+'/weather-lab/app:airports-b282a16b56c6','env':[{'name':'WEATHER_DATA_BUCKET','value':'wrong-bucket' if os.environ.get('RESUME_BAD_BUCKET') else p+'-weather-data'}]}]}}}}))
 elif '--format=json' in a:print(json.dumps({'spec':{'template':{'spec':{'containers':[{'image':'bad.example/app:tag' if os.environ.get('RESUME_BAD_WEB_IMAGE') else 'us-central1-docker.pkg.dev/'+p+'/weather-lab/app:plots-newer'}]}}}}))
 elif '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print('metadata: {}')
elif a[:3]==['scheduler','jobs','list']:
 print(json.dumps([{'name':'projects/'+p+'/locations/us-central1/jobs/'+name,'state':state} for name,state in [('weather-live-radar','ENABLED'),('weather-live-metar-clouds','ENABLED'),('weather-live-satellite','PAUSED'),('unrelated','ENABLED')]]))
elif a[:3]==['run','jobs','execute'] and os.environ.get('RESUME_FAIL_SEED'):sys.exit(1)
elif a[:3]==['run','jobs','describe']:print('projects/'+p+'/locations/us-central1/executions/new-execution')
elif a[:2]==['logging','read']:print(json.dumps([{'protoPayload':{'status':{'code':9,'message':'diagnostic detail'}}}]))
'''
    for name in ['gcloud','curl']:
        path=binary/name;path.write_text(stub);path.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'RESUME_LOG':str(log),'RESUME_ROOT':str(ROOT),**{'RESUME_'+key.upper():str(value) for key,value in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'resume-weather-lab-restore.sh')],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_resume_reuses_collector_image_and_fresh_job_before_publishing(tmp_path):
    result,calls=run_resume(tmp_path);assert result.returncode==0,result.stderr
    deploy=next(c for c in calls if c[:4]==['gcloud','run','jobs','deploy'])
    assert deploy[4].startswith('weather-recover-') and deploy[4]!='weather-airports-restore'
    assert '--image='+IMAGE in deploy and '--service-account=weather-collector@'+PROJECT+'.iam.gserviceaccount.com' in deploy
    assert '--set-env-vars=WEATHER_DATA_BUCKET='+PROJECT+'-weather-data' in deploy
    assert '--max-retries=0' in deploy and '--task-timeout=1800s' in deploy
    assert any('Recovery container started' in arg and 'metar_history.main(); refresh_media.main(); air_quality.main()' in arg for arg in deploy)
    seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    web=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','services','update'])
    assert seed<web and calls[web][4]=='weather-lab' and '--image='+WEB_IMAGE in calls[web]
    assert any(c[:4]==['gcloud','run','services','update-traffic'] and '--to-latest' in c for c in calls)
    assert not any(c[:2]==['gcloud','builds'] or c[:3]==['gcloud','services','enable'] or c[:3]==['gcloud','projects','create'] or 'delete' in c or 'link' in c for c in calls)
    pauses=[c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','pause']]
    resumes=[c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','resume']]
    assert pauses==resumes==['weather-live-radar','weather-live-metar-clouds']
    assert 'twelve hourly airport frames' in result.stdout


def test_failed_job_prints_full_diagnostics_and_preserves_web(tmp_path):
    result,calls=run_resume(tmp_path,fail_seed=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)
    assert 'protoPayload' in result.stdout and 'diagnostic detail' in result.stdout
    assert any(c[:5]==['gcloud','run','jobs','executions','describe'] and '--format=json' in c for c in calls)
    assert [c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','resume']]==['weather-live-radar','weather-live-metar-clouds']


def test_bad_prerequisites_stop_before_pausing_or_deploying(tmp_path):
    for kind in ['billing_off','bad_image','bad_web_image','bad_bucket','denied']:
        directory=tmp_path/kind;directory.mkdir()
        result,calls=run_resume(directory,**{kind:1});assert result.returncode!=0
        assert not any(c[:4] in [['gcloud','run','jobs','deploy'],['gcloud','run','services','update'],['gcloud','scheduler','jobs','pause']] for c in calls)


def test_failed_verification_reports_failure_and_resumes_schedules(tmp_path):
    result,calls=run_resume(tmp_path,bad_history=1)
    assert result.returncode!=0 and 'not verified' in result.stderr
    assert 'Weather Lab resume complete.' not in result.stdout
    assert [c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','resume']]==['weather-live-radar','weather-live-metar-clouds']
