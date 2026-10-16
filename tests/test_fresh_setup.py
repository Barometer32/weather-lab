"""Run the real installer with stubbed Google/Docker commands, never cloud mutations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

FAKE_GCLOUD='''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
p=pathlib.Path(os.environ['WEATHER_FAKE_DIR'])
with (p/'calls').open('a') as out:out.write(json.dumps(args)+'\\n')
if args[:4]==['billing','accounts','describe','TEST-ACCOUNT']:
 print(os.environ.get('WEATHER_FAKE_BILLING_OPEN','true'));sys.exit(0)
if args[:2]==['projects','describe']:
 if not (p/'project').exists():sys.exit(1)
 print('ACTIVE' if 'value(lifecycleState)' in ' '.join(args) else args[2]);sys.exit(0)
if args[:2]==['projects','create']:(p/'project').write_text(args[2])
if args[:3]==['billing','projects','describe']:print('true')
if args[:3]==['artifacts','repositories','describe']:sys.exit(0 if (p/'repository').exists() else 1)
if args[:3]==['artifacts','repositories','create']:
 if not (p/'repo-first-try').exists():(p/'repo-first-try').touch();sys.exit(1)
 (p/'repository').touch()
if args[:3]==['run','services','describe']:print('https://weather-test.example.run.app')
if args[:3]==['scheduler','jobs','describe']:
 if not (p/'stations-state').exists():sys.exit(1)
 print((p/'stations-state').read_text())
if args[:4] in (['scheduler','jobs','create','http'],['scheduler','jobs','update','http']) and 'weather-live-stations' in args:
 (p/'stations-state').write_text('ENABLED')
if args[:4]==['scheduler','jobs','pause','weather-live-stations']:(p/'stations-state').write_text('PAUSED')
if args[:4]==['scheduler','jobs','resume','weather-live-stations']:(p/'stations-state').write_text('ENABLED')
if args[:2]==['builds','submit'] and os.environ.get('WEATHER_FAKE_BUILD_FAIL')=='1':sys.exit(1)
if args[:4]==['run','jobs','execute','weather-metar-backfill'] and os.environ.get('WEATHER_FAKE_IMPORT_FAIL')=='1':sys.exit(1)
'''


class FreshSetupTests(unittest.TestCase):
    def run_setup(self, directory, **extra):
        folder=Path(directory)
        for name,content in [('gcloud',FAKE_GCLOUD),('docker','#!/bin/sh\necho docker >> "$WEATHER_FAKE_DIR/docker-calls"\nexit 0\n'),('sleep','#!/bin/sh\nexit 0\n')]:
            f=folder/name;f.write_text(content);f.chmod(0o755)
        env={**os.environ,'PATH':str(folder)+os.pathsep+os.environ['PATH'],
             'WEATHER_FAKE_DIR':str(folder),'WEATHER_BILLING_ACCOUNT':'TEST-ACCOUNT',
             'WEATHER_STATE_FILE':str(folder/'project-id'),'WEATHER_BUILD_MODE':'cloudbuild',**extra}
        env.pop('WEATHER_PROJECT',None)
        result=subprocess.run(['bash','start-fresh.sh'],cwd=ROOT,env=env,text=True,capture_output=True,timeout=30)
        calls=[json.loads(l) for l in (folder/'calls').read_text().splitlines()]
        return result,calls

    def test_fresh_project_links_billing_retries_repository_backfills_and_rerun_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.run_setup(directory)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            creates=[c for c in calls if c[:2]==['projects','create']]
            self.assertEqual(len(creates),1)
            project=creates[0][2]
            self.assertTrue(project.startswith('weather-metar-'))
            self.assertLessEqual(len(project),30)
            self.assertTrue(any(c[:3]==['billing','projects','link'] and project in c for c in calls))
            self.assertEqual(sum(c[:3]==['artifacts','repositories','create'] for c in calls),2)
            station=[c for c in calls if c[:3]==['scheduler','jobs','create'] and 'weather-live-stations' in c][0]
            self.assertIn('--schedule=5 * * * *',station)
            job_index=next(i for i,c in enumerate(calls) if c[:3]==['run','jobs','execute'])
            self.assertTrue(any(c[:3]==['scheduler','jobs','pause'] for c in calls[:job_index]))
            self.assertTrue(any(c[:3]==['scheduler','jobs','resume'] for c in calls[job_index+1:]))
            result,calls=self.run_setup(directory)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(sum(c[:2]==['projects','create'] for c in calls),1)
            self.assertEqual((Path(directory)/'project-id').read_text().strip(),project)

    def test_cloudbuild_does_not_use_cloud_shell_docker_and_configures_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.run_setup(directory)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertFalse((Path(directory)/'docker-calls').exists())
            build=next(c for c in calls if c[:2]==['builds','submit'])
            self.assertIn('--default-buckets-behavior=regional-user-owned-bucket',build)
            self.assertTrue(any(c.startswith('--service-account=projects/weather-metar-') and '/serviceAccounts/weather-builder@' in c for c in build))
            self.assertTrue(any('--service=cloudbuild.googleapis.com' in c for c in calls))
            self.assertTrue(any('--role=roles/cloudbuild.builds.builder' in c for c in calls))

    def test_failed_build_does_not_resume_or_run_nonexistent_scheduler_job(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.run_setup(directory,WEATHER_FAKE_BUILD_FAIL='1')
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(any(c[:3] in (['scheduler','jobs','resume'],['scheduler','jobs','run']) for c in calls))
            self.assertFalse(any(c[:2]==['run','deploy'] for c in calls))

    def test_closed_billing_stops_before_project_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.run_setup(directory,WEATHER_FAKE_BILLING_OPEN='false')
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(any(c[:2]==['projects','create'] for c in calls))

    def test_failed_import_resumes_hourly_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.run_setup(directory,WEATHER_FAKE_IMPORT_FAIL='1')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('12-hour METAR import did not finish',result.stderr)
            self.assertTrue(any(c[:3]==['scheduler','jobs','resume'] for c in calls))
            self.assertEqual(calls[-1][:4],['scheduler','jobs','run','weather-live-stations'])


if __name__=='__main__':unittest.main()
