from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
import unittest
from unittest.mock import Mock, patch

import build_access

PROJECT='weather-metar-261016-114317'
CALLER='deployer@example.com'


class BuildAccessTests(unittest.TestCase):
    def test_all_permissions_return_success_without_exposing_token(self):
        output=StringIO()
        with redirect_stdout(output):
            ok=build_access.inspect_access(PROJECT,CALLER,'PRIVATE-TOKEN',check=lambda u,p,t:set(p))
        self.assertTrue(ok)
        self.assertNotIn('PRIVATE-TOKEN',output.getvalue())
        self.assertEqual(output.getvalue().count('ALLOWED'),6)

    def test_missing_builder_actas_reports_exact_resource_and_changes_nothing(self):
        output=StringIO()
        with redirect_stdout(output),patch('subprocess.run') as mutate:
            ok=build_access.inspect_access(PROJECT,CALLER,'test-token',check=lambda u,p,t:set() if 'weather-builder@' in u else set(p))
        self.assertFalse(ok)
        self.assertIn('iam.serviceAccounts.actAs on weather-builder',output.getvalue())
        self.assertIn('No IAM changes made',output.getvalue())
        mutate.assert_not_called()

    def test_missing_project_access_is_distinguished_from_service_account_access(self):
        output=StringIO()
        with redirect_stdout(output):
            ok=build_access.inspect_access(PROJECT,CALLER,'test-token',check=lambda u,p,t:set(p)-{'cloudbuild.builds.create'})
        self.assertFalse(ok)
        self.assertIn('project: cloudbuild.builds.create: MISSING',output.getvalue())
        self.assertEqual(output.getvalue().count('MISSING'),1)

    def test_only_test_permission_endpoints_are_called(self):
        check=Mock(side_effect=lambda url,permissions,token:set(permissions))
        with redirect_stdout(StringIO()):build_access.inspect_access(PROJECT,CALLER,'test-token',check=check)
        self.assertEqual(check.call_count,5)
        self.assertTrue(all(c.args[0].endswith(':testIamPermissions') for c in check.call_args_list))

    def test_invalid_api_response_is_not_interpreted_as_missing_permissions(self):
        response=Mock();response.__enter__=Mock(return_value=BytesIO(json.dumps({'error':'bad response'}).encode()));response.__exit__=Mock()
        with patch('build_access.urlopen',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'Unexpected permission-check response'):
                build_access.test_permissions('https://iam.googleapis.com/test',['iam.serviceAccounts.actAs'],'test-token')


if __name__=='__main__':unittest.main()
