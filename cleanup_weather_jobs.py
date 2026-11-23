"""Remove obsolete, verified Weather Lab schedules."""
import argparse
import json
import subprocess
from urllib.parse import urlsplit
from urllib.request import urlopen

PROJECT = 'weather-lab-261105-184200-1a9b'
REGION = 'us-central1'
PARENT = f'projects/{PROJECT}/locations/{REGION}/jobs/'
ACCOUNT = f'weather-scheduler@{PROJECT}.iam.gserviceaccount.com'
REQUIRED = {
    'weather-live-current': 'current-hourly',
    'weather-live-metar-clouds': 'metar-clouds',
    'weather-live-rapmetar': 'rapmetar',
    'weather-live-radar': 'radar-KMPX',
    'weather-live-satellite': 'satellite',
    'weather-live-forecast': 'forecast',
    'weather-live-air-quality': 'air-quality',
}
# Older jobs with this name predate the weather-live-* naming convention.
LEGACY_NAMES = {'weather-hourly'}


def gcloud(*args, output=True):
    result = subprocess.run(['gcloud', *args, '--project='+PROJECT], check=True,
                            text=True, capture_output=output)
    return json.loads(result.stdout) if output else None


def jobs():
    return gcloud('scheduler', 'jobs', 'list', '--location='+REGION, '--format=json')


def configuration(job):
    return {k: job.get(k) for k in ('name','description','state','schedule','timeZone',
                                   'httpTarget','pubsubTarget','appEngineHttpTarget',
                                   'retryConfig','attemptDeadline')}


def owned(job, collector):
    target = job.get('httpTarget', {})
    uri = urlsplit(target.get('uri', ''))
    base = urlsplit(collector)
    token = target.get('oidcToken', {})
    return (uri.scheme == base.scheme == 'https' and uri.netloc == base.netloc
            and uri.path.startswith('/collect/') and not uri.query and not uri.fragment
            and target.get('httpMethod') == 'POST'
            and token.get('serviceAccountEmail') == ACCOUNT
            and token.get('audience') == collector)


def plan(rows, collector):
    by_name = {r['name'].removeprefix(PARENT): r for r in rows if r['name'].startswith(PARENT)}
    for name, endpoint in REQUIRED.items():
        row = by_name.get(name)
        if not row or row.get('state') != 'ENABLED' or not owned(row, collector):
            raise ValueError('Required schedule is missing, paused or not verified: '+name)
        if row['httpTarget']['uri'] != collector+'/collect/'+endpoint:
            raise ValueError('Required schedule has an unexpected endpoint: '+name)
    remove, leave = [], []
    for name, row in by_name.items():
        if name in REQUIRED:
            continue
        if ((name.startswith('weather-live-') or name in LEGACY_NAMES)
                and row.get('state') in ('ENABLED','PAUSED') and owned(row, collector)):
            remove.append(row)
        else:
            leave.append(row)
    return sorted(remove, key=lambda r:r['name']), leave


def service(name):
    row = gcloud('run','services','describe',name,'--region='+REGION,'--format=json')
    if not any(c['type']=='Ready' and c['status']=='True' for c in row['status']['conditions']):
        raise ValueError('Cloud Run service is not ready: '+name)
    return row['status']['url']


def check_site(web):
    with urlopen(web+'/api/current', timeout=30) as response:
        data = json.load(response)
    if (data.get('version') != 'official-hourly-t-remarks-v1'
            or not (data.get('current') or {}).get('complete')):
        raise ValueError('The CURRENT page does not yet have a complete official hour')


def cleanup(apply=False):
    collector = service('weather-collector')
    web = service('weather-lab')
    check_site(web)
    before = jobs()
    remove, leave = plan(before, collector)
    for name in REQUIRED:
        print('KEEP', name, flush=True)
    for row in remove:
        print('REMOVE', row['name'].split('/')[-1], flush=True)
    for row in leave:
        print('UNCHANGED (ownership not verified)', row['name'].split('/')[-1], flush=True)
    if not apply:
        print('Preview only. Run with --apply to remove the listed obsolete jobs.')
        return
    required_before = {r['name']: configuration(r) for r in before if r['name'].split('/')[-1] in REQUIRED}
    for row in remove:
        # Stop if any required job or candidate was edited during cleanup.
        fresh = jobs()
        plan(fresh, collector)
        indexed = {r['name']: r for r in fresh}
        if any(configuration(indexed[name]) != config for name, config in required_before.items()):
            raise ValueError('Required schedule changed during cleanup; stopped')
        if row['name'] not in indexed:
            continue
        if configuration(indexed[row['name']]) != configuration(row):
            raise ValueError('Candidate changed during cleanup; stopped: '+row['name'])
        gcloud('scheduler','jobs','delete',row['name'],'--location='+REGION,'--quiet',output=False)
    remaining = jobs()
    leftovers, _ = plan(remaining, collector)
    if leftovers:
        raise ValueError('Obsolete owned jobs remain; rerun after inspecting the output')
    after = {r['name']: configuration(r) for r in remaining if r['name'].split('/')[-1] in REQUIRED}
    if after != required_before:
        raise ValueError('A required schedule changed; inspect Cloud Scheduler')
    print('Cleanup complete. All required schedules are enabled.', flush=True)


def revision_plan(info, revisions, scheduled_uris=()):
    """Protect all traffic-serving/latest revisions and externally scheduled tags."""
    status=info['status']
    active={t['revisionName']:int(t.get('percent',0)) for t in status['traffic'] if t.get('percent')}
    if sum(active.values())!=100:
        raise ValueError('Service traffic is not a verified 100-percent assignment')
    protected=set(active)|{status.get('latestReadyRevisionName'),status.get('latestCreatedRevisionName')}
    tags=status.get('traffic',[])
    for tag in tags:
        if tag.get('url') and any(uri.startswith(tag['url']+'/') or uri==tag['url'] for uri in scheduled_uris):
            protected.add(tag['revisionName'])
    names={r['metadata']['name'] for r in revisions}
    if not set(active)<=names:
        raise ValueError('Active revisions could not be found; no revisions will be deleted')
    remove=sorted(names-protected)
    remove_tags=[t['tag'] for t in tags if t.get('tag') and t['revisionName'] in remove]
    return active, remove, remove_tags


def cleanup_revisions(apply=False):
    rows=jobs()
    plan(rows,service('weather-collector'))
    uris=[r.get('httpTarget',{}).get('uri','') for r in rows]
    for name in ('weather-lab','weather-collector'):
        info=gcloud('run','services','describe',name,'--region='+REGION,'--format=json')
        revisions=gcloud('run','revisions','list','--service='+name,'--region='+REGION,'--format=json')
        active,remove,tags=revision_plan(info,revisions,uris)
        if any(not r.startswith(name+'-') for r in remove):
            raise ValueError('Unexpected revision identity; stopped')
        print(name+': '+str(len(remove))+' obsolete deployment versions',flush=True)
        if not apply or not remove:
            continue
        if tags:
            # Preserve the exact current traffic percentages; remove old tag URLs.
            assignment=','.join(k+'='+str(v) for k,v in sorted(active.items()))
            gcloud('run','services','update-traffic',name,'--region='+REGION,
                   '--to-revisions='+assignment,'--remove-tags='+','.join(tags),output=False)
        for revision in remove:
            fresh=gcloud('run','services','describe',name,'--region='+REGION,'--format=json')
            fresh_active,still_removable,_=revision_plan(fresh,revisions,uris)
            if fresh_active!=active or revision not in still_removable:
                raise ValueError('Deployment changed during cleanup; stopped')
            print('REMOVE revision',revision,flush=True)
            gcloud('run','revisions','delete',revision,'--region='+REGION,'--quiet',output=False)
        remaining=gcloud('run','revisions','list','--service='+name,'--region='+REGION,'--format=json')
        final=gcloud('run','services','describe',name,'--region='+REGION,'--format=json')
        if revision_plan(final,remaining,uris)[0]!=active:
            raise ValueError('Unexpected traffic change; inspect service')
    print('Current and latest deployment versions retained; old rollback versions removed.' if apply else 'Revision cleanup preview only.',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--old-revisions',action='store_true',help='Also remove unused old deployment versions')
    args=parser.parse_args()
    cleanup(args.apply)
    if args.old_revisions:
        cleanup_revisions(args.apply)
