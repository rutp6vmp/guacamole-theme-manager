#!/usr/bin/env python3
"""Live DB pause and guacd death inside a newly generated fixture only.

Reports contain allowlisted statuses/measurements, never response bodies, tokens,
connection parameters, raw Docker metadata or target credentials.
"""
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import time

from docker_acceptance import run
from pam_acceptance import AcceptanceFailure
from session_acceptance import Browser


def require_fixture_service(info, project, service):
    """Refuse lifecycle operations without matching disposable Compose labels."""
    if not re.fullmatch(r'gtm-pam-test-[a-f0-9]{12}', project) or service not in {'db', 'guacd'}:
        raise AcceptanceFailure('unsupported outage fixture target')
    labels = (info.get('Config') or {}).get('Labels') or {}
    identifier = info.get('Id', '')
    if (labels.get('com.docker.compose.project') != project
            or labels.get('com.docker.compose.service') != service
            or not re.fullmatch(r'[a-f0-9]{64}', identifier)):
        raise AcceptanceFailure('outage fixture ownership mismatch')
    return identifier


def runner(probe, ssh_metadata):
    def execute(base, command, cli, url, client, ext, password):
        checks, measurements = [], {}
        browser = None
        paused = False
        compose = base / 'compose.json'
        config = json.loads(compose.read_bytes())
        project = config['name']

        def check(condition, name):
            if not condition:
                raise AcceptanceFailure(name)
            checks.append(name)

        def service_info(service):
            identifier = run(command + ['ps', '--all', '--quiet', service]).decode().strip()
            metadata = json.loads(run(['docker', 'inspect', identifier]))
            if len(metadata) != 1:
                raise AcceptanceFailure('ambiguous outage fixture target')
            require_fixture_service(metadata[0], project, service)
            return metadata[0]

        def lifecycle(service, operation):
            allowed = {('db', 'pause'), ('db', 'unpause'), ('guacd', 'kill'), ('guacd', 'start')}
            if (service, operation) not in allowed:
                raise AcceptanceFailure('unsupported outage lifecycle operation')
            identifier = service_info(service)['Id']
            arguments = ['docker', operation]
            if operation == 'kill':
                arguments += ['--signal', 'SIGKILL']
            run(arguments + [identifier])

        def login():
            status, body = client.login('gtm-reader', password)
            check(status == 200 and bool(body.get('authToken')), 'fresh JDBC login available')
            return body['authToken']

        resource = 'ext/postgresql/pam-session-probe/'

        def api(path, token, method='GET', data=None):
            return client.request('api/session/' + path, method, data, token=token)

        def issue(token, duration=60000):
            status, body = api(resource + 'intents', token, 'POST',
                {'connectionId': '2', 'ttlMillis': 10000, 'leaseMillis': duration})
            check(status == 200 and bool(body.get('connectionId')), 'healthy native access issues test intent')
            return body['connectionId']

        def open_client(identifier, token, intent, transport='WebSocket'):
            browser.call(op='open', id=identifier, token=token, connectionId=intent, transport=transport)

        def marker(identifier, filename):
            browser.wait(identifier, lambda state: state['connected'] and state['frames'] > 0)
            browser.call(op='send', id=identifier, text='printf READY > /tmp/' + filename + '\n')
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                result = subprocess.run(command + ['exec', '-T', 'ssh', 'test', '-s', '/tmp/' + filename],
                    capture_output=True, timeout=10)
                if result.returncode == 0:
                    return
                time.sleep(.1)
            raise AcceptanceFailure('real SSH command marker missing')

        def ended(token, lease_id, reason=None):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                status, body = api(resource + 'leases', token)
                if status == 200:
                    for item in body:
                        if item['id'] == lease_id and item['status'] == 'ENDED' and item['terminationConfirmedAt']:
                            if reason is None or item['reason'] == reason:
                                check(True, 'lease closure is confirmed, not just requested')
                                return item
                time.sleep(.1)
            raise AcceptanceFailure('lease termination confirmation deadline')

        def active_lease(token):
            status, body = api(resource + 'leases', token)
            active = [item for item in body if item['status'] == 'ACTIVE'] if status == 200 else []
            check(len(active) == 1, 'one real SSH lease is active')
            return active[0]

        def rejected_connect(identifier, token, intent, transport='WebSocket', expected_code=None):
            open_client(identifier, token, intent, transport)
            state = browser.wait(identifier, lambda item: item['closed'], timeout=15)
            check(not state['connected'] and state['code'] is not None,
                identifier + ': no tunnel established during failure/replay')
            if expected_code is not None:
                check(state['code'] == expected_code, identifier + ': server explicitly forbids consumed intent')
            return state['code']

        sql = """
UPDATE guacamole_connection_parameter SET parameter_value='ssh' WHERE connection_id=2 AND parameter_name='hostname';
UPDATE guacamole_connection_parameter SET parameter_value='22' WHERE connection_id=2 AND parameter_name='port';
UPDATE guacamole_connection_parameter SET parameter_value='%s' WHERE connection_id=2 AND parameter_name='password';
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) VALUES (2,'username','probe');
""" % password
        run(command + ['exec', '-T', 'db', 'psql', '-U', 'gtmtest', '-d', 'gtmtest', '-v', 'ON_ERROR_STOP=1'], input=sql.encode())
        jar = ext / 'guacamole-pam-session-probe.jar'
        shutil.copyfile(probe, jar)
        jar.chmod(0o644)
        # Public Guacamole 1.6.0 PostgreSQL driver settings; this fixture makes
        # silent DB stalls bounded. No timeout guarantee for default deployments.
        config['services']['web']['environment'].update({
            'PAM_SESSION_PROBE_ENABLED': 'fixture-only',
            'POSTGRESQL_SOCKET_TIMEOUT': '1', 'POSTGRESQL_DEFAULT_STATEMENT_TIMEOUT': '1'})
        compose.write_text(json.dumps(config))
        try:
            run(command + ['up', '-d', '--no-deps', '--force-recreate', '--pull', 'never', '--no-build', 'web'])
            run(cli + ['doctor'])
            baseline = {service: service_info(service)['Id'] for service in ['db', 'guacd']}
            untouched = {service: run(command + ['ps', '--quiet', service]).strip() for service in ['web', 'ssh']}
            browser = Browser(url)
            owner = login()
            open_client('db-deadline', owner, issue(owner, 12000))
            marker('db-deadline', 'pam-before-db-pause')
            lease = active_lease(owner)
            pending_started = time.monotonic()
            pending = issue(owner)
            lifecycle('db', 'pause')
            paused = True
            check(service_info('db')['State']['Paused'], 'owned PostgreSQL process really paused')
            marker('db-deadline', 'pam-during-db-pause')
            check(True, 'existing SSH executes while native permission database is stalled')

            measurements['dbPausePendingConnectCode'] = rejected_connect('db-pending', owner, pending, 'HTTP')
            measurements['dbPausePendingConnectElapsedMs'] = round((time.monotonic() - pending_started) * 1000)
            check(measurements['dbPausePendingConnectElapsedMs'] < 9000
                and measurements['dbPausePendingConnectCode'] != 771,
                'database failure rejects a still-unexpired pending intent (elapsedMs='
                + str(measurements['dbPausePendingConnectElapsedMs']) + ', code='
                + str(measurements['dbPausePendingConnectCode']) + ')')
            start = time.monotonic()
            status, _ = api(resource + 'intents', owner, 'POST',
                {'connectionId': '2', 'ttlMillis': 1000, 'leaseMillis': 5000})
            measurements['dbPauseIssueHttpStatus'] = status
            measurements['dbPauseIssueResponseMs'] = round((time.monotonic() - start) * 1000)
            check(status in {403, 500, 503}, 'stalled database cannot issue a new intent')
            browser.wait('db-deadline', lambda state: state['closed'], timeout=16)
            check(service_info('db')['State']['Paused'], 'local deadline closes SSH before database resumes')
            check(True, 'local tunnel deadline survives unavailable native database')
            lifecycle('db', 'unpause')
            paused = False
            confirmed = ended(owner, lease['id'], 'DEADLINE')
            parse = lambda value: dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            measurements['dbPauseDeadlineConfirmationOverrunMs'] = round(
                (parse(confirmed['terminationConfirmedAt']) - parse(confirmed['deadlineAt'])).total_seconds() * 1000)
            check(0 <= measurements['dbPauseDeadlineConfirmationOverrunMs'] < 6000,
                'database outage termination confirmation stays bounded in this fixture')
            check(service_info('db')['Id'] == baseline['db'], 'database resumed without recreation or data reinitialization')
            status, _ = api('data/postgresql/connections/2', owner)
            check(status == 200, 'native asset access recovers after database resumes')
            fresh = login()
            open_client('guacd-before', fresh, issue(fresh))
            marker('guacd-before', 'pam-before-guacd-death')
            previous = active_lease(fresh)
            # Demonstrate the source of failure: database access still succeeds,
            # the guacd process is actually dead, and Web/SSH are left running.
            lifecycle('guacd', 'kill')
            start = time.monotonic()
            check(not service_info('guacd')['State']['Running'], 'owned guacd really terminated by SIGKILL')
            browser.wait('guacd-before', lambda state: state['closed'], timeout=8)
            measurements['guacdKillToBrowserClosedMs'] = round((time.monotonic() - start) * 1000)
            ended(fresh, previous['id'])
            status, _ = api('data/postgresql/connections/2', fresh)
            check(status == 200, 'native database access remains healthy during guacd loss')
            failed_started = time.monotonic()
            failed = issue(fresh)
            # The native guacd connection may take its own 15-second socket
            # timeout. Race the duplicate while the winner is still in flight,
            # so a later TTL expiry cannot masquerade as one-use consumption.
            contenders = ['guacd-down-A', 'guacd-down-B']
            for identifier in contenders:
                open_client(identifier, fresh, failed)
            winner = None
            while time.monotonic() - failed_started < 9:
                states = {identifier: browser.call(op='state', id=identifier) for identifier in contenders}
                forbidden = [identifier for identifier, item in states.items()
                    if item['closed'] and not item['connected'] and item['code'] == 771]
                if len(forbidden) == 1:
                    winner = next(identifier for identifier in contenders if identifier not in forbidden)
                    break
                time.sleep(.05)
            check(winner is not None, 'duplicate failed launch rejected before TTL expiry while native connect is in flight')
            state = browser.wait(winner, lambda item: item['closed'], timeout=25)
            check(not state['connected'] and state['code'] is not None and state['code'] != 771,
                'single consumed launch fails at native guacd, not at intent expiry')
            measurements['guacdDownConnectCode'] = state['code']
            measurements['guacdDownConnectFailureMs'] = round((time.monotonic() - failed_started) * 1000)
            status, leases = api(resource + 'leases', fresh)
            check(status == 200 and not any(item['status'] == 'ACTIVE' for item in leases),
                'failed native connect creates no ACTIVE lease')
            lifecycle('guacd', 'start')
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                info = service_info('guacd')
                if info['State']['Running'] and info['State'].get('Health', {}).get('Status') == 'healthy':
                    break
                time.sleep(.2)
            else:
                raise AcceptanceFailure('guacd restart readiness')
            check(info['Id'] == baseline['guacd'], 'same isolated guacd container recovered')
            rejected_connect('failed-connect-replay', fresh, failed, expected_code=771)
            open_client('guacd-recovered', fresh, issue(fresh), 'HTTP')
            marker('guacd-recovered', 'pam-after-guacd-recovery')
            check(True, 'fresh intent executes real SSH after guacd recovery')
            status, leases = api(resource + 'leases', fresh)
            check(status == 200 and len([item for item in leases if item['status'] == 'ACTIVE']) == 1,
                'recovery does not resurrect previously ended lease')
            check(all(run(command + ['ps', '--quiet', service]).strip() == identifier
                for service, identifier in untouched.items()), 'Web and SSH fixture containers never restarted during faults')
            print(json.dumps({'suite': 'G02-native-dependency-outage', 'passed': len(checks), 'checks': checks,
                'measurements': measurements, 'artifactSha256': hashlib.sha256(probe.read_bytes()).hexdigest(),
                'sshTarget': ssh_metadata, 'fixturePostgresqlSocketTimeoutSeconds': 1,
                'limitations': ['Test-only single-Web/JDBC/SSH; not a production policy/IdP/worker outage test',
                    'DB process pause is a silent stall, not every partition or database failure',
                    'PostgreSQL socket/statement timeouts set explicitly; defaults do not provide this bound',
                    'No HA/fencing, power-loss, RDP/VNC, recording, or formal SLA acceptance',
                    'Tunnel closure does not guarantee target OS logout or process termination']}, ensure_ascii=False), flush=True)
        finally:
            if paused:
                lifecycle('db', 'unpause')
            if browser is not None:
                browser.close()
    return execute
