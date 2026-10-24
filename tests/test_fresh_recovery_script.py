"""Check billed-project creation, resumability, and optional URL setup offline."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SOURCE='j-weather-261020012817'
COMMIT='f4ede1f4fad8983d6859ab3c91ea3f082a24143e'


def setup(tmp_path):
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls.jsonl'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['FRESH_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 if a[0]=='clone':
  dst=pathlib.Path(a[-1]);(dst/'.git').mkdir(parents=True)
  (dst/'restore-j-weather-airport-metars.sh').write_text("#!/usr/bin/env bash\\npython3 - \\"$@\\" <<'CHECK'\\nimport json,os,sys\\nwith open(os.environ['FRESH_LOG'],'a') as f:f.write(json.dumps(['restore',*sys.argv[1:]])+'\\\\n')\\nsys.exit(1 if os.environ.get('FRESH_RESTORE_FAIL') else 0)\\nCHECK\\n".replace('\\"','"'))
 elif a[-2:]==['rev-parse','HEAD']:print('f4ede1f4fad8983d6859ab3c91ea3f082a24143e')
elif a[:3]==['billing','projects','describe']:print('billingAccounts/TEST-BILLING')
elif a[:3]==['billing','accounts','describe']:print('False' if os.environ.get('FRESH_CLOSED') else 'True')
elif a[:2]==['projects','create']:
 if os.environ.get('FRESH_PROJECT_FAIL'):print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
elif a[:2]==['projects','describe']:print('DELETE_REQUESTED' if os.environ.get('FRESH_DELETED') else 'ACTIVE')
elif a[:3]==['run','services','describe']:print('https://fresh-weather.example.run.app')
elif a[:4]==['beta','run','domain-mappings','create']:
 if os.environ.get('FRESH_DOMAIN_FAIL'):print('ALREADY_EXISTS',file=sys.stderr);sys.exit(1)
 print('Mapping created')
'''
    for name in ['gcloud','git']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'FRESH_LOG':str(log)}
    def run(**options):
        result=subprocess.run(['bash',str(ROOT/'recover-weather-lab-fresh.sh')],env={**env,**{'FRESH_'+k.upper():str(v) for k,v in options.items()}},text=True,capture_output=True)
        calls=[json.loads(line) for line in log.read_text().splitlines()]
        return result,calls
    return run,home


def test_fresh_project_billing_restore_and_requested_url_and_safe_rerun(tmp_path):
    run,home=setup(tmp_path);result,calls=run();assert result.returncode==0,result.stderr
    create=next(c for c in calls if c[:3]==['gcloud','projects','create']);project=create[3]
    assert project.startswith('weather-lab-') and project!=SOURCE
    link=next(c for c in calls if c[:4]==['gcloud','billing','projects','link'])
    assert link[4]==project and '--billing-account=TEST-BILLING' in link
    restore=next(i for i,c in enumerate(calls) if c[0]=='restore')
    domain=next(i for i,c in enumerate(calls) if c[:5]==['gcloud','beta','run','domain-mappings','create'])
    assert restore<domain and calls[restore]==['restore',project]
    assert '--domain=weather-lab.cloud.run' in calls[domain] and '--project='+project in calls[domain]
    assert not any('delete' in c or 'unlink' in c for c in calls)
    assert (home/'weather-lab-fresh-20261024/project-id.txt').read_text().strip()==project
    again,calls=run();assert again.returncode==0,again.stderr
    assert sum(c[:3]==['gcloud','projects','create'] for c in calls)==1
    assert sum(c[0]=='restore' for c in calls)==1


def test_closed_billing_prevents_project_creation(tmp_path):
    run,_=setup(tmp_path);result,calls=run(closed=1)
    assert result.returncode!=0
    assert not any(c[:3]==['gcloud','projects','create'] for c in calls)


def test_failed_restore_resumes_same_project_and_does_not_claim_url_early(tmp_path):
    run,_=setup(tmp_path);result,calls=run(restore_fail=1)
    assert result.returncode!=0 and not any('domain-mappings' in c for c in calls)
    again,calls=run();assert again.returncode==0,again.stderr
    assert sum(c[:3]==['gcloud','projects','create'] for c in calls)==1
    assert sum(c[0]=='restore' for c in calls)==2


def test_claim_failure_keeps_working_direct_url_and_never_deletes_mapping(tmp_path):
    run,_=setup(tmp_path);result,calls=run(domain_fail=1)
    assert result.returncode==0,result.stderr
    assert 'ALREADY_EXISTS' in result.stderr
    assert 'Direct website: https://fresh-weather.example.run.app' in result.stdout
    assert not any('delete' in c for c in calls)


def test_deleted_resume_project_is_not_replaced_or_rebilled(tmp_path):
    run,_=setup(tmp_path);result,calls=run(deleted=1)
    assert result.returncode!=0
    assert not any(c[:4]==['gcloud','billing','projects','link'] or c[0]=='restore' for c in calls)
