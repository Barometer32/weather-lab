"""The optional trainer runs once with bounded resources and no IAM grants."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class TrainingJobTests(unittest.TestCase):
    def run_script(self,folder,fail=False):
        folder=Path(folder)
        (folder/'gcloud').write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
with (pathlib.Path(os.environ['AI_TEST_DIR'])/'calls').open('a') as f:f.write(json.dumps(args)+'\\n')
if args[:3]==['run','jobs','execute'] and os.environ.get('AI_FAIL')=='1':sys.exit(1)
''')
        (folder/'python3').write_text('#!/bin/sh\nif [ "$1" = build_access.py ]; then exit 0; fi\nexec '+shlex.quote(sys.executable)+' "$@"\n')
        for name in ('gcloud','python3'):(folder/name).chmod(0o755)
        result=subprocess.run(['bash','train-ai.sh','weather-metar-test'],cwd=ROOT,
            env={**os.environ,'PATH':str(folder)+os.pathsep+os.environ['PATH'],'AI_TEST_DIR':str(folder),'AI_FAIL':str(int(fail))},
            text=True,capture_output=True,timeout=15)
        import json
        calls=[json.loads(s) for s in (folder/'calls').read_text().splitlines()]
        return result,calls

    def test_success_runs_one_bounded_training_task_then_requests_map_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            result,calls=self.run_script(folder)
        self.assertEqual(result.returncode,0,result.stderr)
        deploy=next(c for c in calls if c[:3]==['run','jobs','deploy'])
        for flag in ('--cpu=4','--memory=8Gi','--tasks=1','--parallelism=1','--max-retries=0','--task-timeout=1800s'):
            self.assertIn(flag,deploy)
        self.assertEqual(sum(c[:3]==['run','jobs','execute'] for c in calls),1)
        self.assertEqual(calls[-1][:4],['scheduler','jobs','run','weather-live-stations'])
        self.assertFalse(any('add-iam-policy-binding' in c for c in calls))

    def test_failed_training_does_not_claim_success_or_trigger_new_forecasts(self):
        with tempfile.TemporaryDirectory() as folder:
            result,calls=self.run_script(folder,True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[:3]==['scheduler','jobs','run'] for c in calls))
        self.assertNotIn('Training finished.',result.stdout)


if __name__=='__main__':unittest.main()
