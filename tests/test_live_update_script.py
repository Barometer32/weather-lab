"""Execute the deployment helper with isolated CLI doubles; never contact GCP."""
import json
import os
from pathlib import Path
import subprocess

SCRIPT=Path(__file__).resolve().parents[1]/'update-j-weather-live.sh'
PROJECT='j-weather-261020012817'


def run_helper(tmp_path, **options):
    binary=tmp_path/'bin';binary.mkdir()
    home=tmp_path/'home';home.mkdir()
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;args=sys.argv[1:]
with open(os.environ['LIVE_TEST_LOG'],'a') as stream:stream.write(json.dumps([name,*args])+'\\n')
existing=os.environ.get('LIVE_TEST_EXISTING')=='1'
if name=='git':
 if args[0]=='clone':pathlib.Path(args[-1]).mkdir(parents=True)
 else:print('1234567890abcdef1234567890abcdef12345678')
elif name=='curl':
 target=pathlib.Path(args[args.index('-o')+1])
 if target.name=='page.html':target.write_text(''.join('<button role="tab" id="tab-'+t+'">' for t in ['current','radar','metar-clouds','satellite','forecast','air-quality'])+'<section id="current"><p id="sun-angle"></p></section><section id="satellite"></section>')
 else:target.write_text(json.dumps({'version':'latest-three-airports-celsius-v1','current':None}))
elif name=='gcloud':
 if args[:3]==['run','services','list']:
  if os.environ.get('LIVE_TEST_DENIED')=='1':print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
  print('weather-lab\\nweather-collector\\nunrelated-service')
  if existing:print('weather-models')
 elif args[:3]==['scheduler','jobs','list']:
  if '--format=json' in args:print('[]')
  else:
   print('projects/j-weather-261020012817/locations/us-central1/jobs/weather-live-radar')
   print('projects/j-weather-261020012817/locations/us-central1/jobs/unrelated-job')
   if existing:
    for job in ['weather-live-models','weather-live-current','weather-live-observations']:print('projects/j-weather-261020012817/locations/us-central1/jobs/'+job)
 elif args[:3]==['run','services','describe']:
  print('https://weather.example.run.app' if '--format=value(status.url)' in args else 'metadata: {}')
 elif args[:3]==['scheduler','jobs','describe']:print('PAUSED' if 'weather-live-current' in args and existing else 'ENABLED')
 elif args[:4]==['artifacts','docker','images','describe']:sys.exit(0 if os.environ.get('LIVE_TEST_IMAGE') else 1)
 elif args[:2]==['builds','submit'] and os.environ.get('LIVE_TEST_FAIL_BUILD')=='1':sys.exit(1)
 elif args[:2]==['storage','ls']:
  print('gs://j-weather-261020012817-weather-data/live/forecast.json')
  print('gs://j-weather-261020012817-weather-data/live/models-other.json')
  if existing:print('gs://j-weather-261020012817-weather-data/live/models.json\\ngs://j-weather-261020012817-weather-data/live/models-status.json')
'''
    for tool in ['gcloud','git','curl']:
        path=binary/tool;path.write_text(stub);path.chmod(0o755)
    logfile=tmp_path/'calls.jsonl'
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'LIVE_TEST_LOG':str(logfile),
         **{'LIVE_TEST_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(SCRIPT)],env=env,capture_output=True,text=True)
    return result,[json.loads(line) for line in logfile.read_text().splitlines()]


def test_new_rapid_job_private_oidc_and_existing_services_image_only(tmp_path):
    result,calls=run_helper(tmp_path)
    assert result.returncode==0,result.stderr
    gcloud=[c[1:] for c in calls if c[0]=='gcloud']
    assert all('--project='+PROJECT in c for c in gcloud if c[0]!='storage')
    updates=[c for c in gcloud if c[:3]==['run','services','update']]
    assert [c[3] for c in updates]==['weather-collector','weather-lab']
    assert all(not any(x.startswith('--args=') or x.startswith('--command=') or x.startswith('--update-env-vars=') for x in c) for c in updates)
    jobs=[c for c in gcloud if c[:3]==['scheduler','jobs','create']]
    assert len(jobs)==1 and jobs[0][3:5]==['http','weather-live-current']
    for option in ['--schedule=*/2 * * * *','--max-retry-attempts=0','--http-method=POST',
                   '--oidc-token-audience=https://weather.example.run.app',
                   '--oidc-service-account-email=weather-scheduler@'+PROJECT+'.iam.gserviceaccount.com']:
        assert option in jobs[0]
    assert not any('delete' in c or 'rm' in c for c in gcloud)
    assert 'Verified: live Current' in result.stdout


def test_existing_current_job_resumed_and_only_retired_models_removed(tmp_path):
    result,calls=run_helper(tmp_path,existing=1)
    assert result.returncode==0,result.stderr
    assert any(c[:5]==['gcloud','scheduler','jobs','update','http'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-current'] for c in calls)
    removed=[c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','delete']]
    assert removed==['weather-live-models','weather-live-observations']
    services=[c[4] for c in calls if c[:4]==['gcloud','run','services','delete']]
    assert services==['weather-models']
    objects=[c[3] for c in calls if c[:3]==['gcloud','storage','rm']]
    assert objects==['gs://'+PROJECT+'-weather-data/live/models.json','gs://'+PROJECT+'-weather-data/live/models-status.json']
    pause=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','scheduler','jobs','pause'])
    build=next(i for i,c in enumerate(calls) if c[:3]==['gcloud','builds','submit'])
    verify=next(i for i,c in enumerate(calls) if c[0]=='curl' and c[-1].endswith('current.json'))
    cleanup=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','scheduler','jobs','delete'])
    assert pause<build<verify<cleanup


def test_build_failure_never_deploys_or_deletes_services(tmp_path):
    result,calls=run_helper(tmp_path,existing=1,fail_build=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] or c[:4]==['gcloud','run','services','delete'] for c in calls)
    assert not any(c[:4]==['gcloud','scheduler','jobs','delete'] for c in calls)


def test_list_permission_denied_never_falls_through_to_build_or_delete(tmp_path):
    result,calls=run_helper(tmp_path,denied=1)
    assert result.returncode!=0 and 'PERMISSION_DENIED' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)


def test_rerun_reuses_versioned_image(tmp_path):
    result,calls=run_helper(tmp_path,image=1)
    assert result.returncode==0,result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)
