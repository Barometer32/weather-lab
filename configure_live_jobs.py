"""Configure schedules used by the current Weather Lab site."""
import subprocess
from cleanup_weather_jobs import ACCOUNT, PROJECT, REGION, REQUIRED, jobs, owned, service

def plan(rows, collector):
    indexed = {row['name'].split('/')[-1]: row for row in rows}
    commands = []
    common = ['--project='+PROJECT, '--location='+REGION]
    for name, endpoint in REQUIRED.items():
        old = indexed.get(name)
        if old:
            if not owned(old, collector) or old['httpTarget']['uri'] != collector+'/collect/'+endpoint:
                raise ValueError('Unexpected target for required schedule: '+name)
            if old.get('state') not in ('ENABLED','PAUSED'):
                raise ValueError('Unexpected schedule state: '+name)
            schedule = {'weather-live-metar-clouds':'*/2 * * * *',
                        'weather-live-forecast':'*/5 * * * *',
                        'weather-live-hrmetar':'*/3 * * * *'}.get(name)
            if schedule and old['schedule'] != schedule:
                commands.append(['gcloud','scheduler','jobs','update','http',name,*common,'--schedule='+schedule])
            if old['state'] == 'PAUSED':
                commands.append(['gcloud','scheduler','jobs','resume',name,*common])
        elif name == 'weather-live-hrmetar':
            commands.append(['gcloud', 'scheduler', 'jobs', 'create', 'http', name, *common,
                             '--schedule=*/3 * * * *', '--time-zone=Etc/UTC', '--http-method=POST',
                             '--uri='+collector+'/collect/'+endpoint, '--oidc-service-account-email='+ACCOUNT,
                             '--oidc-token-audience='+collector, '--attempt-deadline=120s'])
        else:
            raise ValueError('Required schedule is missing: '+name)
    return commands


if __name__ == '__main__':
    for command in plan(jobs(), service('weather-collector')):
        subprocess.run(command, check=True)
