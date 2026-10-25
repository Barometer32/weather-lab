import json,os,subprocess,threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROJECT='weather-lab-261024-133205'


@contextmanager
def fake_site(bad_history=False):
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data,code=200):
            body=data if isinstance(data,bytes) else json.dumps(data).encode()
            self.send_response(code);self.end_headers();self.wfile.write(body)
        def do_POST(self):requests.append(('POST',self.path));self.reply({'status':'prepared'})
        def do_GET(self):
            requests.append(('GET',self.path))
            if self.path=='/':return self.reply((ROOT/'static/index.html').read_bytes())
            if self.path=='/api/station-plots':
                row={'station':'KMSP','reportType':'METAR','time':'2026-10-24T17:53:00Z'}
                return self.reply({'sourcePolicy':'airport-routine-only','stationPolicy':'all-airports-v1','history':[{'stations':[row]}]*(1 if bad_history else 12)})
            if self.path=='/api/forecast':return self.reply({'periods':[{'name':'Tonight'}]})
            if self.path.startswith('/api/prepared/'):return self.reply(b'prepared image')
            return self.reply({'frames':[{'url':'/api/prepared/newest.bin'}]})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',requests
    finally:server.shutdown();server.server_close();thread.join()


def run_update(tmp_path,url,**options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['PRODUCT_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':pathlib.Path(a[-1]).mkdir()
 else:print('abc1234567890000000000000000000000000000')
elif a[:3]==['run','services','describe']:
 if '--format=json' in a:print(json.dumps({'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/weather-lab-261024-133205/existing-images/app@sha256:abc'}]}}}}))
 else:print(os.environ['PRODUCT_URL'])
elif a[:3]==['scheduler','jobs','list']:print(json.dumps([{'name':'projects/x/jobs/'+name,'state':'ENABLED'} for name in ['weather-live-observation-stations','weather-live-metar-clouds','weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-air-quality','unrelated']]))
elif a[:2]==['auth','print-identity-token']:print('test-token')
elif a[:2]==['builds','submit'] and os.environ.get('PRODUCT_BUILD_FAIL'):sys.exit(1)
'''
    for name in ('gcloud','git'):
        file=binary/name;file.write_text(stub);file.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'PRODUCT_LOG':str(log),'PRODUCT_URL':url,**{'PRODUCT_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'update-weather-lab-metars.sh'),PROJECT],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_update_stops_only_mesonet_and_verifies_every_prepared_page_without_adding_warm_instances(tmp_path):
    with fake_site() as (url,requests):result,calls=run_update(tmp_path,url)
    assert result.returncode==0,result.stderr
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    assert [c[4] for c in updates]==['weather-collector','weather-lab']
    assert '--update-env-vars=WEATHER_PREPARED_ONLY=true' in updates[1]
    removed=[c[4] for c in calls if c[:4]==['gcloud','scheduler','jobs','delete']]
    assert removed==['weather-live-observation-stations']
    assert not any(c[:4] in (['gcloud','scheduler','jobs','update'],['gcloud','scheduler','jobs','create']) for c in calls)
    assert not any(arg.startswith('--min') for c in updates for arg in c)
    assert {path for method,path in requests if method=='POST'}=={'/collect/metar-clouds','/collect/radar-KMPX','/collect/satellite','/collect/forecast','/collect/air-quality'}
    pages={path for method,path in requests if method=='GET'}
    assert {'/api/station-plots','/api/radar?site=KMPX','/api/satellite/truecolor','/api/satellite/dcphase','/api/satellite/ntmicro','/api/forecast','/api/air-quality','/api/prepared/newest.bin'}<=pages
    assert 'METAR update complete' in result.stdout


def test_failed_build_preserves_running_services_and_schedulers(tmp_path):
    with fake_site() as (url,requests):result,calls=run_update(tmp_path,url,build_fail=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)
    assert not any(c[:4]==['gcloud','scheduler','jobs','delete'] for c in calls)
    assert not requests


def test_incomplete_history_is_not_reported_as_complete(tmp_path):
    with fake_site(bad_history=True) as (url,requests):result,calls=run_update(tmp_path,url)
    assert result.returncode!=0
    assert 'hourly frames were not verified' in result.stderr
    assert 'METAR update complete' not in result.stdout
