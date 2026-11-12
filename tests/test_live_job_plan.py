"""Unused station schedules stop reversibly before verified retirement."""
from configure_live_jobs import plan

PROJECT='weather-lab-261105-184200-1a9b'


def job(name,state='ENABLED'):
    return {'name':'projects/'+PROJECT+'/locations/us-central1/jobs/'+name,'state':state}


def test_retired_jobs_pause_and_rollback_resumes_only_previously_enabled_jobs():
    jobs=[job('weather-live-rtmetar'),job('weather-live-mesonet','PAUSED'),
          job('weather-live-observation-stations'),job('weather-live-metar-clouds'),job('weather-live-radar')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert {tuple(c[3:5]) for c in configure}=={('pause','weather-live-rtmetar'),('pause','weather-live-observation-stations')}
    assert {tuple(c[3:5]) for c in rollback}=={('resume','weather-live-rtmetar'),('resume','weather-live-observation-stations')}
    assert not any(c[3]=='delete' for c in configure+rollback), 'Deletion waits for live verification'


def test_absent_or_already_paused_retired_jobs_need_no_mutations():
    jobs=[job('weather-live-metar-clouds'),job('weather-live-rtmetar','PAUSED')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert configure==rollback==[]
