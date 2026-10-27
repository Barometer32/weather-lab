"""Exercise fresh-project recovery and cutover failures without cloud mutations."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OLD = 'weather-lab-261024-133205'


def setup(tmp_path):
    binary = tmp_path / 'bin'; binary.mkdir()
    home = tmp_path / 'home'; home.mkdir()
    log = tmp_path / 'calls'
    stub = r"""#!/usr/bin/env python3
import json,os,pathlib,sys,shutil
a=sys.argv[1:];name=pathlib.Path(sys.argv[0]).name
home=pathlib.Path(os.environ['HOME']);old='weather-lab-261024-133205'
with open(os.environ['MIGRATE_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\n')
def fail(label):print(label,file=sys.stderr);sys.exit(1)
if name=='python3':
 if a and a[0].endswith('/verify_weather_site.py'):
  if os.environ.get('MIGRATE_VERIFY_FAIL'):fail('prepared radar missing')
  print('All prepared pages verified');sys.exit(0)
 os.execv(os.environ['MIGRATE_PYTHON'],[os.environ['MIGRATE_PYTHON'],*a])
if name=='git':
 if a[0]=='clone':
  dst=pathlib.Path(a[-1]);(dst/'.git').mkdir(parents=True)
  for file in ['ensure-weather-apis.sh','verify_weather_site.py']:(dst/file).write_text('# stub\n')
  (dst/'restore-weather-lab-latest.sh').write_text('''#!/usr/bin/env bash
python3 - "$1" <<'PY'
import json,os,pathlib,sys
with open(os.environ['MIGRATE_LOG'],'a') as f:f.write(json.dumps(['restore',sys.argv[1],os.environ.get('WEATHER_RESTORE_SOURCE_COMMIT'),os.environ.get('WEATHER_SKIP_DOMAIN_SETUP')])+'\\n')
sys.exit(1 if os.environ.get('MIGRATE_RESTORE_FAIL') else 0)
PY
''')
 sys.exit(0)
if name=='curl':
 if os.environ.get('MIGRATE_COLLECTOR_FAIL') and any('/collect/' in arg for arg in a):fail('collector unavailable')
 if os.environ.get('MIGRATE_CUSTOM_FAIL') and 'https://weather-lab.cloud.run/' in a:fail('custom URL unavailable')
 if '-o' in a:pathlib.Path(a[a.index('-o')+1]).write_text('{}')
 sys.exit(0)
if name=='sleep':sys.exit(0)
if a[:3]==['billing','projects','describe']:
 if any('format=yaml' in v for v in a):print('billingEnabled: false')
 else:print('billingAccounts/TEST-BILLING')
elif a[:3]==['billing','accounts','describe']:print('False' if os.environ.get('MIGRATE_CLOSED') else 'True')
elif a[:2]==['projects','create']:
 if os.environ.get('MIGRATE_PROJECT_FAIL'):fail('PERMISSION_DENIED')
elif a[:2]==['projects','describe']:print('DELETE_REQUESTED' if os.environ.get('MIGRATE_DELETED') else 'ACTIVE')
elif a[:3]==['storage','buckets','list']:
 if os.environ.get('MIGRATE_BUCKET_READ_FAIL'):fail('PERMISSION_DENIED')
 print(json.dumps([] if os.environ.get('MIGRATE_NO_DATA') or '--project='+old not in a else [{'name':old+'-weather-data'}]))
elif a[:2]==['storage','rsync'] and os.environ.get('MIGRATE_COPY_FAIL'):fail('copy failed')
elif a[:3]==['run','services','describe']:
 print('https://'+a[3]+'-123.us-central1.run.app')
elif a[:2]==['auth','print-identity-token']:print('test-token')
elif a[:4]==['beta','run','domain-mappings','list']:
 if os.environ.get('MIGRATE_MAPPING_READ_FAIL'):fail('PERMISSION_DENIED')
 source='--project='+old in a
 exists=(not (home/'old-deleted').exists() if source else (home/'new-created').exists())
 route='other-service' if source and os.environ.get('MIGRATE_OTHER_ROUTE') else 'weather-lab'
 print(json.dumps([{'metadata':{'name':'weather-lab.cloud.run'},'spec':{'routeName':route}}] if exists else []))
elif a[:4]==['beta','run','domain-mappings','delete']:(home/'old-deleted').touch()
elif a[:4]==['beta','run','domain-mappings','create']:
 source='--project='+old in a
 if not source and os.environ.get('MIGRATE_CLAIM_FAIL'):fail('ALREADY_EXISTS')
 if source:(home/'old-deleted').unlink(missing_ok=True)
 else:(home/'new-created').touch()
elif a[:4]==['beta','run','domain-mappings','describe']:
 print(json.dumps({'spec':{'routeName':'weather-lab'},'status':{'conditions':[{'type':'Ready','status':'False' if os.environ.get('MIGRATE_PENDING') else 'True'}]}}))
"""
    for name in ('gcloud', 'git', 'curl', 'python3', 'sleep'):
        path = binary / name; path.write_text(stub.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1)); path.chmod(0o755)
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'HOME': str(home), 'MIGRATE_LOG': str(log), 'MIGRATE_PYTHON': sys.executable}

    def run(**options):
        result = subprocess.run(['bash', str(ROOT / 'start-weather-lab-fresh.sh'), OLD], env={**env, **{'MIGRATE_' + k.upper(): str(v) for k, v in options.items()}}, text=True, capture_output=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls
    return run, home


def cloud(calls, prefix):
    return [(i, call) for i, call in enumerate(calls) if call[:len(prefix)+1] == ['gcloud', *prefix]]


def test_fresh_rebuild_copy_verification_and_transfer_before_old_billing_stops(tmp_path):
    run, home = setup(tmp_path); result, calls = run()
    assert result.returncode == 0, result.stderr
    created = cloud(calls, ['projects', 'create'])[0][1]
    new = created[3]
    assert len(new) <= 30 and new != OLD
    assert '--name=Weather Lab' in created
    copied = cloud(calls, ['storage', 'rsync'])[0][0]
    restored = next(i for i, c in enumerate(calls) if c[0] == 'restore')
    verified = next(i for i, c in enumerate(calls) if c[0] == 'python3' and c[1].endswith('/verify_weather_site.py'))
    deleted = cloud(calls, ['beta', 'run', 'domain-mappings', 'delete'])[0]
    claimed = cloud(calls, ['beta', 'run', 'domain-mappings', 'create'])[0]
    unlinked = cloud(calls, ['billing', 'projects', 'unlink'])[0]
    assert copied < restored < verified < deleted[0] < claimed[0] < unlinked[0]
    assert '--project=' + OLD in deleted[1] and '--project=' + new in claimed[1]
    assert unlinked[1][4] == OLD
    assert calls[restored][2:] == ['ada1bdb84bfa39d3608812a6ed392a588e303b50', 'true']
    assert not cloud(calls, ['projects', 'delete'])
    assert (home / 'weather-lab-fresh-migration/project-id.txt').read_text().strip() == new
    again, calls = run()
    assert again.returncode == 0, again.stderr
    assert len(cloud(calls, ['projects', 'create'])) == 1
    assert sum(c[0] == 'restore' for c in calls) == 1
    assert len(cloud(calls, ['beta', 'run', 'domain-mappings', 'delete'])) == 1
    assert len(cloud(calls, ['storage', 'rsync'])) == 1


def test_failed_restore_resumes_same_project_without_touching_address(tmp_path):
    run, _ = setup(tmp_path); result, calls = run(restore_fail=1)
    assert result.returncode != 0
    assert not cloud(calls, ['beta', 'run', 'domain-mappings'])
    assert not cloud(calls, ['billing', 'projects', 'unlink'])
    again, calls = run()
    assert again.returncode == 0, again.stderr
    assert len(cloud(calls, ['projects', 'create'])) == 1


def test_claim_failure_attempts_rollback_and_keeps_old_billing(tmp_path):
    run, home = setup(tmp_path); result, calls = run(claim_fail=1)
    assert result.returncode != 0 and 'Direct website:' in result.stderr
    claims = cloud(calls, ['beta', 'run', 'domain-mappings', 'create'])
    assert len(claims) == 2 and '--project=' + OLD in claims[-1][1]
    assert not (home / 'old-deleted').exists()
    assert not cloud(calls, ['billing', 'projects', 'unlink'])


def test_pending_mapping_resumes_without_releasing_name_again(tmp_path):
    run, _ = setup(tmp_path); result, calls = run(pending=1)
    assert result.returncode != 0 and 'routing is still pending' in result.stderr
    assert not cloud(calls, ['billing', 'projects', 'unlink'])
    again, calls = run()
    assert again.returncode == 0, again.stderr
    assert len(cloud(calls, ['beta', 'run', 'domain-mappings', 'delete'])) == 1


def test_custom_url_failure_keeps_old_billing_until_successful_retry(tmp_path):
    run, _ = setup(tmp_path); result, calls = run(custom_fail=1)
    assert result.returncode != 0
    assert not cloud(calls, ['billing', 'projects', 'unlink'])
    again, calls = run()
    assert again.returncode == 0, again.stderr
    assert len(cloud(calls, ['projects', 'create'])) == 1
    assert len(cloud(calls, ['beta', 'run', 'domain-mappings', 'delete'])) == 1


def test_bad_readiness_or_collector_or_mapping_never_releases_address(tmp_path):
    for index, option in enumerate(('verify_fail', 'collector_fail', 'mapping_read_fail', 'other_route', 'copy_fail', 'bucket_read_fail')):
        folder = tmp_path / str(index); folder.mkdir()
        run, _ = setup(folder); result, calls = run(**{option: 1})
        assert result.returncode != 0, option
        assert not cloud(calls, ['beta', 'run', 'domain-mappings', 'delete']), option
        assert not cloud(calls, ['billing', 'projects', 'unlink']), option


def test_closed_account_or_deleted_new_project_stops_without_build(tmp_path):
    for index, option in enumerate(('closed', 'deleted', 'project_fail')):
        folder = tmp_path / str(index); folder.mkdir()
        run, _ = setup(folder); result, calls = run(**{option: 1})
        assert result.returncode != 0
        assert not any(c[0] == 'restore' for c in calls)
        assert not cloud(calls, ['billing', 'projects', 'unlink'])
        if option == 'closed': assert not cloud(calls, ['projects', 'create'])


def test_missing_bucket_rebuilds_without_attempting_copy(tmp_path):
    run, _ = setup(tmp_path); result, calls = run(no_data=1)
    assert result.returncode == 0, result.stderr
    assert not cloud(calls, ['storage', 'rsync'])
    assert any(c[0] == 'restore' for c in calls)
