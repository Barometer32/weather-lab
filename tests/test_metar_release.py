"""Exercise staged release and rollback without making any cloud changes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure,retired_exists", [("none",True),("none",False),("candidate",True),("candidate",False),("live",True),("cleanup",True)])
def test_release_waits_for_prepared_maps_and_restores_prior_state_on_failure(tmp_path, failure, retired_exists):
    def executable(name, body):
        path = tmp_path / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    executable("git", "import sys\nprint('abcdef123456' if sys.argv[1]=='rev-parse' else '')\n")
    executable("sleep", "pass\n")
    executable("python3", '''import json,os,sys
from pathlib import Path
root=Path(os.environ['MOCK_ROOT'])
if sys.argv[1]=='verify_weather_release.py':
    with (root/'calls').open('a') as f: f.write(json.dumps(['verify',*sys.argv[2:]])+'\\n')
    failure=os.environ['MOCK_FAILURE']
    if '--all-products' in sys.argv and (failure=='candidate' and 'candidate' in sys.argv[2] or failure=='live' and 'cloud.run' in sys.argv[2]):
        sys.exit(1)
    print('Verified prepared weather')
else:
    os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
''')
    executable("gcloud", '''import json,os,sys
from pathlib import Path
root=Path(os.environ['MOCK_ROOT']); args=sys.argv[1:]
with (root/'calls').open('a') as f: f.write(json.dumps(args)+'\\n')
state_path=root/'state.json'
state=json.loads(state_path.read_text()) if state_path.exists() else {}
project='weather-lab-261105-184200-1a9b'
def option(key):
    return next((a.split('=',1)[1] for a in args if a.startswith(key+'=')),None)
if args[:3]==['run','services','describe']:
    service=args[3]
    traffic=[{'revisionName':service+'-old','percent':100}]
    if service in state:
        traffic.append({'revisionName':service+'-candidate','tag':state[service],'url':'https://'+service+'-candidate.example'})
    env=[{'name':'WEATHER_DATA_BUCKET','value':project+'-weather-data'},{'name':'WEATHER_PREPARED_ONLY','value':'true'}]
    print(json.dumps({'metadata':{'annotations':{'run.googleapis.com/minScale':state.get('minimum','0')}},'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather/app:old','env':env}]}}},'status':{'url':'https://'+service+'.example','traffic':traffic}}))
elif args[:3]==['run','services','update']:
    if option('--tag'): state[args[3]]=option('--tag')
    if option('--min'): state['minimum']=option('--min')
    state_path.write_text(json.dumps(state))
elif args[:3]==['scheduler','jobs','describe']:
    if args[3]=='weather-live-mesonet' and state.get('retiredDeleted'): sys.exit(1)
    fmt=option('--format')
    if fmt=='value(httpTarget.oidcToken.serviceAccountEmail)': print('weather-scheduler@'+project+'.iam.gserviceaccount.com')
    elif fmt=='value(state)': print('PAUSED' if args[3]=='weather-live-hourly-observations' else state.get(args[3]+'-state','ENABLED'))
    elif fmt=='value(schedule)': print('0,30 * * * *')
    else: print(json.dumps({'schedule':'0,5,10 * * * *','attemptDeadline':'180s','state':'ENABLED'}))
elif args[:4] in [['scheduler','jobs','update','http'],['scheduler','jobs','create','http']]:
    state[args[4]+'-schedule']=option('--schedule')
    if args[4]=='weather-live-mesonet': state['retiredDeleted']=False
    if args[4]=='weather-live-rtmetar': state['activeExists']=True
    if args[4]=='weather-live-rapid-observations': state['observationsExists']=True
    state_path.write_text(json.dumps(state))
elif args[:3]==['scheduler','jobs','delete']:
    if args[3]=='weather-live-mesonet': state['retiredDeleted']=True
    if args[3]=='weather-live-rtmetar': state['activeExists']=False
    if args[3]=='weather-live-rapid-observations': state['observationsExists']=False
    if args[3]=='weather-live-rtma-observations': state['rtmaExists']=False
    state_path.write_text(json.dumps(state))
elif args[:3] in [['scheduler','jobs','resume'],['scheduler','jobs','pause']]:
    state[args[3]+'-state']='ENABLED' if args[2]=='resume' else 'PAUSED';state_path.write_text(json.dumps(state))
elif args[:3]==['scheduler','jobs','list']:
    names=['weather-live-metar-clouds','weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-air-quality']
    if not state.get('retiredDeleted'): names.append('weather-live-mesonet')
    if state.get('activeExists'): names.append('weather-live-rtmetar')
    if state.get('observationsExists'): names.append('weather-live-rapid-observations')
    if state.get('rtmaExists'): names.append('weather-live-rtma-observations')
    print(json.dumps([{'name':'projects/'+project+'/locations/us-central1/jobs/'+name,'schedule':state.get(name+'-schedule','*/5 * * * *'),'state':state.get(name+'-state','ENABLED'),'timeZone':'Etc/UTC','httpTarget':{'uri':'https://weather-collector.example/collect/'+name.removeprefix('weather-live-'),'httpMethod':'POST','oidcToken':{'serviceAccountEmail':'weather-scheduler@'+project+'.iam.gserviceaccount.com','audience':'https://weather-collector.example'}}} for name in names]))
elif args[:3]==['storage','buckets','describe']:
    print(json.dumps({'name':project+'-weather-data','lifecycle':{'rule':[{'action':{'type':'Delete'},'condition':{'age':1,'matchesPrefix':['satellite/truecolor/']}}]}}))
elif args[:3]==['storage','buckets','update'] and os.environ['MOCK_FAILURE']=='cleanup':
    sys.exit(1)
elif args[:2]==['storage','ls']:
    print('gs://'+project+'-weather-data/live/mesonet-v1.json')
    print('gs://'+project+'-weather-data/live/metar-loop.json')
''')
    (tmp_path/'state.json').write_text(json.dumps({'retiredDeleted':not retired_exists,'activeExists':retired_exists,'observationsExists':retired_exists,'rtmaExists':retired_exists,'weather-live-satellite-state':'PAUSED'}))
    env = {**os.environ, "PATH": str(tmp_path)+os.pathsep+os.environ["PATH"],
           "MOCK_ROOT": str(tmp_path), "MOCK_FAILURE": failure}
    result = subprocess.run(["bash", str(ROOT / "release-plots.sh")], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=15)
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    cutover = [i for i,c in enumerate(calls) if c[:4] == ["run", "services", "update-traffic", "weather-lab"]
               and "--to-revisions=weather-lab-candidate=100" in c]
    hourly_run = next(i for i,c in enumerate(calls) if c[:4] == ["scheduler", "jobs", "run", "weather-live-metar-clouds"])
    verifications = [i for i,c in enumerate(calls) if c[0] == "verify" and "--all-products" in c]
    assert hourly_run < verifications[0]
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert verifications[0] < cutover[0] < verifications[-1]
        assert any(c[:4] == ["run", "services", "update", "weather-collector"] and "--memory=2Gi" in c for c in calls)
        assert any(c[:4] == ["run", "services", "update", "weather-lab"] and "--min=1" in c for c in calls)
        assert not any("--to-revisions=weather-lab-old=100" in c for c in calls)
        retired=[i for i,c in enumerate(calls) if c[:4] == ["scheduler", "jobs", "delete", "weather-live-mesonet"]]
        assert bool(retired)==retired_exists
        assert all(i>verifications[-1] for i in retired), "Retire MESONET only after live verification"
        assert any(c[:4] == ["scheduler", "jobs", "resume", "weather-live-satellite"] for c in calls)
        assert not any(c[:2] == ["storage", "rm"] for c in calls), "Retain all snapshots"
        rapid_deletions=[i for i,c in enumerate(calls) if c[:4]==["scheduler","jobs","delete","weather-live-rtmetar"]]
        assert bool(rapid_deletions)==retired_exists
        assert all(i>verifications[-1] for i in rapid_deletions), "Retire RTMETAR only after live verification"
        assert not any(c[:4]==["scheduler","jobs","run","weather-live-rtmetar"] for c in calls)
        observation_deletions=[i for i,c in enumerate(calls) if c[:4]==["scheduler","jobs","delete","weather-live-rapid-observations"]]
        assert bool(observation_deletions)==retired_exists
        assert all(i>verifications[-1] for i in observation_deletions), "Retire OBSERVATIONS only after live verification"
        assert not any(c[:4]==["scheduler","jobs","run","weather-live-rapid-observations"] for c in calls)
        assert not any(c[:5]==["scheduler","jobs","create","http","weather-live-rapid-observations"] for c in calls)
        rtma_deletions=[i for i,c in enumerate(calls) if c[:4]==['scheduler','jobs','delete','weather-live-rtma-observations']]
        assert bool(rtma_deletions)==retired_exists
        assert all(i>verifications[-1] for i in rtma_deletions)
        assert not any(c[:4]==['scheduler','jobs','run','weather-live-rtma-observations'] for c in calls)
        assert any(c[:5] == ["scheduler", "jobs", "update", "http", "weather-live-metar-clouds"]
                   and "--schedule=*/2 * * * *" in c for c in calls)
        assert any(c[:5] == ["scheduler", "jobs", "update", "http", "weather-live-forecast"]
                   and "--schedule=*/5 * * * *" in c for c in calls)
        retention = next(i for i,c in enumerate(calls) if c[:3] == ["storage", "buckets", "update"])
        assert retention > verifications[-1], "Retention changes happen after the replacement passes live checks"
    elif failure == "cleanup":
        assert result.returncode != 0
        assert cutover and 'cleanup is incomplete' in result.stderr
        assert not any("--to-revisions=weather-lab-old=100" in c for c in calls), "Keep the verified replacement live when cleanup fails"
    else:
        assert result.returncode != 0
        assert any(c[:4] == ["scheduler", "jobs", "pause", "weather-live-satellite"] for c in calls), "Restore a previously paused schedule on rollback"
        assert bool(cutover) == (failure == "live")
        for service in ["weather-lab", "weather-collector"]:
            assert any(c[:4] == ["run", "services", "update-traffic", service] and f"--to-revisions={service}-old=100" in c for c in calls)
        # Existing jobs retain their original state; newly created jobs are removed.
        if retired_exists:
            assert any(c[:4] == ["scheduler", "jobs", "resume", "weather-live-mesonet"] for c in calls)
            assert not any(c[:4] == ["scheduler", "jobs", "delete", "weather-live-mesonet"] for c in calls)
        else:
            assert not any("weather-live-mesonet" in c for c in calls if c[:2]==["scheduler","jobs"])
        assert not any(c[:4] == ["scheduler", "jobs", "delete", "weather-live-rtmetar"] for c in calls)
        assert not any(c[:4] == ["scheduler", "jobs", "delete", "weather-live-rapid-observations"] for c in calls)
        assert any(c[:4] == ["scheduler", "jobs", "resume", "weather-live-rapid-observations"] for c in calls)==retired_exists
        assert any(c[:4] == ["scheduler", "jobs", "resume", "weather-live-rtmetar"] for c in calls)==retired_exists
        assert any(c[:4]==['scheduler','jobs','resume','weather-live-rtma-observations'] for c in calls)==retired_exists
        assert not any(c[:4]==['scheduler','jobs','delete','weather-live-rtma-observations'] for c in calls)
        assert any(c[:5] == ["scheduler", "jobs", "update", "http", "weather-live-metar-clouds"]
                   and "--schedule=0,5,10 * * * *" in c and "--attempt-deadline=180s" in c for c in calls)
        assert any(c[:4] == ["run", "services", "update", "weather-lab"] and "--min=0" in c for c in calls)
        assert any(c[:5] == ["scheduler", "jobs", "update", "http", "weather-live-forecast"]
                   and "--schedule=0,30 * * * *" in c for c in calls)
