#!/usr/bin/env python3
"""G01 minimum probe: real JDBC, HTTP/WS/native client, separate deny-only JAR.

Uses pam_acceptance's new disposable fixture; no production paths accepted.
Requires a separately built probe JAR and Playwright/Node for native transports.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from pam_acceptance import main as isolated_fixture, AcceptanceFailure
from docker_acceptance import ROOT, run


def runner(probe):
    def execute(base, command, cli, url, client, ext, password):
        checks = []

        def check(condition, name):
            if not condition:
                raise AcceptanceFailure(name)
            checks.append(name)

        def login(name):
            status, body = client.login(name, password)
            check(status == 200 and bool(body.get('authToken')), name + ': JDBC login works')
            return body['authToken']

        def tunnel(token, kind='c', destination='2', extras=None):
            fields = {'token': token, 'GUAC_DATA_SOURCE':'postgresql', 'GUAC_TYPE':kind, 'GUAC_ID':destination,
                      'GUAC_WIDTH':'800', 'GUAC_HEIGHT':'600', 'GUAC_DPI':'96'}
            fields.update(extras or {})
            request = urllib.request.Request(url + 'tunnel?connect',
                data=urllib.parse.urlencode(fields).encode(), method='POST')
            try:
                response = client.opener.open(request, timeout=15)
            except urllib.error.HTTPError as failure:
                response = failure
            with response:
                return response.code, response.read(65536), response.headers

        sql = b"""
INSERT INTO guacamole_connection_group (connection_group_name,type) VALUES ('Probe Balancer','BALANCING');
UPDATE guacamole_connection SET parent_id=(SELECT connection_group_id FROM guacamole_connection_group WHERE connection_group_name='Probe Balancer') WHERE connection_id=2;
INSERT INTO guacamole_connection_group_permission (entity_id,connection_group_id,permission) SELECT e.entity_id,g.connection_group_id,'READ' FROM guacamole_entity e CROSS JOIN guacamole_connection_group g WHERE e.name='gtm-reader' AND g.connection_group_name='Probe Balancer';
UPDATE guacamole_connection_parameter SET parameter_value='127.0.0.1' WHERE connection_id=2 AND parameter_name='hostname';
UPDATE guacamole_connection_parameter SET parameter_value='1' WHERE connection_id=2 AND parameter_name='port';
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) VALUES (2,'username','synthetic-probe');
"""
        run(command + ['exec','-T','db','psql','-U','gtmtest','-d','gtmtest','-v','ON_ERROR_STOP=1'], input=sql)
        group = run(command + ['exec','-T','db','psql','-U','gtmtest','-d','gtmtest','-Atc',
                               "SELECT connection_group_id FROM guacamole_connection_group WHERE connection_group_name='Probe Balancer'"]).decode().strip()
        reader = login('gtm-reader')
        before = run(command + ['logs','--no-color','guacd']).count(b'Creating new client for protocol')
        status, _, _ = tunnel(reader)
        # Baseline may return a tunnel or protocol failure after guacd connects
        # to the deliberately closed loopback port. It must never be probe-denied.
        after = run(command + ['logs','--no-color','guacd']).count(b'Creating new client for protocol')
        check(after > before, 'positive control reaches real guacd before probe installation')
        original_ids = [run(command + ['ps','--quiet',s]).strip() for s in ['db','guacd']]
        destination = ext / 'guacamole-pam-gate-probe.jar'
        shutil.copyfile(probe, destination); destination.chmod(0o644)
        run(command + ['up','-d','--no-deps','--force-recreate','--pull','never','--no-build','web'])
        run(cli + ['doctor'])
        logs = run(command + ['logs','--no-color','web'])
        check(b'PAM Gate Probe (DENIES CONNECTIONS - TEST ONLY)' in logs, 'separate official extension loaded')
        reader = login('gtm-reader')
        admin = login('gtm-admin')
        status, _ = client.request('api/session/data/postgresql/connectionGroups/ROOT/tree',token=reader)
        check(status == 200, 'authorized native tree still available after decoration (HTTP '+str(status)+')')
        proof = hashlib.sha256(b'postgresql\0gtm-reader\0postgresql\0gtm-reader').hexdigest().encode()
        for token, kind, ident, label, marker, extras in [
            (reader,'c','2','reader direct',b'PAM_PROBE_DENY_CONNECTION',{}),
            (reader,'g',group,'balancing group',b'PAM_PROBE_DENY_GROUP',{}),
            (reader,'c','2','forged browser identity',b'PAM_PROBE_DENY_CONNECTION',{'username':'gtm-admin','user_id':'gtm-admin','mfa':'true'}),
            (admin,'c','2','native administrator',b'PAM_PROBE_DENY_CONNECTION',{}),
            (reader,'c','2','new reconnect attempt',b'PAM_PROBE_DENY_CONNECTION',{}),
        ]:
            status, body, headers = tunnel(token, kind, ident, extras)
            # Native HTTP exposes the fixed exception text through a header.
            message = headers.get('Guacamole-Error-Message', '')
            check(status == 403 and (marker in body or marker.decode() in message), label + ': server rejects before connect')
        status, _, _ = tunnel(reader, 'a', 'nonexistent-test-session')
        check(status in (403,404), 'unknown active ID rejected by native authorization; real join untested')
        browser = subprocess.run(['node',str(ROOT/'tests/gate-browser.mjs')],
            input=json.dumps({'url':url,'password':password,'token':reader}).encode(),
            capture_output=True, timeout=150, env=os.environ)
        if browser.returncode:
            # The browser prints only its fixed stage label on failure.
            for line in browser.stderr.decode(errors='replace').splitlines():
                if line.startswith(('Gate browser acceptance failed at ', 'Gate browser state: ')):
                    print(line, file=sys.stderr)
            raise AcceptanceFailure('native browser gate checks')
        browser_report = json.loads(browser.stdout)
        check(browser_report.get('passed') == 5, 'official HTTP/WS and native client URL denied in real browser')
        logs = run(command + ['logs','--no-color','web'])
        check(b'PAM_PROBE_DECORATE proof='+proof in logs, 'decorator identity comes from authenticated JDBC objects')
        check(b'PAM_PROBE_DENY kind=CONNECTION proof='+proof in logs, 'connect uses same trusted identity proof')
        check(run(command + ['logs','--no-color','guacd']).count(b'Creating new client for protocol') == after,
              'denied requests never start a new guacd client')
        check([run(command + ['ps','--quiet',s]).strip() for s in ['db','guacd']] == original_ids,
              'probe test preserves database and guacd containers')
        # Re-authentication with an existing token exercises redecorate().
        status, result = client.request('api/tokens','POST',{'token':reader,'username':'gtm-reader','password':password},form=True)
        check(status == 200 and bool(result.get('authToken')), 'existing token reauthentication works')
        status, body, headers = tunnel(result['authToken'])
        check(status == 403, 'redecorated context still rejects connect')
        logs = run(command + ['logs','--no-color','web'])
        check(b'PAM_PROBE_REDECORATE proof='+proof in logs, 'redecorate hook reached with authenticated identity')
        # Prove the theme validator still refuses executable providers.
        from test_manager import g
        import io
        candidate = io.BytesIO()
        with zipfile.ZipFile(probe) as original, zipfile.ZipFile(candidate,'w') as transformed:
            for name in original.namelist():
                data = original.read(name)
                if name == 'guac-manifest.json':
                    manifest = json.loads(data); manifest['name']='Probe'; manifest['namespace']='gtm-probe'
                    data = json.dumps(manifest).encode()
                transformed.writestr(name,data)
        candidate = candidate.getvalue()
        rejected = False
        try:
            g.validate_jar(candidate, {'id':'probe','name':'Probe','version':'0.1.0',
                'entry':'guacamole-probe.jar','sha256':{'guacamole-probe.jar':hashlib.sha256(candidate).hexdigest()}})
        except g.ThemeError as failure:
            rejected = 'Only static theme extensions' in str(failure)
        check(rejected, 'static theme validator still rejects Java probe JAR')
        print(json.dumps({'suite':'G01-minimum-probe','passed':len(checks),'browserChecks':browser_report['passed'],
            'checks':checks,'artifactSha256':hashlib.sha256(probe.read_bytes()).hexdigest(),
            'limitations':['Deny-only POC, not production policy or admission',
                           'No stable login-session binding or MFA proof',
                           'Active lookup uses nonexistent ID; real sharing/join untested',
                           'Balancer denied before selection; selected-asset authorization untested',
                           'No real target protocol session or G02 revocation', 'Single JDBC provider and single Web node']}, ensure_ascii=False),flush=True)
    return execute


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-jar', required=True)
    try:
        args = parser.parse_args()
        probe = Path(args.probe_jar).resolve(strict=True)
        with zipfile.ZipFile(probe) as jar:
            manifest = json.loads(jar.read('guac-manifest.json'))
            if manifest.get('namespace') != 'pam-gate-probe' or manifest.get('guacamoleVersion') != '1.6.0':
                raise AcceptanceFailure('wrong probe artifact identity')
        isolated_fixture(gate_runner=runner(probe))
    except AcceptanceFailure as failure:
        print('Gate acceptance failed: '+str(failure),file=sys.stderr); sys.exit(1)
    except Exception:
        print('Gate acceptance could not complete; private diagnostics suppressed.',file=sys.stderr); sys.exit(1)
