"""Read-only checks of the signed-in deployer's effective Google Cloud access."""
import argparse
import json
import re
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def test_permissions(url, permissions, token):
    request = Request(url, json.dumps({'permissions': permissions}).encode(),
                      {'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=30) as response:
            document = json.load(response)
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get('error', {}).get('message', '')
        except (ValueError, AttributeError):
            detail = error.reason
        raise RuntimeError(f'Permission check returned HTTP {error.code}: {str(detail)[:2000]}') from None
    if (not isinstance(document, dict) or set(document)-{'permissions'}
            or not isinstance(document.get('permissions', []), list)):
        raise RuntimeError('Unexpected permission-check response; no IAM changes made')
    return set(document.get('permissions', []))


def inspect_access(project, caller, token, *, check=test_permissions):
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', project):
        raise ValueError('Invalid project ID')
    if not caller or caller == '(unset)':
        raise ValueError('No active Google Cloud account')
    print(f'Account: {caller}\nProject: {project}', flush=True)
    project_url = f'https://cloudresourcemanager.googleapis.com/v1/projects/{project}:testIamPermissions'
    targets = [(project_url, 'project', ['cloudbuild.builds.create', 'serviceusage.services.use'])]
    for name in ('weather-builder', 'weather-web', 'weather-collector', 'weather-scheduler'):
        account = f'{name}@{project}.iam.gserviceaccount.com'
        url = f'https://iam.googleapis.com/v1/projects/{project}/serviceAccounts/{account}:testIamPermissions'
        targets.append((url, name, ['iam.serviceAccounts.actAs']))
    missing = []
    for url, label, permissions in targets:
        granted = check(url, permissions, token)
        for permission in permissions:
            allowed = permission in granted
            print(f'{label}: {permission}: {"ALLOWED" if allowed else "MISSING"}', flush=True)
            if not allowed:
                missing.append(f'{permission} on {label}')
    if missing:
        print('Missing access: '+', '.join(missing)+'. No IAM changes made; no build submitted.', flush=True)
        return False
    print('Deployer permissions verified. No IAM changes made.', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project')
    args = parser.parse_args()
    caller = subprocess.check_output(['gcloud', 'config', 'get-value', 'account'], text=True).strip()
    # The short-lived token stays in memory and is never printed or saved.
    token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()
    return 0 if inspect_access(args.project, caller, token) else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
