"""Exercise staged release and rollback without making any cloud changes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", ["none", "candidate", "live"])
def test_release_waits_for_prepared_maps_and_restores_prior_state_on_failure(tmp_path, failure):
    def executable(name, body):
        path = tmp_path / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    executable("git", "import sys\nprint('abcdef123456' if sys.argv[1]=='rev-parse' else '')\n")
    executable("sleep", "pass\n")
    executable("python3", '''import json,os,sys
from pathlib import Path
root=Path(os.environ['MOCK_ROOT'])
if sys.argv[1]=='verify_rtmetar_release.py':
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
    print(json.dumps({'metadata':{'annotations':{'run.googleapis.com/minScale':'0'}},'spec':{'template':{'spec':{'containers':[{'image':'us-central1-docker.pkg.dev/'+project+'/weather/app:old'}]}}},'status':{'url':'https://'+service+'.example','traffic':traffic}}))
elif args[:3]==['run','services','update']:
    if option('--tag'):
        state[args[3]]=option('--tag');state_path.write_text(json.dumps(state))
elif args[:3]==['scheduler','jobs','describe']:
    fmt=option('--format')
    if fmt=='value(httpTarget.oidcToken.serviceAccountEmail)': print('weather-scheduler@'+project+'.iam.gserviceaccount.com')
    elif fmt=='value(state)': print('PAUSED' if args[3]=='weather-live-hourly-observations' else 'ENABLED')
    else: print(json.dumps({'schedule':'0,5,10 * * * *','attemptDeadline':'180s','state':'ENABLED'}))
''')
    env = {**os.environ, "PATH": str(tmp_path)+os.pathsep+os.environ["PATH"],
           "MOCK_ROOT": str(tmp_path), "MOCK_FAILURE": failure}
    result = subprocess.run(["bash", str(ROOT / "release-rtmetar.sh")], cwd=ROOT,
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
        assert any(c[:4] == ["run", "services", "update", "weather-lab"] and "--min=1" in c for c in calls)
        assert not any("--to-revisions=weather-lab-old=100" in c for c in calls)
    else:
        assert result.returncode != 0
        assert bool(cutover) == (failure == "live")
        for service in ["weather-lab", "weather-collector"]:
            assert any(c[:4] == ["run", "services", "update-traffic", service] and f"--to-revisions={service}-old=100" in c for c in calls)
        # A rollback must retain an existing enabled RTMETAR job.
        assert any(c[:4] == ["scheduler", "jobs", "resume", "weather-live-rtmetar"] for c in calls)
        assert not any(c[:4] == ["scheduler", "jobs", "pause", "weather-live-rtmetar"] for c in calls)
        assert any(c[:5] == ["scheduler", "jobs", "update", "http", "weather-live-metar-clouds"]
                   and "--schedule=0,5,10 * * * *" in c and "--attempt-deadline=180s" in c for c in calls)
        assert any(c[:4] == ["run", "services", "update", "weather-lab"] and "--min=0" in c for c in calls)
