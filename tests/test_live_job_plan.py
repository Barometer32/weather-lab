"""Unused station schedules stop reversibly before verified retirement."""
from configure_live_jobs import plan

PROJECT='weather-lab-261105-184200-1a9b'
ACCOUNT='weather-scheduler@'+PROJECT+'.iam.gserviceaccount.com'


def job(name,state='ENABLED'):
    return {'name':'projects/'+PROJECT+'/locations/us-central1/jobs/'+name,'state':state,'schedule':'1-59/5 * * * *','timeZone':'America/Chicago','attemptDeadline':'240s','httpTarget':{'uri':'https://old.example/collect/original','httpMethod':'POST','oidcToken':{'serviceAccountEmail':ACCOUNT,'audience':'https://old.example'}}}


def test_retired_jobs_pause_and_rollback_resumes_only_previously_enabled_jobs():
    jobs=[job('weather-live-rtmetar'),job('weather-live-mesonet','PAUSED'),
          job('weather-live-observation-stations'),job('weather-live-metar-clouds'),job('weather-live-radar')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert {tuple(c[3:5]) for c in configure if c[3]=='pause'}=={('pause','weather-live-rtmetar'),('pause','weather-live-observation-stations')}
    assert {tuple(c[3:5]) for c in rollback if c[3]=='resume'}=={('resume','weather-live-rtmetar'),('resume','weather-live-observation-stations')}
    assert not any(c[3:5]==['delete','weather-live-rtmetar'] for c in configure+rollback), 'Retired-job deletion waits for live verification'


def test_absent_or_already_paused_retired_jobs_need_no_mutations():
    jobs=[job('weather-live-metar-clouds'),job('weather-live-rtmetar','PAUSED')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert not any(c[3]=='pause' for c in configure)
    assert not any(c[3]=='resume' for c in rollback)


def test_create_and_seed_authenticated_five_minute_average_with_rollback():
    configure,rollback=plan([job('weather-live-metar-clouds')],PROJECT,'us-central1','https://collector.example')
    create=next(c for c in configure if c[3]=='create')
    assert create[4:6]==['http','weather-live-rapid-observations']
    for flag in ['--schedule=* * * * *','--attempt-deadline=300s','--http-method=POST','--uri=https://collector.example/collect/rapid-observations','--oidc-service-account-email='+ACCOUNT,'--oidc-token-audience=https://collector.example']:
        assert flag in create
    assert any(c[3:5]==['run','weather-live-rapid-observations'] for c in configure)
    assert any(c[3:5]==['delete','weather-live-rapid-observations'] for c in rollback)


def test_existing_paused_average_job_restores_original_schedule_target_and_state():
    configure,rollback=plan([job('weather-live-metar-clouds'),job('weather-live-rapid-observations','PAUSED')],PROJECT,'us-central1','https://collector.example')
    assert any(c[3:5]==['resume','weather-live-rapid-observations'] for c in configure)
    restore=next(c for c in rollback if c[3]=='update')
    for flag in ['--schedule=1-59/5 * * * *','--time-zone=America/Chicago','--attempt-deadline=240s','--uri=https://old.example/collect/original','--oidc-token-audience=https://old.example']:
        assert flag in restore
    assert any(c[3:5]==['pause','weather-live-rapid-observations'] for c in rollback)
