"""The dropdown update preserves existing airport/media collection schedules."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


def run_update(tmp_path,fail='',existing=False):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub=r'''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project=os.environ['MADIS_PROJECT']
with open(os.environ['MADIS_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);p.mkdir();(p/'verify_weather_site.py').write_text('print("five tabs and three observation views ready")')
 else:print('937ac58e73cb889cc492457cf6aa23077994a7ad')
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'weather-collector@'+project+'.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3]==['scheduler','jobs','list']:
 jobs=[{'name':'projects/'+project+'/locations/us-central1/jobs/weather-live-metar-clouds','state':'ENABLED'}]
 if os.environ['MADIS_EXISTING']=='yes':jobs.append({'name':'projects/'+project+'/locations/us-central1/jobs/weather-live-madis-map','state':'PAUSED'})
 print(json.dumps(jobs))
elif a[:2]==['builds','submit'] and os.environ['MADIS_FAIL']=='build':sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ['MADIS_FAIL']=='seed':sys.exit(1)
'''
    for name in ('git','gcloud'):
        p=binary/name;p.write_text(stub.replace('#!/usr/bin/env python3','#!'+sys.executable,1));p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'MADIS_LOG':str(log),'MADIS_PROJECT':PROJECT,'MADIS_FAIL':fail,'MADIS_EXISTING':'yes' if existing else 'no'}
    result=subprocess.run(['bash',str(ROOT/'update-weather-lab-madis-products.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_seeds_separate_history_before_web_publication_and_changes_only_new_schedule(tmp_path):
    result,calls=run_update(tmp_path);assert result.returncode==0,result.stderr
    collector=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-collector'])
    seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    web=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-lab'])
    assert collector<seed<web
    changes=[c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3]!='list']
    assert len(changes)==1 and changes[0][3:6]==['create','http','weather-live-madis-map']
    assert '--schedule=0,15,30,45 * * * *' in changes[0] and '--max-retry-attempts=0' in changes[0]
    assert any('--args=-u,madis_map.py' in c and '--task-timeout=900s' in c for c in calls)
    assert not any('delete' in c or 'billing' in c or 'add-iam-policy-binding' in c for c in calls)
    assert not any(v.startswith(('--min=', '--min-instances=', '--update-env-vars=')) for c in calls for v in c)


def test_existing_paused_madis_job_is_updated_and_resumed(tmp_path):
    result,calls=run_update(tmp_path,existing=True);assert result.returncode==0,result.stderr
    assert any(c[:6]==['gcloud','scheduler','jobs','update','http','weather-live-madis-map'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-madis-map'] for c in calls)


def test_failed_build_does_not_touch_services(tmp_path):
    result,calls=run_update(tmp_path,fail='build');assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)


def test_failed_backfill_does_not_publish_new_dropdown_or_change_schedules(tmp_path):
    result,calls=run_update(tmp_path,fail='seed');assert result.returncode!=0
    assert not any(c[:5]==['gcloud','run','services','update','weather-lab'] or c[:4]==['gcloud','scheduler','jobs','create'] for c in calls)
