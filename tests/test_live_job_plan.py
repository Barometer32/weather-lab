"""Unused station schedules stop reversibly before verified retirement."""
from configure_live_jobs import plan

PROJECT='weather-lab-261105-184200-1a9b'
ACCOUNT='weather-scheduler@'+PROJECT+'.iam.gserviceaccount.com'


def job(name,state='ENABLED'):
    return {'name':'projects/'+PROJECT+'/locations/us-central1/jobs/'+name,'state':state,'schedule':'1-59/5 * * * *','timeZone':'America/Chicago','attemptDeadline':'240s','httpTarget':{'uri':'https://old.example/collect/original','httpMethod':'POST','oidcToken':{'serviceAccountEmail':ACCOUNT,'audience':'https://old.example'}}}


def test_retired_jobs_pause_and_rollback_resumes_only_previously_enabled_jobs():
    jobs=[job('weather-live-rtmetar'),job('weather-live-mesonet','PAUSED'),
          job('weather-live-observation-stations'),job('weather-live-rtma-observations'),job('weather-live-metar-clouds'),job('weather-live-radar')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert {tuple(c[3:5]) for c in configure if c[3]=='pause'}=={('pause','weather-live-rtmetar'),('pause','weather-live-observation-stations'),('pause','weather-live-rtma-observations')}
    assert {tuple(c[3:5]) for c in rollback if c[3]=='resume'}=={('resume','weather-live-rtmetar'),('resume','weather-live-observation-stations'),('resume','weather-live-rtma-observations')}
    assert not any(c[3:5]==['delete','weather-live-rtmetar'] for c in configure+rollback), 'Retired-job deletion waits for live verification'


def test_absent_or_already_paused_retired_jobs_need_no_mutations():
    jobs=[job('weather-live-metar-clouds'),job('weather-live-rtmetar','PAUSED'),job('weather-live-rtma-observations','PAUSED')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert not any(c[3]=='pause' for c in configure)
    assert not any(c[3]=='resume' for c in rollback)


def test_observations_jobs_pause_without_new_jobs_or_source_collection():
    jobs=[job('weather-live-metar-clouds'),job('weather-live-rapid-observations'),
          job('weather-live-hourly-observations','PAUSED'),job('weather-live-radar')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert [c[3:5] for c in configure]==[['pause','weather-live-rapid-observations']]
    assert [c[3:5] for c in rollback]==[['resume','weather-live-rapid-observations']]
    assert not any(c[3] in ('create','update','run','delete') for c in configure+rollback)


def test_absent_observation_jobs_create_nothing():
    assert plan([job('weather-live-metar-clouds')],PROJECT,'us-central1','https://collector.example')==([],[])


def test_retirement_script_deletes_only_existing_dedicated_jobs_after_validation(tmp_path):
    import json
    import runpy
    import shlex
    from pathlib import Path
    from unittest.mock import patch
    jobs=[job('weather-live-rapid-observations'),job('weather-live-hourly-observations','PAUSED'),
          job('weather-live-rtma-observations'),job('weather-live-metar-clouds'),job('weather-live-radar')]
    source=tmp_path/'jobs.json';source.write_text(json.dumps(jobs))
    script=str(Path(__file__).resolve().parents[1]/'configure_live_jobs.py')
    with patch('sys.argv',[script,'plan',str(source),str(tmp_path),PROJECT,'us-central1','https://collector.example']):
        runpy.run_path(script,run_name='__main__')
    commands=[shlex.split(line) for line in (tmp_path/'live-retire.sh').read_text().splitlines() if line.startswith('gcloud')]
    assert {c[4] for c in commands}=={'weather-live-rapid-observations','weather-live-hourly-observations','weather-live-rtma-observations'}
    assert all(c[:4]==['gcloud','scheduler','jobs','delete'] and '--quiet' in c for c in commands)
