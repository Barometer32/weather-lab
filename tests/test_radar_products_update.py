"""Exercise successful cutover and failed seed cleanup without cloud mutations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RadarUpdateTests(unittest.TestCase):
    def run_script(self, fail=False, paused=False):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work/'gcloud').write_text('''#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:]
with open(os.environ['MOCK_LOG'],'a') as out:out.write(json.dumps(args)+'\\n')
if args[:3]==['run','services','describe']:
 if '--format=value(status.url)' in args:print('https://example.run.app')
 else:print(json.dumps({'spec':{'template':{'spec':{'serviceAccountName':'collector@example.iam.gserviceaccount.com','containers':[{'image':'us-central1-docker.pkg.dev/weather-lab-test/weather-lab/app:before','env':[{'name':'WEATHER_DATA_BUCKET','value':'weather-lab-test-weather-data'}]}]}}}}))
elif args[:3]==['scheduler','jobs','describe']:print(json.dumps({'state':os.environ['MOCK_STATE']}))
elif args[:3]==['run','jobs','execute'] and os.environ['MOCK_FAIL']=='1':sys.exit(1)
''')
            (work/'git').write_text('''#!/usr/bin/env python3
import sys,pathlib
if sys.argv[1]=='clone':
 p=pathlib.Path(sys.argv[-1]);p.mkdir();(p/'verify_radar_products.py').write_text('print("Verified mock cutover")')
elif sys.argv[-2:]==['rev-parse','HEAD']:print('a'*40)
''')
            for name in ('gcloud', 'git'):
                (work/name).chmod(0o755)
            env = {**os.environ, 'PATH':str(work)+os.pathsep+os.environ['PATH'], 'HOME':str(work),
                   'MOCK_LOG':str(work/'calls'), 'MOCK_FAIL':str(int(fail)), 'MOCK_STATE':'PAUSED' if paused else 'ENABLED'}
            result = subprocess.run(['bash', str(ROOT/'update-weather-radar-products.sh'), 'weather-lab-test'], env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in (work/'calls').read_text().splitlines()]
            return result, calls

    def test_prepares_before_publishing_and_only_changes_service_images(self):
        result, calls = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        seed = next(i for i, c in enumerate(calls) if c[:3] == ['run','jobs','execute'])
        updates = [(i,c) for i,c in enumerate(calls) if c[:3] == ['run','services','update']]
        self.assertEqual(len(updates), 2)
        for index, call in updates:
            self.assertGreater(index, seed)
            self.assertFalse(any(x.startswith(('--set-env','--memory','--min','--max','--service-account')) for x in call))
        self.assertTrue(any(c[:3] == ['scheduler','jobs','resume'] for c in calls))

    def test_failed_seed_resumes_collection_without_publishing(self):
        result, calls = self.run_script(fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c[:3] == ['run','services','update'] for c in calls))
        self.assertTrue(any(c[:3] == ['scheduler','jobs','resume'] for c in calls))

    def test_already_paused_schedule_is_left_paused(self):
        result, calls = self.run_script(paused=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertFalse(any(c[:2] == ['scheduler','jobs'] and c[2] in ('pause','resume') for c in calls))
