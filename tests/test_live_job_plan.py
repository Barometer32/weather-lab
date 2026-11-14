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


def test_old_observations_jobs_pause_and_only_new_rtma_collector_is_started():
    jobs=[job('weather-live-metar-clouds'),job('weather-live-rapid-observations'),
          job('weather-live-hourly-observations','PAUSED'),job('weather-live-radar')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert [c[3:5] for c in configure if c[3]=='pause']==[['pause','weather-live-rapid-observations']]
    assert [c[3:5] for c in rollback if c[3]=='resume']==[['resume','weather-live-rapid-observations']]
    assert all('weather-live-rtma-observations' in c for c in configure+rollback if c[3] in ('create','update','run','delete'))


def test_new_rtma_job_checks_every_minute_and_rollback_deletes_only_that_job():
    configure,rollback=plan([job('weather-live-metar-clouds')],PROJECT,'us-central1','https://collector.example')
    create=configure[0]
    assert create[3:6]==['create','http','weather-live-rtma-observations']
    assert '--schedule=* * * * *' in create and '--max-retry-attempts=0' in create
    assert '--uri=https://collector.example/collect/rtma-observations' in create
    assert '--oidc-service-account-email='+ACCOUNT in create
    assert configure[-1][3:5]==['run','weather-live-rtma-observations']
    assert [c[3:5] for c in rollback]==[['delete','weather-live-rtma-observations']]


def test_existing_rtma_job_restores_previous_uri_schedule_and_paused_state():
    configure,rollback=plan([job('weather-live-rtma-observations','PAUSED')],PROJECT,'us-central1','https://collector.example')
    assert configure[0][3]=='update'
    assert ['resume','weather-live-rtma-observations'] in [c[3:5] for c in configure]
    assert '--uri=https://old.example/collect/original' in rollback[0]
    assert '--schedule=1-59/5 * * * *' in rollback[0]
    assert '--attempt-deadline=240s' in rollback[0]
    assert rollback[-1][3:5]==['pause','weather-live-rtma-observations']


def test_retirement_script_deletes_only_existing_dedicated_jobs_after_validation(tmp_path):
    import json
    import runpy
    import shlex
    from pathlib import Path
    from unittest.mock import patch
    jobs=[job('weather-live-rapid-observations'),job('weather-live-hourly-observations','PAUSED'),
          job('weather-live-metar-clouds'),job('weather-live-radar')]
    source=tmp_path/'jobs.json';source.write_text(json.dumps(jobs))
    script=str(Path(__file__).resolve().parents[1]/'configure_live_jobs.py')
    with patch('sys.argv',[script,'plan',str(source),str(tmp_path),PROJECT,'us-central1','https://collector.example']):
        runpy.run_path(script,run_name='__main__')
    commands=[shlex.split(line) for line in (tmp_path/'live-retire.sh').read_text().splitlines() if line.startswith('gcloud')]
    assert {c[4] for c in commands}=={'weather-live-rapid-observations','weather-live-hourly-observations'}
    assert all(c[:4]==['gcloud','scheduler','jobs','delete'] and '--quiet' in c for c in commands)
