#!/usr/bin/env python3
"""Creates ONLY a new random Docker project. Never targets an existing deployment.

Requires Docker, Node and Playwright. Uses synthetic data and random credentials.
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
import zipfile

from seed import seed

ROOT = Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def fixture_directory(prefix):
    base=Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield base
    finally:
        if (base/'retain-for-debug').exists():
            print('Private isolated fixture retained for debugging: '+str(base))
        else:
            shutil.rmtree(base)


def run(cmd, **kwargs):
    r = subprocess.run(cmd, capture_output=True, timeout=300, **kwargs)
    if r.returncode:
        for line in r.stderr.decode(errors='replace').splitlines():
            if line.startswith(('Browser acceptance failed','Settings acceptance failed','Settings readiness diagnostic')):
                print(line,file=sys.stderr)
        raise RuntimeError('Isolated test command failed; output suppressed to protect test credentials')
    return r.stdout


def main():
    run(['docker', 'info', '--format', '{{.ServerVersion}}'])
    project = 'gtm-test-' + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    with fixture_directory(prefix=project + '-') as temp:
        base = Path(temp)
        ext = base / 'extensions'; ext.mkdir(mode=0o755)
        # A harmless translation-only fixture that must survive every switch.
        with zipfile.ZipFile(ext / 'guacamole-zh-tw.jar', 'w') as z:
            z.writestr('guac-manifest.json', json.dumps({'guacamoleVersion':'1.6.0', 'name':'Test Traditional Chinese',
                           'namespace':'test-traditional-chinese', 'translations':['translations/zh_TW.json']}))
            z.writestr('translations/zh_TW.json', json.dumps({'NAME':'繁體中文', 'APP':{'ACTION_LOGIN':'登入'}}))
        zh_hash = hashlib.sha256((ext / 'guacamole-zh-tw.jar').read_bytes()).hexdigest()
        # Language-only overlay survives theme install/switch/reset/restore.
        overlay = ext / 'guacamole-jdbc-zh-tw-1.0.0.jar'
        shutil.copyfile(ROOT / 'dist' / overlay.name, overlay)
        overlay_hash = hashlib.sha256(overlay.read_bytes()).hexdigest()
        schema = run(['docker','run','--rm','--entrypoint','/opt/guacamole/bin/initdb.sh',
                      'guacamole/guacamole:1.6.0','--postgresql'])
        init = base / 'init'; init.mkdir(mode=0o755)
        (init / '001.sql').write_bytes(schema)
        (init / '002.sql').write_text(seed(password))
        # PostgreSQL reads its initialization scripts from this read-only fixture.
        for path in init.iterdir():
            path.chmod(0o644)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        url = 'http://127.0.0.1:' + str(port) + '/guacamole/'
        config = {'name': project, 'services': {
            'db': {'image':'postgres:16', 'environment':{'POSTGRES_DB':'gtmtest','POSTGRES_USER':'gtmtest','POSTGRES_PASSWORD':password},
                   'tmpfs':['/var/lib/postgresql/data'],
                   'volumes':[{'type':'bind','source':str(init),'target':'/docker-entrypoint-initdb.d','read_only':True}],
                   'healthcheck':{'test':['CMD','pg_isready','-U','gtmtest','-d','gtmtest'],'interval':'2s','timeout':'3s','retries':30}},
            # The official image probes every five minutes. Use the same probe
            # more frequently in this disposable fixture so --wait can finish.
            'guacd': {'image':'guacamole/guacd:1.6.0',
                      'healthcheck':{'test':['CMD-SHELL','nc -z 127.0.0.1 4822 || exit 1'],
                                     'interval':'2s','timeout':'5s','start_period':'2s','retries':30}},
            'web': {'image':'guacamole/guacamole:1.6.0',
                    'depends_on':{'db':{'condition':'service_healthy'},'guacd':{'condition':'service_started'}},
                    'ports':[{'target':8080,'published':str(port),'host_ip':'127.0.0.1'}],
                    'environment':{'GUACD_HOSTNAME':'guacd','POSTGRESQL_ENABLED':'true','POSTGRESQL_HOSTNAME':'db',
                                   'POSTGRESQL_DATABASE':'gtmtest','POSTGRESQL_USERNAME':'gtmtest','POSTGRESQL_PASSWORD':password},
                    'volumes':[{'type':'bind','source':str(ext),'target':'/etc/guacamole/extensions','read_only':True}]}
        }}
        compose = base / 'compose.json'; compose.write_text(json.dumps(config)); compose.chmod(0o600)
        command = ['docker','compose','-f',str(compose),'--project-name',project]
        cli = [sys.executable,str(ROOT / 'bin/guac-theme'),'--state-dir',str(base / 'state')]
        passed=False
        try:
            print('Starting new isolated project: ' + project)
            run(command + ['up','-d','--wait','--wait-timeout','180'])
            def ids():
                return tuple(run(command + ['ps','--quiet',s]).strip() for s in ['db','guacd'])
            original_ids = ids()
            run(cli + ['configure','--extensions-dir',str(ext),'--compose-file',str(compose),'--project-name',project,
                       '--service','web','--web-url',url,'--timeout','120'])
            run(cli + ['doctor'])
            for name in ['librenms','dark']:
                run(cli + ['import',str(ROOT / ('dist/guac-theme-' + name + '-1.1.0.zip'))])
            run(cli + ['install','librenms','--yes','--trust-theme'])
            bid = run(cli + ['backup']).decode().strip()
            browser_env = dict(os.environ,GTM_TEST_PASSWORD=password,GTM_TEST_URL=url)
            private=base/'browser-env.json';private.write_text(json.dumps({'GTM_TEST_PASSWORD':password,'GTM_TEST_URL':url}));private.chmod(0o600)
            if os.environ.get('GTM_TEST_SUITE') != 'settings':
                result = run(['node',str(ROOT / 'tests/browser.mjs')],env=browser_env)
                print(result.decode().strip())
            result = run(['node',str(ROOT / 'tests/settings-browser.mjs')],env=browser_env)
            print(result.decode().strip())
            if os.environ.get('GTM_TEST_SUITE') == 'settings':
                passed=True
                return
            for action in [['switch','dark','--yes','--trust-theme'], ['reset','--yes'], ['restore',bid,'--yes','--trust-theme']]:
                run(cli + action)
                assert ids() == original_ids, 'A non-Web container changed'
                assert hashlib.sha256((ext / 'guacamole-zh-tw.jar').read_bytes()).hexdigest() == zh_hash
                assert hashlib.sha256(overlay.read_bytes()).hexdigest() == overlay_hash
                run(cli + ['doctor'])
                if action[:2] == ['switch','dark']:
                    result=run(['node',str(ROOT/'tests/settings-browser.mjs')],env=browser_env)
                    print('Dark theme: '+result.decode().strip())
            # Cause a real readiness failure, verify files roll back and recovery
            # is retained when the verification endpoint remains unavailable.
            conf_path = base / 'state/config.json'; conf = json.loads(conf_path.read_bytes())
            conf['webUrl'] = 'http://127.0.0.1:1/guacamole/'; conf['timeout'] = 5
            conf_path.write_text(json.dumps(conf))
            failed = subprocess.run(cli + ['switch','dark','--yes','--trust-theme'],capture_output=True,timeout=180)
            assert failed.returncode != 0 and (base / 'state/pending.json').is_file()
            conf['webUrl'] = url; conf['timeout'] = 120; conf_path.write_text(json.dumps(conf))
            run(cli + ['recover','--yes','--trust-theme'])
            assert ids() == original_ids
            assert not (base / 'state/pending.json').exists()
            print('Clean Docker acceptance passed; db/guacd identities and translation JAR preserved.')
            passed=True
        finally:
            # This command can only reference the just-generated random project
            # and private temporary Compose file. No production volumes exist here.
            if not passed and os.environ.get('GTM_TEST_RETAIN_ON_FAILURE')=='1':
                (base/'retain-for-debug').touch(mode=0o600)
            else:
                run(command + ['down','--remove-orphans','--timeout','10'])


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        print('Docker acceptance could not complete. Check Docker access, dependencies and isolated test images locally.',file=sys.stderr)
        sys.exit(1)
