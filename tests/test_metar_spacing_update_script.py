"""The spacing update changes only the website image."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='j-weather-261020012817'


def run_update(tmp_path, script='update-j-weather-metar-spacing.sh', **options):
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
    result=subprocess.run(['bash',str(ROOT/script)],env=env,capture_output=True,text=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]



def test_only_website_is_updated(tmp_path):
    result,calls=run_update(tmp_path)
    assert result.returncode==0,result.stderr
    assert [c[4] for c in calls if c[:4]==['gcloud','run','services','update']]==['weather-lab']
    assert not any('weather-collector' in c or c[:2]==['gcloud','scheduler'] or c[:3]==['gcloud','services','enable'] for c in calls)
    assert '--compressed' in next(c for c in calls if c[0]=='curl')
    assert 'Verified compact METAR spacing and fine zoom.' in result.stdout


def test_build_failure_keeps_running_website(tmp_path):
    result,calls=run_update(tmp_path,build_fail=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)


def test_denied_settings_read_stops_before_build(tmp_path):
    result,calls=run_update(tmp_path,denied=1)
    assert result.returncode!=0 and 'PERMISSION_DENIED' in result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)


def test_rerun_reuses_versioned_image(tmp_path):
    result,calls=run_update(tmp_path,reuse=1)
    assert result.returncode==0,result.stderr
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)


def test_clouds_tab_update_changes_only_the_web_image(tmp_path):
    result,calls=run_update(tmp_path,script='update-j-weather-clouds-tab.sh')
    assert result.returncode==0,result.stderr
    assert [c[4] for c in calls if c[:4]==['gcloud','run','services','update']]==['weather-lab']
    assert not any('weather-collector' in c or c[:2]==['gcloud','scheduler'] or c[:3]==['gcloud','services','enable'] for c in calls)
    assert 'separate METAR and Clouds station plots with 12-hour history' in result.stdout
