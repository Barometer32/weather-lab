from copy import deepcopy
from unittest.mock import patch
import pytest
import cleanup_weather_jobs as cleanup
from configure_live_jobs import plan as configure

COLLECTOR='https://weather-collector.example.run.app'


def job(name, endpoint=None, state='ENABLED'):
    return {'name':cleanup.PARENT+name,'state':state,'schedule':'*/2 * * * *','timeZone':'Etc/UTC',
            'httpTarget':{'uri':COLLECTOR+'/collect/'+(endpoint or cleanup.REQUIRED.get(name,'retired')),
                          'httpMethod':'POST','oidcToken':{'serviceAccountEmail':cleanup.ACCOUNT,'audience':COLLECTOR}}}


def required():
    return [job(name) for name in cleanup.REQUIRED]


def test_cleanup_removes_only_verified_owned_obsolete_jobs_and_keeps_required():
    rows=required()+[job('weather-live-nbm','nbm',state='PAUSED'),job('weather-live-mn-asos-audit','mn-asos-audit'),
                     job('weather-live-duplicate','current-hourly'),job('other-project-task')]
    foreign=job('weather-live-foreign');foreign['httpTarget']['uri']='https://other.example/collect/retired';rows.append(foreign)
    before=deepcopy(rows)
    remove,leave=cleanup.plan(rows,COLLECTOR)
    assert {r['name'].split('/')[-1] for r in remove}=={'weather-live-nbm','weather-live-mn-asos-audit','weather-live-duplicate'}
    assert len(leave)==2 and rows==before


@pytest.mark.parametrize('fault',['missing','paused','target','identity'])
def test_cleanup_stops_if_a_required_job_is_not_verified(fault):
    rows=required()
    if fault=='missing':rows.pop()
    elif fault=='paused':rows[0]['state']='PAUSED'
    elif fault=='target':rows[0]['httpTarget']['uri']=COLLECTOR+'/collect/other'
    else:rows[0]['httpTarget']['oidcToken']['serviceAccountEmail']='other@example.com'
    with pytest.raises(ValueError):cleanup.plan(rows,COLLECTOR)


def test_apply_checks_twice_and_never_deletes_or_updates_required_jobs():
    rows=required()+[job('weather-live-nbm','nbm')];calls=[]
    def cloud(*args,**kwargs):
        calls.append(args)
        if args[:3]==('scheduler','jobs','delete'):rows[:]=[r for r in rows if r['name']!=args[3]]
    with patch.object(cleanup,'service',side_effect=[COLLECTOR,'https://weather.example']),patch.object(cleanup,'check_site'),patch.object(cleanup,'jobs',side_effect=lambda:deepcopy(rows)),patch.object(cleanup,'gcloud',side_effect=cloud):
        cleanup.cleanup(True)
    assert len(calls)==1 and calls[0][3]==cleanup.PARENT+'weather-live-nbm'
    assert len(rows)==len(cleanup.REQUIRED)


def test_targeted_cleanup_retires_rapmetar_without_deleting_other_jobs():
    rapid = job('weather-live-rapmetar', 'rapmetar')
    other = job('weather-live-nbm', 'nbm')
    rows = required() + [rapid, other]

    def delete(*args, **kwargs):
        assert args[:4] == ('scheduler', 'jobs', 'delete', rapid['name'])
        rows.remove(rapid)

    with patch.object(cleanup, 'service', return_value=COLLECTOR), patch.object(cleanup, 'check_site'), patch.object(cleanup, 'jobs', side_effect=lambda: deepcopy(rows)), patch.object(cleanup, 'gcloud', side_effect=delete) as cloud:
        cleanup.cleanup(True, 'weather-live-rapmetar')
        cleanup.cleanup(True, 'weather-live-rapmetar')
        cloud.assert_called_once()
    assert rows == required() + [other]


def test_cleanup_preview_never_mutates_and_changed_candidate_stops_apply():
    rows=required()+[job('weather-live-nbm')]
    changed=deepcopy(rows);changed[-1]['schedule']='* * * * *'
    with patch.object(cleanup,'service',side_effect=[COLLECTOR,'https://weather.example']),patch.object(cleanup,'check_site'),patch.object(cleanup,'jobs',return_value=rows),patch.object(cleanup,'gcloud') as cloud:
        cleanup.cleanup(False);cloud.assert_not_called()
    with patch.object(cleanup,'service',side_effect=[COLLECTOR,'https://weather.example']),patch.object(cleanup,'check_site'),patch.object(cleanup,'jobs',side_effect=[rows,changed]),patch.object(cleanup,'gcloud') as cloud:
        with pytest.raises(ValueError,match='Candidate changed'):cleanup.cleanup(True)
        cloud.assert_not_called()


def test_current_configuration_preserves_noncurrent_schedules_and_no_rollbacks():
    rows=required();rows[0]['state']='PAUSED';rows[0]['schedule']='*/15 * * * *'
    commands=configure(rows,COLLECTOR)
    assert any('--schedule=*/2 * * * *' in c for c in commands)
    assert any(c[1:4]==['scheduler','jobs','resume'] for c in commands)
    assert not any(c[3] in ('delete','pause') for c in commands)


def test_hourly_lamp_schedule_is_retired():
    old = job('weather-live-hourly', 'hourly')
    rows = required() + [old]
    assert cleanup.plan(rows, COLLECTOR) == ([old], [])
    assert all('weather-live-hourly' not in command for command in configure(rows, COLLECTOR))


def test_revision_cleanup_protects_active_latest_and_scheduled_tag():
    names=['weather-lab-old','weather-lab-current','weather-lab-latest','weather-lab-used-tag']
    info={'status':{'latestReadyRevisionName':names[2],'latestCreatedRevisionName':names[2],
                    'traffic':[{'revisionName':names[1],'percent':100},
                               {'revisionName':names[0],'tag':'old','url':'https://old.example'},
                               {'revisionName':names[3],'tag':'used','url':'https://used.example'}]}}
    active,remove,tags=cleanup.revision_plan(info,[{'metadata':{'name':n}} for n in names],['https://used.example/collect/custom'])
    assert active=={names[1]:100} and remove==[names[0]] and tags==['old']
    info['status']['traffic'][0]['percent']=50
    with pytest.raises(ValueError):cleanup.revision_plan(info,[{'metadata':{'name':n}} for n in names])


def test_revision_apply_removes_old_tags_before_versions_and_preserves_current_traffic():
    calls=[];removed=set()
    def cloud(*args,**kwargs):
        calls.append(args)
        if args[:3]==('run','services','describe'):
            name=args[3]
            traffic=[{'revisionName':name+'-current','percent':100}]
            if name+'-old' not in removed:
                traffic.append({'revisionName':name+'-old','percent':0,'tag':'old','url':'https://old-'+name+'.example'})
            return {'status':{'traffic':traffic,'latestReadyRevisionName':name+'-current','latestCreatedRevisionName':name+'-current'}}
        if args[:3]==('run','revisions','list'):
            name=next(a.split('=',1)[1] for a in args if a.startswith('--service='))
            return [{'metadata':{'name':n}} for n in (name+'-current',name+'-old') if n not in removed]
        if args[:3]==('run','revisions','delete'):
            removed.add(args[3])
    with patch.object(cleanup,'jobs',return_value=required()),patch.object(cleanup,'service',return_value=COLLECTOR),patch.object(cleanup,'gcloud',side_effect=cloud):
        cleanup.cleanup_revisions(True)
    assert removed=={'weather-lab-old','weather-collector-old'}
    for service in ('weather-lab','weather-collector'):
        tag=next(i for i,c in enumerate(calls) if c[:4]==('run','services','update-traffic',service))
        deletion=next(i for i,c in enumerate(calls) if c[:4]==('run','revisions','delete',service+'-old'))
        assert tag<deletion
        assert '--to-revisions='+service+'-current=100' in calls[tag]


def test_revision_apply_stops_when_active_version_changes_before_deletion():
    calls=[];describes=0
    def cloud(*args,**kwargs):
        nonlocal describes
        calls.append(args)
        if args[:3]==('run','services','describe'):
            describes+=1;active='weather-lab-current' if describes==1 else 'weather-lab-old'
            return {'status':{'traffic':[{'revisionName':active,'percent':100}],
                              'latestReadyRevisionName':active,'latestCreatedRevisionName':active}}
        if args[:3]==('run','revisions','list'):
            return [{'metadata':{'name':n}} for n in ('weather-lab-current','weather-lab-old')]
    with patch.object(cleanup,'jobs',return_value=required()),patch.object(cleanup,'service',return_value=COLLECTOR),patch.object(cleanup,'gcloud',side_effect=cloud):
        with pytest.raises(ValueError,match='Deployment changed'):cleanup.cleanup_revisions(True)
    assert not any(c[:3]==('run','revisions','delete') for c in calls)
