"""Avoid duplicate Service Usage mutations and recover only transient limits."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='j-weather-261020012817'


def setup(tmp_path, mode):
    binpath=tmp_path/'bin';binpath.mkdir()
    script='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['SETUP_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='sleep':sys.exit(0)
assert os.environ['CLOUDSDK_BILLING_QUOTA_PROJECT']=='j-weather-261020012817'
assert '--project=j-weather-261020012817' in a and '--billing-project=j-weather-261020012817' in a
mode=os.environ['SETUP_MODE'];countfile=pathlib.Path(os.environ['SETUP_COUNT']);count=int(countfile.read_text()) if countfile.exists() else 0
if a[:2]==['services','list']:
 if mode=='read_denied':print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 apis=['run.googleapis.com','cloudbuild.googleapis.com','artifactregistry.googleapis.com','cloudscheduler.googleapis.com','storage.googleapis.com']
 if mode=='enabled':apis+=['iam.googleapis.com']
 print('\\n'.join(apis))
elif a[:2]==['services','enable']:
 assert a[2]=='iam.googleapis.com' and len([x for x in a[2:] if not x.startswith('--')])==1
 countfile.write_text(str(count+1))
 if mode=='enable_denied':print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 if mode=='always_limited' or (mode=='retry' and count==0):print('429 RATE_LIMIT_EXCEEDED Mutate requests',file=sys.stderr);sys.exit(1)
 print('Enabled IAM')
else:sys.exit(9)
'''
    for tool in ['gcloud','sleep']:
        p=binpath/tool;p.write_text(script);p.chmod(0o755)
    log=tmp_path/'calls';env={**os.environ,'PATH':str(binpath)+os.pathsep+os.environ['PATH'],'SETUP_LOG':str(log),'SETUP_MODE':mode,'SETUP_COUNT':str(tmp_path/'count')}
    result=subprocess.run(['bash',str(ROOT/'ensure-weather-apis.sh'),PROJECT],env=env,capture_output=True,text=True)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    return result,calls


def test_all_enabled_means_no_mutation(tmp_path):
    result,calls=setup(tmp_path,'enabled')
    assert result.returncode==0,result.stderr
    assert len(calls)==1 and calls[0][:3]==['gcloud','services','list']


def test_only_missing_iam_is_enabled_in_the_target_quota_project(tmp_path):
    result,calls=setup(tmp_path,'missing')
    assert result.returncode==0,result.stderr
    assert len(calls)==2 and calls[1][3]=='iam.googleapis.com'


def test_failed_read_never_implies_missing_services(tmp_path):
    result,calls=setup(tmp_path,'read_denied')
    assert result.returncode!=0 and len(calls)==1


def test_permission_error_is_not_retried(tmp_path):
    result,calls=setup(tmp_path,'enable_denied')
    assert result.returncode!=0
    assert not any(c[0]=='sleep' for c in calls)


def test_429_rechecks_services_after_backoff(tmp_path):
    result,calls=setup(tmp_path,'retry')
    assert result.returncode==0,result.stderr
    assert [c[0] for c in calls]==['gcloud','gcloud','sleep','gcloud','gcloud']
    assert calls[2]==['sleep','20']


def test_persistent_quota_failure_is_bounded(tmp_path):
    result,calls=setup(tmp_path,'always_limited')
    assert result.returncode!=0 and 'still exhausted' in result.stderr
    assert len([c for c in calls if c[:3]==['gcloud','services','enable']])==4
    assert [c[1] for c in calls if c[0]=='sleep']==['20','40','60']
