from configure_live_jobs import plan

PROJECT='weather-lab-261105-184200-1a9b'
ACCOUNT='weather-scheduler@'+PROJECT+'.iam.gserviceaccount.com'


def job(name,state='ENABLED'):
    return {'name':'projects/'+PROJECT+'/locations/us-central1/jobs/'+name,'state':state,
            'schedule':'1-59/5 * * * *','timeZone':'America/Chicago','attemptDeadline':'240s',
            'httpTarget':{'uri':'https://old.example/collect/original','httpMethod':'POST',
                          'oidcToken':{'serviceAccountEmail':ACCOUNT,'audience':'https://old.example'}}}


def test_live_jobs_created_seeded_and_rollback_removes_only_new_jobs():
    configure,rollback=plan([job('weather-live-metar-clouds')],PROJECT,'us-central1','https://collector.example')
    for name,kind in [('weather-live-mesonet','mesonet')]:
        create=next(c for c in configure if c[3:6]==['create','http',name])
        assert '--schedule=*/5 * * * *' in create and '--attempt-deadline=300s' in create
        assert '--uri=https://collector.example/collect/'+kind in create
        assert '--oidc-token-audience=https://collector.example' in create
        assert any(c[3:5]==['run',name] for c in configure)
        assert any(c[3:5]==['delete',name] for c in rollback)


def test_live_jobs_update_and_restore_original_auth_target_schedule_and_paused_state():
    jobs=[job('weather-live-metar-clouds'),job('weather-live-rtmetar','PAUSED'),job('weather-live-mesonet')]
    configure,rollback=plan(jobs,PROJECT,'us-central1','https://collector.example')
    assert not any(c[3]=='delete' for c in rollback)
    assert not any('weather-live-rtmetar' in c for c in configure+rollback), 'Retired paused job stays paused until final retirement'
    for name in ['weather-live-mesonet']:
        restored=next(c for c in rollback if c[3:6]==['update','http',name])
        for flag in ['--schedule=1-59/5 * * * *','--time-zone=America/Chicago','--attempt-deadline=240s',
                     '--uri=https://old.example/collect/original','--oidc-token-audience=https://old.example']:
            assert flag in restored


def test_retired_enabled_rtmetar_is_paused_but_remains_recoverable_before_cutover():
    configure,rollback=plan([job('weather-live-metar-clouds'),job('weather-live-rtmetar')],PROJECT,'us-central1','https://collector.example')
    assert configure[0][3:5]==['pause','weather-live-rtmetar']
    assert any(c[3:5]==['resume','weather-live-rtmetar'] for c in rollback)
    assert not any(c[3:5]==['delete','weather-live-rtmetar'] for c in configure+rollback)
    assert not any(c[3:5]==['run','weather-live-rtmetar'] for c in configure)
