"""Restore orchestration checks using cloud-command stubs, never real resources."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261024-133205'


def run_restore(tmp_path,extra_env=None,**options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];p='weather-lab-261024-133205';root=pathlib.Path(os.environ['LATEST_ROOT'])
with open(os.environ['LATEST_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  dst=pathlib.Path(a[-1]);dst.mkdir(parents=True)
  for file in ['deploy.sh','ensure-weather-apis.sh','data-lifecycle.json']:shutil.copyfile(root/file,dst/file)
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':
 dst=pathlib.Path(a[a.index('-o')+1])
 if dst.name=='page.html':dst.write_text((root/'static/index.html').read_text())
 elif dst.name=='stations.json':dst.write_text(json.dumps({'version':'hennepin-west-station-list-v1','stations':[{'station':'HPN20','network':'Hennepin West'}],'average':None}))
 else:dst.write_text(json.dumps({'history':[{'stations':[{'station':'KMSP'}]}]*12}))
elif a[:2]==['projects','describe']:
 marker=pathlib.Path(os.environ['HOME'])/'undeleted'
 print('DELETE_REQUESTED' if os.environ.get('LATEST_DELETED') and not marker.exists() else 'ACTIVE')
elif a[:2]==['projects','undelete']:(pathlib.Path(os.environ['HOME'])/'undeleted').touch()
elif a[:3]==['billing','projects','describe']:print('False' if os.environ.get('LATEST_BILLING_OFF') else 'True')
elif a[:3]==['billing','accounts','list']:print(json.dumps([] if os.environ.get('LATEST_NO_ACCOUNT') else [{'name':'billingAccounts/test-account'}]))
elif a[:3]==['billing','accounts','describe']:print('True')
elif a[:2]==['services','list']:print('run.googleapis.com\\ncloudbuild.googleapis.com\\nartifactregistry.googleapis.com\\ncloudscheduler.googleapis.com\\nstorage.googleapis.com\\niam.googleapis.com')
elif a[:3]==['run','services','list']:print(json.dumps([{'metadata':{'name':'weather-lab'},'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+p+'/existing-images/app:latest'}]}}}}]))
elif a[:3]==['run','services','describe']:
 if a[3]=='weather-models':sys.exit(1)
 print('https://weather.example.run.app')
elif a[:3]==['scheduler','jobs','list']:print(json.dumps([{'name':'projects/'+p+'/locations/us-central1/jobs/weather-live-radar','state':'ENABLED'},{'name':'projects/'+p+'/locations/us-central1/jobs/unrelated','state':'ENABLED'}]))
elif a[:3]==['scheduler','jobs','describe']:
 if a[3] in ['weather-hourly','weather-live-radar-KEVX','weather-live-observations','weather-live-models']:sys.exit(1)
 print('ENABLED')
elif a[:3]==['artifacts','repositories','list']:print('projects/'+p+'/locations/us-central1/repositories/existing-images')
elif a[:3]==['storage','buckets','describe'] and a[3].endswith('-forecast'):sys.exit(1)
elif a[:3]==['storage','objects','describe']:sys.exit(1)
elif a[:3]==['run','jobs','describe']:sys.exit(1)
elif a[:2]==['builds','submit'] and os.environ.get('LATEST_BUILD_FAIL'):sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('LATEST_SEED_FAIL'):sys.exit(1)
elif a[:4]==['beta','run','domain-mappings','describe']:print(json.dumps({'spec':{'routeName':'weather-lab'}}))
'''
    for name in ('gcloud','git','curl'):
        file=binary/name;file.write_text(stub);file.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'LATEST_ROOT':str(ROOT),'LATEST_LOG':str(log),**{'LATEST_'+k.upper():str(v) for k,v in options.items()}}
    env.update(extra_env or {})
    result=subprocess.run(['bash',str(ROOT/'restore-weather-lab-latest.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_deleted_project_is_restored_in_place_and_latest_data_is_imported_before_website(tmp_path):
    result,calls=run_restore(tmp_path,deleted=1,billing_off=1)
    assert result.returncode==0,result.stderr
    assert any(c[:3]==['gcloud','projects','undelete'] and c[3]==PROJECT for c in calls)
    assert any(c[:4]==['gcloud','billing','projects','link'] for c in calls)
    assert not any(c[:3]==['gcloud','projects','create'] for c in calls)
    build=next(c for c in calls if c[:3]==['gcloud','builds','submit'])
    assert build[build.index('--tag')+1]=='us-central1-docker.pkg.dev/'+PROJECT+'/existing-images/app:restore-abc123456789'
    collector=next(c for c in calls if c[:4]==['gcloud','run','deploy','weather-collector'])
    assert '--memory=2Gi' in collector
    job=next(c for c in calls if c[:4]==['gcloud','run','jobs','deploy'])
    assert job[4].startswith('weather-latest-') and '--args=-u,restore_latest_data.py' in job
    execute=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    publish=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','deploy','weather-lab'])
    assert execute<publish
    assert not any(c[:4]==['gcloud','scheduler','jobs','run'] for c in calls),'scheduled work is deferred until history import finishes'
    resumed={c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','resume']}
    assert resumed=={'weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-metar-clouds','weather-live-air-quality'}
    assert not any('unrelated' in c for c in calls if c[:3]==['gcloud','scheduler','jobs'] and c[3] in ('pause','resume','delete'))


def test_closed_billing_stops_before_build_or_service_changes(tmp_path):
    result,calls=run_restore(tmp_path,billing_off=1,no_account=1)
    assert result.returncode!=0 and 'console.cloud.google.com/billing' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] or c[:3]==['gcloud','run','deploy'] for c in calls)


def test_failed_build_restores_previously_running_jobs_and_does_not_publish(tmp_path):
    result,calls=run_restore(tmp_path,build_fail=1)
    assert result.returncode!=0
    assert not any(c[:3]==['gcloud','run','deploy'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-radar'] for c in calls)


def test_failed_data_job_does_not_publish_website_and_resumes_collection(tmp_path):
    result,calls=run_restore(tmp_path,seed_fail=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','deploy','weather-lab'] for c in calls)
    resumed={c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','resume']}
    assert len(resumed)==5


def test_migration_pins_application_source_and_defers_address_changes(tmp_path):
    commit='abc123456789'+'0'*28
    result,calls=run_restore(tmp_path,extra_env={'WEATHER_RESTORE_SOURCE_COMMIT':commit,'WEATHER_SKIP_DOMAIN_SETUP':'true'})
    assert result.returncode==0,result.stderr
    assert any(c[0]=='git' and c[-5:]==['fetch','--quiet','--depth=1','origin',commit] for c in calls)
    assert any(c[0]=='git' and c[-4:]==['checkout','--quiet','--detach',commit] for c in calls)
    assert not any(c[:4]==['gcloud','beta','run','domain-mappings'] for c in calls)


def test_unverified_source_commit_stops_before_build(tmp_path):
    result,calls=run_restore(tmp_path,extra_env={'WEATHER_RESTORE_SOURCE_COMMIT':'a'*40})
    assert result.returncode!=0
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)
