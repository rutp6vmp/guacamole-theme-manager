#!/usr/bin/env python3
"""P00/G03/G04 and early P01 against official Guacamole 1.6.0.

Creates only a random localhost-only Compose project with a disposable database.
Seeds, passwords, tokens and complete HTTP/Docker responses never leave memory
or the private temporary fixture. No production deployment is inspected.
"""
import base64
import hashlib
import hmac
import json
import secrets
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from docker_acceptance import ROOT, fixture_directory, run
from seed import seed


class AcceptanceFailure(Exception):
    pass


class Client:
    def __init__(self, url):
        self.url = url
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, method='GET', data=None, token=None, form=False):
        headers = {}
        if token:
            headers['Guacamole-Token'] = token
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
            data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
        request = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=10)
        except urllib.error.HTTPError as failure:
            response = failure
        with response:
            raw = response.read(1024 * 1024)
            return response.code, json.loads(raw) if raw else None

    def login(self, user, password, code=None):
        data = {'username': user, 'password': password}
        if code is not None:
            data['guac-totp'] = code
        return self.request('api/tokens', 'POST', data, form=True)


def totp(secret):
    key = base64.b32decode(secret, casefold=True)
    value = hmac.new(key, struct.pack('>Q', int(time.time()) // 30), hashlib.sha1).digest()
    offset = value[-1] & 15
    return str((struct.unpack('>I', value[offset:offset+4])[0] & 0x7fffffff) % 1000000).zfill(6)


def safe_result(status, body):
    """Diagnostics restricted to HTTP status and known protocol enums."""
    kind = (body or {}).get('type')
    if kind not in {'INSUFFICIENT_CREDENTIALS', 'INVALID_CREDENTIALS', 'PERMISSION_DENIED', 'BAD_REQUEST', 'INTERNAL_ERROR'}:
        kind = 'other'
    key = ((body or {}).get('translatableMessage') or {}).get('key')
    if key not in {'TOTP.INFO_VERIFICATION_FAILED', 'TOTP.INFO_ENROLL_REQUIRED', 'TOTP.INFO_CODE_REQUIRED'}:
        key = 'other'
    return ' (HTTP ' + str(status) + ', ' + kind + ', ' + key + ')'


def main(gate_runner=None, fixture_setup=None):
    results = []

    def check(condition, name, details=''):
        if not condition:
            raise AcceptanceFailure(name + details)
        results.append(name)

    project = 'gtm-pam-test-' + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    with fixture_directory(project + '-') as base:
        ext = base / 'extensions'; ext.mkdir(mode=0o755)
        recordings = base / 'recordings'; recordings.mkdir(mode=0o755)
        init = base / 'init'; init.mkdir(mode=0o755)
        schema = run(['docker', 'run', '--rm', '--entrypoint', '/opt/guacamole/bin/initdb.sh',
                      'guacamole/guacamole:1.6.0', '--postgresql'])
        (init / '001.sql').write_bytes(schema)
        (init / '002.sql').write_text(seed(password))
        for path in init.iterdir():
            path.chmod(0o644)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        url = 'http://127.0.0.1:' + str(port) + '/guacamole/'
        config = {'name': project, 'services': {
            'db': {'image': 'postgres:16', 'environment': {'POSTGRES_DB': 'gtmtest', 'POSTGRES_USER': 'gtmtest', 'POSTGRES_PASSWORD': password},
                   'tmpfs': ['/var/lib/postgresql/data'],
                   'volumes': [{'type': 'bind', 'source': str(init), 'target': '/docker-entrypoint-initdb.d', 'read_only': True}],
                   'healthcheck': {'test': ['CMD', 'pg_isready', '-U', 'gtmtest', '-d', 'gtmtest'], 'interval': '2s', 'timeout': '3s', 'retries': 30}},
            'guacd': {'image': 'guacamole/guacd:1.6.0',
                      'healthcheck': {'test': ['CMD-SHELL', 'nc -z 127.0.0.1 4822 || exit 1'],
                                      'interval': '2s', 'timeout': '5s', 'start_period': '2s', 'retries': 30}},
            'web': {'image': 'guacamole/guacamole:1.6.0',
                    'depends_on': {'db': {'condition': 'service_healthy'}, 'guacd': {'condition': 'service_started'}},
                    'ports': [{'target': 8080, 'published': str(port), 'host_ip': '127.0.0.1'}],
                    'environment': {'GUACD_HOSTNAME': 'guacd', 'POSTGRESQL_ENABLED': 'true', 'POSTGRESQL_HOSTNAME': 'db',
                                    'POSTGRESQL_DATABASE': 'gtmtest', 'POSTGRESQL_USERNAME': 'gtmtest', 'POSTGRESQL_PASSWORD': password},
                    'volumes': [{'type': 'bind', 'source': str(ext), 'target': '/etc/guacamole/extensions', 'read_only': True}]}}}
        if fixture_setup is not None:
            fixture_setup(base, config, password)
        compose = base / 'compose.json'; compose.write_text(json.dumps(config)); compose.chmod(0o600)
        overlay = base / 'security.json'
        overlay.write_text(json.dumps({'services': {'web': {
            'environment': {'TOTP_ENABLED': 'true', 'RECORDING_ENABLED': 'true'},
            'volumes': [{'type': 'bind', 'source': str(recordings), 'target': '/var/lib/guacamole/recordings', 'read_only': True}]}}}))
        overlay.chmod(0o600)
        command = ['docker', 'compose', '-f', str(compose), '--project-name', project]
        secured = ['docker', 'compose', '-f', str(compose), '-f', str(overlay), '--project-name', project]
        cli = [sys.executable, str(ROOT / 'bin/guac-theme'), '--state-dir', str(base / 'state')]
        client = Client(url)

        def challenge(user, enrolled=False):
            status, body = client.login(user, password)
            check(status == 403 and body.get('type') == 'INSUFFICIENT_CREDENTIALS' and 'authToken' not in body,
                  user + ': password alone cannot authenticate')
            fields = [f for f in body.get('expected', []) if f.get('name') == 'guac-totp']
            check(len(fields) == 1, user + ': native TOTP challenge')
            if enrolled:
                check(not fields[0].get('secret'), user + ': enrolled seed not disclosed')
            return fields[0].get('secret')

        def enroll(user, negative_tests=False):
            key = challenge(user)
            check(bool(key), user + ': enrollment available')
            # Keep deliberate failures below the official Docker image's
            # default IP-ban threshold; retain the default brute-force guard.
            if negative_tests:
                status, body = client.login(user, password, 'invalid-code')
                check(status != 200 and 'authToken' not in body, user + ': wrong OTP denied')
            code = totp(key)
            status, body = client.login(user, password, code)
            check(status == 200 and bool(body.get('authToken')), user + ': real OTP enrollment succeeded')
            token = body['authToken']
            if negative_tests:
                status, body = client.login(user, password, code)
                check(status != 200 and 'authToken' not in body, user + ': OTP replay denied within running instance')
            challenge(user, enrolled=True)
            return key, token

        try:
            print('Starting isolated PAM acceptance: ' + project, flush=True)
            run(command + ['up', '-d', '--wait', '--wait-timeout', '180'])
            run(cli + ['configure', '--extensions-dir', str(ext), '--compose-file', str(compose),
                       '--project-name', project, '--service', 'web', '--web-url', url, '--timeout', '90'])
            run(cli + ['doctor'])
            if gate_runner is not None:
                gate_runner(base, command, cli, url, client, ext, password)
                return
            for name in ['librenms', 'dark']:
                run(cli + ['import', str(ROOT / ('dist/guac-theme-' + name + '-1.1.0.zip'))])
            run(cli + ['install', 'librenms', '--yes', '--trust-theme'])
            backup = run(cli + ['backup']).decode().strip()
            original_ids = [run(command + ['ps', '--quiet', s]).strip() for s in ['db', 'guacd']]
            # Enable official modules ONLY in this new disposable installation.
            run(secured + ['up', '-d', '--no-deps', '--force-recreate', '--pull', 'never', '--no-build', 'web'])
            old_theme = (ext / 'guac-theme-managed.jar').read_bytes()
            refused = subprocess.run(cli + ['reset', '--yes'], capture_output=True, timeout=120)
            check(refused.returncode != 0 and b'Runtime Compose file list differs' in refused.stderr,
                  'missing live security overlay refused before recreation')
            check((ext / 'guac-theme-managed.jar').read_bytes() == old_theme, 'refused reset preserves theme bytes')
            run(cli + ['protect-deployment', '--compose-file', str(compose), '--compose-file', str(overlay),
                       '--require-feature', 'totp', '--require-feature', 'recording'])
            print('Official TOTP and recording-storage modules loaded; testing authentication and permissions.', flush=True)
            reader_key, reader = enroll('gtm-reader', negative_tests=True)
            _, admin = enroll('gtm-admin')
            root = 'api/session/data/postgresql/'
            status, body = client.request(root + 'connections/1', token=reader)
            check(status == 200, 'READ-only operator can retrieve an authorized asset')
            status, body = client.request(root + 'connections/1/parameters', token=reader)
            check(status == 403, 'READ-only operator cannot retrieve target parameters')
            status, body = client.request(root + 'connections/5', token=reader)
            check(status in (403, 404), 'hidden asset inaccessible via direct API')
            status, body = client.request(root + 'users/gtm-admin', token=reader)
            check(status in (403, 404), 'operator cannot retrieve another user')
            status, body = client.request(root + 'users/gtm-reader', token=reader)
            check(status in (200, 403, 404), 'own user resource uses normal authorization (HTTP ' + str(status) + ')')
            if status == 200:
                check('guac-totp-key-secret' not in body.get('attributes', {}), 'own user API hides seed')
            else:
                check(True, 'own user API inaccessible without user READ permission (HTTP ' + str(status) + ')')
            own = {'username': 'gtm-reader', 'attributes': {'guac-totp-disabled': 'true'}}
            status, body = client.request(root + 'users/gtm-reader', 'PUT', own, token=reader)
            check(status in (403, 404), 'operator cannot self-disable MFA through native API (HTTP ' + str(status) + ')')
            status, body = client.request(root + 'users/gtm-reader', token=admin)
            check(status == 200 and 'guac-totp-key-secret' not in body.get('attributes', {}), 'admin API also hides seed')
            body['attributes']['guac-totp-key-generated'] = ''
            status, _ = client.request(root + 'users/gtm-reader', 'PUT', body, token=admin)
            check(status in (200, 204), 'independent admin can reset test user enrollment')
            replacement = challenge('gtm-reader')
            check(bool(replacement) and replacement != reader_key, 'reset requires a fresh enrollment secret')
            status, body = client.login('gtm-reader', password, totp(reader_key))
            check(status != 200 and 'authToken' not in body, 'old enrollment no longer authenticates')
            status, body = client.login('gtm-reader', password, totp(replacement))
            check(status == 200 and bool(body.get('authToken')), 'test user can re-enroll after recovery', safe_result(status, body))
            for action in [['switch', 'dark', '--yes', '--trust-theme'], ['reset', '--yes'],
                           ['restore', backup, '--yes', '--trust-theme']]:
                run(cli + action)
                check([run(secured + ['ps', '--quiet', s]).strip() for s in ['db', 'guacd']] == original_ids,
                      action[0] + ': database and guacd container identities unchanged')
                challenge('gtm-reader', enrolled=True)
                run(cli + ['doctor'])
                print('Verified security continuity after ' + action[0] + '.', flush=True)
            # Negative config change: must fail before changing the theme/Web.
            prior_web = run(secured + ['ps', '--quiet', 'web']).strip()
            bad = json.loads(overlay.read_bytes()); bad['services']['web']['environment']['TOTP_ENABLED'] = 'false'
            overlay.write_text(json.dumps(bad))
            refused = subprocess.run(cli + ['reset', '--yes'], capture_output=True, timeout=120)
            check(refused.returncode != 0 and b'Required security feature' in refused.stderr, 'disabled TOTP config blocks theme reset')
            check(run(secured + ['ps', '--quiet', 'web']).strip() == prior_web, 'disabled TOTP refusal does not recreate Web')
            # Return the file to its validated state for safe fixture teardown.
            bad['services']['web']['environment']['TOTP_ENABLED'] = 'true'; overlay.write_text(json.dumps(bad))
            images = []
            for reference in ['guacamole/guacamole:1.6.0', 'guacamole/guacd:1.6.0', 'postgres:16']:
                info = json.loads(run(['docker', 'image', 'inspect', reference]))[0]
                images.append({'reference': reference, 'id': info['Id'], 'repoDigests': info.get('RepoDigests', [])})
            print(json.dumps({'suite': 'P00-G03-G04-P01-TOTP', 'passed': len(results), 'checks': results, 'images': images,
                              'limitations': ['No real SSH/RDP/VNC recording or playback', 'No G01 admission gate or G02 revocation',
                                              'No vendor organization isolation or external ingress', 'Single-node JDBC test only']}, ensure_ascii=False), flush=True)
        finally:
            run(secured + ['down', '--remove-orphans', '--timeout', '10'])


if __name__ == '__main__':
    try:
        main()
    except AcceptanceFailure as failure:
        print('PAM acceptance failed: ' + str(failure), file=sys.stderr)
        sys.exit(1)
    except Exception:
        # HTTP exception text/tracebacks can contain a response or private data.
        print('PAM acceptance could not complete; private command/HTTP details suppressed.', file=sys.stderr)
        sys.exit(1)
