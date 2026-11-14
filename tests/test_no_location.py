import json
import os
from pathlib import Path
import re
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261028-205713-506d'


def test_all_website_responses_disable_device_location():
    import app
    client=app.app.test_client()
    for path in ['/', '/static/app.js','/static/vendor/leaflet.js','/healthz','/not-a-page']:
        response=client.get(path)
        assert response.headers.get('Permissions-Policy')=='geolocation=()'
    html=client.get('/').get_data(as_text=True)
    assert re.findall(r'<button role="tab" id="tab-([^"]+)"',html)==['metar','radar','satellite','forecast','air-quality']
    assert 'id="radar-location"' not in html and 'radar-location.js' not in html
    assert client.get('/static/radar-location.js').status_code==404
    assert client.get('/api/test/location?q=Shakopee').status_code==404
    for path in (ROOT/'static').glob('*.js'):
        assert not re.search(r'navigator\s*\.\s*geolocation|watchPosition\s*\(|getCurrentPosition\s*\(|\.locate\s*\(',path.read_text()),path.name
    assert not (ROOT/'update-weather-radar-location.sh').exists()


@pytest.mark.parametrize('script',['remove-weather-location.sh','fix-weather-airq-refresh.sh'])
@pytest.mark.parametrize('fail_build',[False,True])
def test_only_the_website_is_updated_and_location_policy_is_verified(tmp_path,fail_build,script):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import os,sys,json,pathlib,shutil
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];project='weather-lab-261028-205713-506d';root=pathlib.Path(os.environ['NO_LOCATION_ROOT'])
with open(os.environ['NO_LOCATION_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);(p/'static').mkdir(parents=True);shutil.copyfile(root/'static/app.js',p/'static/app.js');shutil.copyfile(root/'static/air-quality-views.js',p/'static/air-quality-views.js')
 elif 'rev-parse' in a:print('a'*40)
elif name=='curl':
 target=pathlib.Path(a[a.index('-o')+1]);target.write_bytes((root/('static/index.html' if target.name=='page.html' else 'static/'+target.name)).read_bytes())
 if target.name=='page.html':
  target.write_text('\\n'.join(line for line in target.read_text().splitlines() if 'id="tab-observations"' not in line).replace('airq-source-fallback-v1','airq-freshness-v2'))
 if '--dump-header' in a:pathlib.Path(a[a.index('--dump-header')+1]).write_text('HTTP/2 200\\nPermissions-Policy: geolocation=()\\n')
elif a[:3]==['run','services','describe']:
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/existing/app:latest'}]}}}}))
elif a[:2]==['builds','submit'] and os.environ['NO_LOCATION_FAIL']=='1':sys.exit(1)
'''
    for name in ['git','gcloud','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'HOME':str(home),'NO_LOCATION_ROOT':str(ROOT),'NO_LOCATION_LOG':str(log),'NO_LOCATION_FAIL':str(int(fail_build))}
    result=subprocess.run(['bash',str(ROOT/script),PROJECT],env=env,text=True,capture_output=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert (result.returncode==0)==(not fail_build),result.stderr
    assert not any('weather-collector' in c or (c[:3]==['gcloud','scheduler','jobs'] and c[3]!='describe') or c[:3]==['gcloud','run','jobs'] for c in calls)
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    assert len(updates)==(0 if fail_build else 1)
    if updates:
        assert updates[0][4]=='weather-lab'
        assert not any(a.startswith(('--min','--memory','--set-env','--service-account')) for a in updates[0])
