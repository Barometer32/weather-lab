"""Only EXPMET resources are retired; standard service settings survive."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


@pytest.mark.parametrize('mode',['present','absent','build-fail'])
def test_remove_experiment_and_keep_all_other_resources(tmp_path,mode):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d';mode=os.environ['FOUR_MODE']
with open(os.environ['FOUR_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);(p/'static').mkdir(parents=True);(p/'static/index.html').write_text('<script src="/static/metar-views.js?v=metar-four-frame-v1"></script>');(p/'static/metar-views.js').write_text('const historyHours=4;');(p/'verify_weather_site.py').write_text('print("verified")')
 elif 'rev-parse' in a:print('a'*40)
elif name=='curl':pathlib.Path(a[a.index('-o')+1]).write_text('<script src="/static/metar-views.js?v=metar-four-frame-v1"></script>')
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather-lab/app:latest','env':[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'}]}]}}}}))
elif a[:3] in [['scheduler','jobs','describe'],['run','jobs','describe'],['storage','objects','describe']]:
 if mode=='absent':print('NOT_FOUND',file=sys.stderr);sys.exit(1)
 print(json.dumps({'state':'ENABLED'}))
elif a[:2]==['builds','submit'] and mode=='build-fail':sys.exit(1)
'''
    for name in ['gcloud','git','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'HOME':str(home),'PATH':str(binary)+os.pathsep+os.environ['PATH'],'FOUR_LOG':str(log),'FOUR_MODE':mode}
    result=subprocess.run(['bash',str(ROOT/'restore-weather-lab-four-frames.sh'),PROJECT],env=env,text=True,capture_output=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    if mode=='build-fail':assert result.returncode!=0 and not updates
    else:
        assert result.returncode==0,result.stderr
        assert {c[4] for c in updates}=={'weather-lab','weather-collector'}
        assert not any(arg.startswith(('--min','--max','--set-env','--cpu','--memory')) for c in updates for arg in c)
    deletions=[c for c in calls if 'delete' in c or 'rm' in c]
    if mode=='absent':assert not deletions
    else:
        assert any('weather-live-expmet' in c and 'delete' in c for c in deletions)
        assert any('weather-expmet-seed' in c and 'delete' in c for c in deletions)
        assert all(any('expmet' in arg for arg in c) for c in deletions)
    assert not any(c[:3]==['gcloud','scheduler','jobs'] and c[3] in ['create','update','resume','run'] for c in calls)
    assert not any('billing' in c or 'enable' in c for c in calls)


def test_experimental_routes_and_files_are_removed_and_collection_is_unchanged():
    for p in ['expmet.py','static/expmet-views.js','setup-weather-lab-expmet.sh']:assert not (ROOT/p).exists()
    assert '/api/expmet' not in (ROOT/'app.py').read_text()
    assert 'collect_expmet' not in (ROOT/'collector.py').read_text()
    assert 'tab-expmet' not in (ROOT/'static/index.html').read_text()
    assert "weather_schedule metar-clouds '0,5,10 * * * *'" in (ROOT/'deploy.sh').read_text()
