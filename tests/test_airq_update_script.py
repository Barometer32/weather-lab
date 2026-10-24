import json,os,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run_update(tmp_path,**options):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['AIRQ_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  p=pathlib.Path(a[-1]);p.mkdir();shutil.copyfile(pathlib.Path(os.environ['AIRQ_ROOT'])/'data-lifecycle.json',p/'data-lifecycle.json')
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':
 p=pathlib.Path(a[a.index('-o')+1])
 if p.name=='page.html':p.write_text((pathlib.Path(os.environ['AIRQ_ROOT'])/'static/index.html').read_text())
 else:p.write_text(json.dumps({'version':'mn-region-v2','timeBasis':'source','frames':[{'time':'2026-10-23T23:00:00Z','sourceTime':'2026-10-23T23:00:00Z','style':'contours-only-no-labels'}]}))
elif a[:3]==['run','services','describe']:
 if os.environ.get('AIRQ_DENIED'):sys.exit(1)
 print('collector@example.iam.gserviceaccount.com' if '--format=value(spec.template.spec.serviceAccountName)' in a else 'https://weather.example.run.app')
elif a[:3]==['scheduler','jobs','list']:print(json.dumps([{'name':'projects/p/locations/us-central1/jobs/weather-live-air-quality'}] if os.environ.get('AIRQ_EXISTING') else []))
elif a[:3]==['scheduler','jobs','describe']:print('PAUSED' if os.environ.get('AIRQ_PAUSED') else 'ENABLED')
elif a[:4]==['artifacts','docker','images','describe']:sys.exit(0 if os.environ.get('AIRQ_REUSE') else 1)
elif a[:2]==['builds','submit'] and os.environ.get('AIRQ_BUILD_FAIL'):sys.exit(1)
elif a[:3]==['run','jobs','execute'] and os.environ.get('AIRQ_SEED_FAIL'):sys.exit(1)
'''
    for name in ['gcloud','git','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'AIRQ_LOG':str(log),'AIRQ_ROOT':str(ROOT),**{'AIRQ_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'update-j-weather-airq.sh')],env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_captures_before_publishing_and_adds_only_hourly_airq_schedule(tmp_path):
    result,calls=run_update(tmp_path);assert result.returncode==0,result.stderr
    seed=next(i for i,c in enumerate(calls) if c[:4]==['gcloud','run','jobs','execute'])
    web=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','run','services','update','weather-lab'])
    assert seed<web
    jobs=[c for c in calls if c[:4] in [['gcloud','scheduler','jobs','create'],['gcloud','scheduler','jobs','update']]]
    assert len(jobs)==1 and jobs[0][5]=='weather-live-air-quality' and '--schedule=0,30 * * * *' in jobs[0]
    assert '--oidc-token-audience=https://weather.example.run.app' in jobs[0]
    assert not any(c[:3]==['gcloud','services','enable'] or 'delete' in c for c in calls)
    assert 'Verified 1/12 saved Air Q data hours.' in result.stdout


def test_seed_failure_keeps_old_website_and_schedules(tmp_path):
    result,calls=run_update(tmp_path,seed_fail=1);assert result.returncode!=0
    assert not any(c[:5]==['gcloud','run','services','update','weather-lab'] for c in calls)
    assert not any(c[:4] in [['gcloud','scheduler','jobs','create'],['gcloud','scheduler','jobs','update']] for c in calls)


def test_existing_paused_job_is_updated_and_resumed_with_reused_image(tmp_path):
    result,calls=run_update(tmp_path,existing=1,paused=1,reuse=1);assert result.returncode==0,result.stderr
    assert any(c[:6]==['gcloud','scheduler','jobs','update','http','weather-live-air-quality'] for c in calls)
    assert any(c[:5]==['gcloud','scheduler','jobs','resume','weather-live-air-quality'] for c in calls)
    assert not any(c[:3]==['gcloud','builds','submit'] for c in calls)


def test_read_or_build_failure_stops_before_updates(tmp_path):
    for kind in ['denied','build_fail']:
        path=tmp_path/kind;path.mkdir();result,calls=run_update(path,**{kind:1});assert result.returncode!=0
        assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)
