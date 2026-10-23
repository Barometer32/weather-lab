"""The retry update preserves other schedules and avoids a full restore."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='j-weather-261020012817'


def run_update(tmp_path, **options):
    binpath=tmp_path/'bin';binpath.mkdir();home=tmp_path/'home';home.mkdir()
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['RETRY_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':pathlib.Path(a[-1]).mkdir(parents=True)
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':pathlib.Path(a[a.index('-o')+1]).write_text((pathlib.Path(os.environ['RETRY_ROOT'])/'static/index.html').read_text())
elif a[:3]==['run','services','describe']:
 if os.environ.get('RETRY_DENIED'):print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 print('https://weather.example.run.app' if '--format=value(status.url)' in a else 'metadata: {}')
elif a[:3]==['scheduler','jobs','describe']:print('PAUSED' if '--format=value(state)' in a else '{}')
elif a[:4]==['artifacts','docker','images','describe']:sys.exit(0 if os.environ.get('RETRY_REUSE') else 1)
elif a[:2]==['builds','submit'] and os.environ.get('RETRY_BUILD_FAIL'):sys.exit(1)
'''
    for name in ['gcloud','git','curl']:
        p=binpath/name;p.write_text(stub);p.chmod(0o755)
    log=tmp_path/'calls'
    env={**os.environ,'PATH':str(binpath)+os.pathsep+os.environ['PATH'],'HOME':str(home),'RETRY_LOG':str(log),'RETRY_ROOT':str(ROOT),**{'RETRY_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'update-j-weather-metar-retries.sh')],env=env,capture_output=True,text=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_only_app_images_and_existing_metar_job_are_updated(tmp_path):
    result,calls=run_update(tmp_path)
    assert result.returncode==0,result.stderr
    assert [c[4] for c in calls if c[:4]==['gcloud','run','services','update']]==['weather-collector','weather-lab']
    updates=[c for c in calls if c[:5]==['gcloud','scheduler','jobs','update','http']]
    assert len(updates)==1 and updates[0][5]=='weather-live-metar-clouds'
    for flag in ['--schedule=*/2 * * * *','--attempt-deadline=300s','--max-retry-attempts=0','--http-method=POST',
                 '--oidc-token-audience=https://weather.example.run.app','--uri=https://weather.example.run.app/collect/metar-clouds']:
        assert flag in updates[0]
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-metar-clouds'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','run','weather-live-metar-clouds'] for c in calls)
    assert not any(c[:3]==['gcloud','services','enable'] or 'delete' in c or c[:3]==['gcloud','run','jobs'] for c in calls)
    assert 'Verified retry-aware' in result.stdout


def test_build_failure_does_not_change_services_or_schedule(tmp_path):
    result,calls=run_update(tmp_path,build_fail=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] or c[:4]==['gcloud','scheduler','jobs','update'] for c in calls)


def test_denied_settings_read_stops_before_build(tmp_path):
    result,calls=run_update(tmp_path,denied=1)
    assert result.returncode!=0 and 'PERMISSION_DENIED' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)


def test_rerun_reuses_existing_versioned_image(tmp_path):
    result,calls=run_update(tmp_path,reuse=1)
    assert result.returncode==0,result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)
