"""Dry-run the Cloud Shell release without touching cloud resources."""
import json,os,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


def run_setup(tmp_path,fail=''):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub=r'''#!/usr/bin/env python3
import json,os,pathlib,sys,shutil
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d';root=pathlib.Path(os.environ['GRID_ROOT'])
with open(os.environ['GRID_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);(p/'static').mkdir(parents=True);shutil.copyfile(root/'static/location-choice.js',p/'static/location-choice.js');(p/'verify_weather_site.py').write_text('print("all six tabs ready")')
 else:print('a'*40)
elif name=='curl':
 target=pathlib.Path(a[a.index('-o')+1]);target.write_bytes((root/('static/index.html' if target.name=='page.html' else 'static/'+target.name)).read_bytes())
 if '--dump-header' in a:pathlib.Path(a[a.index('--dump-header')+1]).write_text('HTTP/2 200\nPermissions-Policy: geolocation=(self)\n')
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3]==['scheduler','jobs','list']:
 print(json.dumps([{'name':'projects/'+project+'/locations/us-central1/jobs/weather-live-metar-clouds','httpTarget':{'oidcToken':{'serviceAccountEmail':'weather-scheduler@'+project+'.iam.gserviceaccount.com'}}}]))
elif a[:3]==['scheduler','jobs','describe']:
 if '--format=json' in a:print('NOT_FOUND',file=sys.stderr);sys.exit(1)
 else:print('ENABLED')
elif a[:2]==['builds','submit'] and os.environ.get('GRID_FAIL')=='build':sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('GRID_FAIL')=='seed':sys.exit(1)
'''
    for name in ('git','gcloud','curl'):
        p=binary/name;p.write_text(stub.replace('#!/usr/bin/env python3','#!'+sys.executable,1));p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'GRID_ROOT':str(ROOT),'GRID_LOG':str(log),'GRID_FAIL':fail,'WEATHER_SOURCE_COMMIT':'a'*40}
    result=subprocess.run(['bash',str(ROOT/'setup-weather-current-grid.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_seed_precedes_publication_and_only_new_current_schedule_changes(tmp_path):
    result,calls=run_setup(tmp_path);assert result.returncode==0,result.stderr
    seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    web=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-lab'])
    assert seed<web
    changes=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3] in ('create','update','delete','pause','resume')]
    assert len(changes)==1 and 'weather-live-current-analysis' in changes[0]
    assert '--schedule=*/5 * * * *' in changes[0] and '--max-retry-attempts=0' in changes[0]
    assert not any('billing' in c or 'domain-mappings' in c for c in calls)
    grants=[c for c in calls if 'add-iam-policy-binding' in c]
    assert len(grants)==1 and 'weather-current-collector' in grants[0]
    assert not any(c[:5]==['gcloud','run','services','update','weather-collector'] for c in calls)
    webcall=calls[web]
    assert not any(x.startswith(('--min-instances','--max-instances','--cpu','--memory')) for x in webcall)


@pytest.mark.parametrize('fail',['build','seed'])
def test_failed_build_or_seed_does_not_publish_the_new_page(tmp_path,fail):
    result,calls=run_setup(tmp_path,fail);assert result.returncode!=0
    assert not any(c[:5]==['gcloud','run','services','update','weather-lab'] for c in calls)
    assert not any(c[:3]==['gcloud','scheduler','jobs'] and c[3] in ('create','update') for c in calls)


def test_generic_restore_scheduler_keeps_retry_count_separate_from_service_url(tmp_path):
    binary=tmp_path/'bin';binary.mkdir();log=tmp_path/'calls'
    p=binary/'gcloud';p.write_text('#!'+sys.executable+'\nimport os,sys,json\nwith open(os.environ["GRID_LOG"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n');p.chmod(0o755)
    source=(ROOT/'deploy.sh').read_text();function=source[source.index('weather_schedule() {'):source.index("weather_schedule radar '*")]
    script=function+'''\nweather_schedule metar-clouds '0,5,10 * * * *' metar-clouds 300 0
weather_schedule current-analysis '*/5 * * * *' current-analysis 180 0 https://current.example.run.app
'''
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'GRID_LOG':str(log),'WEATHER_COLLECTOR_URL':'https://old.example.run.app','WEATHER_REGION':'us-central1','WEATHER_SCHEDULER_SA':'fake@example.com','WEATHER_DEFER_COLLECTION':'true'}
    result=subprocess.run(['bash','-eu'],input=script,env=env,text=True,capture_output=True);assert result.returncode==0,result.stderr
    changes=[json.loads(line) for line in log.read_text().splitlines() if '"http"' in line]
    assert '--uri=https://old.example.run.app/collect/metar-clouds' in changes[0]
    assert '--uri=https://current.example.run.app/collect/current-analysis' in changes[1]
    assert '--max-retry-attempts=0' in changes[0] and '--max-retry-attempts=0' in changes[1]
