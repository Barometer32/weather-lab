"""The compact plot update resolves the live domain and touches only its web service."""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OLD='j-weather-261020012817'
NEW='weather-lab-261024-133205'


def run_update(tmp_path,**options):
    project_arg=options.pop('project',None)
    binary=tmp_path/'bin';binary.mkdir();home=tmp_path/'home';home.mkdir();log=tmp_path/'calls'
    stub='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with open(os.environ['PLOT_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
project=next((v.split('=',1)[1] for v in a if v.startswith('--project=')),'')
if name=='git':
 if a[0]=='clone':pathlib.Path(a[-1]).mkdir()
 else:print('abc1234567890000000000000000000000000000')
elif name=='curl':pathlib.Path(a[a.index('-o')+1]).write_text((pathlib.Path(os.environ['PLOT_ROOT'])/'static/index.html').read_text())
elif a[:4]==['beta','run','domain-mappings','describe']:
 if os.environ.get('PLOT_UNRESOLVED') or project!=os.environ.get('PLOT_OWNER','weather-lab-261024-133205') and not os.environ.get('PLOT_AMBIGUOUS'):
  print('NOT_FOUND',file=sys.stderr);sys.exit(1)
 print(json.dumps({'metadata':{'name':'weather-lab.cloud.run'},'spec':{'routeName':'other-service' if os.environ.get('PLOT_WRONG_ROUTE') else 'weather-lab'}}))
elif a[:3]==['run','services','describe']:
 if os.environ.get('PLOT_DENIED'):print('PERMISSION_DENIED',file=sys.stderr);sys.exit(1)
 if '--format=value(status.url)' in a:print('https://weather.example.run.app')
 elif '--format=value(spec.template.spec.containers[0].image)' in a:print('unrelated.example/app:latest' if os.environ.get('PLOT_BAD_IMAGE') else 'us-central1-docker.pkg.dev/'+project+'/recovery-images/app@sha256:abc123')
 else:print('metadata: {}')
elif a[:2]==['builds','submit'] and os.environ.get('PLOT_BUILD_FAIL'):sys.exit(1)
'''
    for name in ['gcloud','git','curl']:
        p=binary/name;p.write_text(stub);p.chmod(0o755)
    env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'HOME':str(home),'PLOT_LOG':str(log),'PLOT_ROOT':str(ROOT),**{'PLOT_'+k.upper():str(v) for k,v in options.items()}}
    result=subprocess.run(['bash',str(ROOT/'update-weather-lab-plots.sh')]+([project_arg] if project_arg else []),env=env,text=True,capture_output=True)
    return result,[json.loads(line) for line in log.read_text().splitlines()]


def test_locates_live_new_project_and_preserves_registry_and_background_services(tmp_path):
    result,calls=run_update(tmp_path);assert result.returncode==0,result.stderr
    build=next(c for c in calls if c[:3]==['gcloud','builds','submit'])
    assert '--project='+NEW in build
    assert '--tag=us-central1-docker.pkg.dev/'+NEW+'/recovery-images/app:plots-abc123456789' in build
    updates=[c for c in calls if c[:4]==['gcloud','run','services','update']]
    assert len(updates)==1 and updates[0][4]=='weather-lab' and '--project='+NEW in updates[0]
    assert not any('weather-collector' in c or 'scheduler' in c or 'delete' in c or 'billing' in c or 'enable' in c for c in calls)
    assert 'https://weather-lab.cloud.run' in result.stdout


def test_old_project_is_used_if_it_is_the_verified_domain_owner(tmp_path):
    result,calls=run_update(tmp_path,owner=OLD);assert result.returncode==0,result.stderr
    assert '--project='+OLD in next(c for c in calls if c[:3]==['gcloud','builds','submit'])


def test_ambiguous_missing_or_wrong_domain_route_stops_before_build(tmp_path):
    for kind in ['ambiguous','unresolved','wrong_route']:
        d=tmp_path/kind;d.mkdir();result,calls=run_update(d,**{kind:1})
        assert result.returncode!=0
        assert not any(c[:3]==['gcloud','builds','submit'] or c[:4]==['gcloud','run','services','update'] for c in calls)


def test_settings_or_build_failure_keeps_running_website(tmp_path):
    for kind in ['denied','bad_image','build_fail']:
        d=tmp_path/kind;d.mkdir();result,calls=run_update(d,**{kind:1})
        assert result.returncode!=0
        assert not any(c[:4]==['gcloud','run','services','update'] for c in calls)


def test_confirmed_project_argument_bypasses_inconclusive_domain_discovery(tmp_path):
    result,calls=run_update(tmp_path,project=NEW,unresolved=1)
    assert result.returncode==0,result.stderr
    assert not any('domain-mappings' in c for c in calls)
    build=next(c for c in calls if c[:3]==['gcloud','builds','submit'])
    update=next(c for c in calls if c[:4]==['gcloud','run','services','update'])
    assert '--project='+NEW in build and '--project='+NEW in update
    assert not any('weather-collector' in c or 'scheduler' in c or 'delete' in c for c in calls)
