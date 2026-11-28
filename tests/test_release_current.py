"""Exercise the supported deployment entrypoint without cloud mutations."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure',[False,True])
def test_release_checks_prepared_data_before_switching_web_and_cleanup(tmp_path,failure):
    def executable(name,body):
        p=tmp_path/name;p.write_text('#!'+sys.executable+'\n'+body);p.chmod(0o755)
    executable('git',"import sys\nprint('abcdef123456' if sys.argv[1]=='rev-parse' else '')\n")
    executable('sleep','pass\n')
    executable('python3', '''import os,sys,json
from pathlib import Path
p=Path(os.environ['CALLS'])
if sys.argv[1]=='-c' and 'from configure_live_jobs' not in sys.argv[2]:os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
with p.open('a') as f:f.write(json.dumps(['python',*sys.argv[1:]])+'\\n')
if sys.argv[1]=='verify_weather_release.py' and '--all-products' in sys.argv and 'candidate' in sys.argv[2] and os.environ['FAIL']=='1':sys.exit(1)
''')
    executable('gcloud', '''import sys,json,os
from pathlib import Path
a=sys.argv[1:]
with Path(os.environ['CALLS']).open('a') as f:f.write(json.dumps(a)+'\\n')
project='weather-lab-261105-184200-1a9b'
if a[:3]==['run','services','describe']:
 name=a[3];fmt=next(x.split('=',1)[1] for x in a if x.startswith('--format='))
 image='us-central1-docker.pkg.dev/'+project+'/weather-lab/app:old'
 if fmt.startswith('value('):print(image)
 else:print(json.dumps({'metadata':{'annotations':{'run.googleapis.com/minScale':'1'}},'spec':{'template':{'spec':{'containers':[{'image':image}]}}},'status':{'traffic':[{'revisionName':name+'-old','percent':100},{'revisionName':name+'-new','tag':'live-ready-abcdef123456','url':'https://candidate.example'}]}}))
''')
    env={**os.environ,'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'],'CALLS':str(tmp_path/'calls'),'FAIL':'1' if failure else '0'}
    result=subprocess.run(['bash',str(ROOT/'release-plots.sh')],cwd=ROOT,env=env,capture_output=True,text=True,timeout=15)
    calls=[json.loads(line) for line in (tmp_path/'calls').read_text().splitlines()]
    switches=[i for i,c in enumerate(calls) if c[:4]==['run','services','update-traffic','weather-lab']]
    cleanup=[i for i,c in enumerate(calls) if c[:2]==['python','cleanup_weather_jobs.py']]
    if failure:
        assert result.returncode!=0 and not switches and not cleanup
        assert 'website traffic was not switched' in result.stderr
    else:
        assert result.returncode==0,result.stderr
        checks=[i for i,c in enumerate(calls) if c[:2]==['python','verify_weather_release.py'] and '--all-products' in c]
        assert checks[0]<switches[0]<checks[-1]<cleanup[0]
        assert [calls[i][2:] for i in cleanup] == [
            ['--apply', '--only-job', 'weather-live-rapmetar'],
            ['--apply', '--only-job', 'weather-live-hourly'],
        ]
        runs=[c[3] for c in calls if c[:3]==['scheduler','jobs','run']]
        assert set(runs)=={'weather-live-current','weather-live-metar-clouds','weather-live-radar','weather-live-satellite','weather-live-forecast','weather-live-air-quality'}
