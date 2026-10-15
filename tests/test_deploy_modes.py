"""Exercise deployment control flow with command stubs; no cloud calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUB = '''import json, os, sys
from pathlib import Path
args=sys.argv[1:]
tool=Path(sys.argv[0]).name
with open(os.environ['WEATHER_TEST_COMMAND_LOG'],'a') as log:
    log.write(json.dumps([tool,*args])+"\\n")
if tool=='docker':
    if args and args[0]=='push' and os.environ.get('WEATHER_TEST_FAIL_PUSH')=='1':
        sys.exit(1)
    sys.exit(0)
if args[:2]==['projects','describe']:
    print('ACTIVE')
elif args[:3]==['billing','projects','describe']:
    print('True')
elif args[:3]==['scheduler','jobs','describe']:
    if args[3] in ('weather-hourly','weather-live-radar-KEVX','weather-live-observations','weather-live-surface','weather-live-metar-clouds'):
        sys.exit(1)
    print('ENABLED')
elif args[:3]==['run','jobs','describe']:
    sys.exit(1)
elif args[:3]==['storage','objects','describe']:
    sys.exit(1)
elif args[:3]==['storage','buckets','describe'] and args[3].endswith('-forecast'):
    sys.exit(1)
elif args[:3]==['run','services','describe']:
    print('https://weather-collector.example.invalid')
'''


class DeploymentModeTests(unittest.TestCase):
    def run_deploy(self, mode, fail_push=False):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            for tool in ('gcloud','docker'):
                executable=directory/tool
                executable.write_text('#!'+sys.executable+'\n'+STUB)
                executable.chmod(0o755)
            log=directory/'commands.jsonl'
            env={**os.environ,'PATH':str(directory)+os.pathsep+os.environ['PATH'],
                 'WEATHER_BUILD_MODE':mode,'WEATHER_ARTIFACT_REPOSITORY':'weather-test-images',
                 'WEATHER_TEST_COMMAND_LOG':str(log),'WEATHER_TEST_FAIL_PUSH':'1' if fail_push else '0'}
            result=subprocess.run(['bash','deploy.sh','weather-test-project'],cwd=ROOT,env=env,
                                  text=True,capture_output=True,timeout=20)
            commands=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result,commands

    def test_cloud_shell_build_pushes_before_either_service_deploys_and_skips_cloud_build(self):
        result,commands=self.run_deploy('docker')
        self.assertEqual(result.returncode,0,result.stderr)
        push=next(i for i,c in enumerate(commands) if c[:2]==['docker','push'])
        deploys=[i for i,c in enumerate(commands) if c[:3]==['gcloud','run','deploy']]
        self.assertEqual(len(deploys),2)
        self.assertTrue(all(i>push for i in deploys))
        self.assertFalse(any(c[:3]==['gcloud','builds','submit'] for c in commands))
        self.assertFalse(any('weather-builder@' in ' '.join(c) for c in commands))
        enable=next(c for c in commands if c[:3]==['gcloud','services','enable'])
        self.assertNotIn('cloudbuild.googleapis.com',enable)
        self.assertIn(['gcloud','auth','configure-docker','us-central1-docker.pkg.dev','--quiet'],commands)

    def test_failed_push_cannot_replace_either_running_service(self):
        result,commands=self.run_deploy('docker',fail_push=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[:3]==['gcloud','run','deploy'] for c in commands))

    def test_cloud_build_mode_keeps_existing_submission_workflow(self):
        result,commands=self.run_deploy('cloudbuild')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(any(c[:3]==['gcloud','builds','submit'] for c in commands))
        self.assertFalse(any(c[0]=='docker' for c in commands))

    def test_invalid_mode_stops_before_any_cloud_commands(self):
        result,commands=self.run_deploy('invalid')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(commands,[])


if __name__=='__main__':unittest.main()
