#!/usr/bin/env python3
"""Real 1.6.0 WAR tests without Docker; creates a private Tomcat/PG fixture.

Provide already-installed/downloaded upstream binaries. Never runs as root or
touches an existing database, Guacamole directory, or container.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

from seed import seed

ROOT = Path(__file__).resolve().parent.parent


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]


def run(command, **kwargs):
    p = subprocess.run(command, capture_output=True, timeout=180, **kwargs)
    if p.returncode:
        for line in p.stderr.decode(errors='replace').splitlines():
            if line.startswith(('Native browser acceptance failed','Browser acceptance failed')):
                print(line,file=sys.stderr)
        raise RuntimeError('Test dependency command failed (details suppressed)')
    return p.stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['java-home','tomcat','pg-bin','war','jdbc-extension','jdbc-driver','schema','translation-jar']:
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--pg-lib',type=Path)
    args = p.parse_args()
    if os.geteuid()==0:
        raise RuntimeError('Standalone tests must run as an ordinary user')
    with tempfile.TemporaryDirectory(prefix='gtm-native-test-') as temp:
        base = Path(temp); password = secrets.token_urlsafe(32)
        pgport,webport = port(),port()
        while pgport==webport:
            webport=port()
        env = dict(os.environ)
        if args.pg_lib:
            env['LD_LIBRARY_PATH']=str(args.pg_lib)
        db=base/'pgdata'
        run([str(args.pg_bin/'initdb'),'-D',str(db),'-A','trust','--no-locale','-U','gtmtest'],env=env)
        run([str(args.pg_bin/'pg_ctl'),'-D',str(db),'-l',str(base/'pg.log'),'-o',
             '-p '+str(pgport)+' -h 127.0.0.1 -k '+str(base),'start'],env=env)
        proc = None
        try:
            sql=args.schema.read_bytes()+seed(password).encode()
            run([str(args.pg_bin/'psql'),'-h','127.0.0.1','-p',str(pgport),'-U','gtmtest','-d','postgres','-v','ON_ERROR_STOP=1'],input=sql,env=env)
            home=base/'guac-home'; (home/'extensions').mkdir(parents=True); (home/'lib').mkdir()
            shutil.copyfile(args.jdbc_extension,home/'extensions/postgresql.jar')
            shutil.copyfile(args.jdbc_driver,home/'lib/postgresql.jar')
            shutil.copyfile(args.translation_jar,home/'extensions/guacamole-zh-tw.jar')
            original_zh=hashlib.sha256((home/'extensions/guacamole-zh-tw.jar').read_bytes()).hexdigest()
            properties=home/'guacamole.properties'
            properties.write_text('postgresql-hostname: 127.0.0.1\npostgresql-port: '+str(pgport)+
                '\npostgresql-database: postgres\npostgresql-username: gtmtest\npostgresql-password: '+password+
                '\nguacd-hostname: 127.0.0.1\nguacd-port: 1\n')
            properties.chmod(0o600)
            tc=base/'tomcat'
            shutil.copytree(args.tomcat/'conf',tc/'conf')
            for d in ['logs','work','temp','webapps']:
                (tc/d).mkdir()
            server=ET.parse(tc/'conf/server.xml'); server.getroot().set('port','-1')
            configured=False
            for service in server.getroot().findall('Service'):
                for connector in service.findall('Connector'):
                    if not configured and 'HTTP' in connector.get('protocol','HTTP/1.1').upper():
                        connector.set('port',str(webport));connector.set('address','127.0.0.1')
                        configured=True
                    else:service.remove(connector)
            if not configured:raise RuntimeError('No HTTP connector in supplied Tomcat configuration')
            server.write(tc/'conf/server.xml')
            shutil.copyfile(args.war,tc/'webapps/guacamole.war')
            url='http://127.0.0.1:'+str(webport)+'/guacamole/'
            browser_env=dict(env,GTM_TEST_URL=url,GTM_TEST_PASSWORD=password)
            server_env=dict(env,JAVA_HOME=str(args.java_home),CATALINA_HOME=str(args.tomcat),
                            CATALINA_BASE=str(tc),GUACAMOLE_HOME=str(home))
            log=base/'tomcat.log'
            for theme in ['default','librenms','dark','default']:
                print('Testing isolated mode: '+theme,flush=True)
                managed=home/'extensions/guac-theme-managed.jar'
                if managed.exists():managed.unlink()
                if theme!='default':shutil.copyfile(ROOT/('dist/guacamole-'+theme+'.jar'),managed)
                with log.open('wb') as output:
                    proc=subprocess.Popen(['sh',str(args.tomcat/'bin/catalina.sh'),'run'],env=server_env,stdout=output,stderr=subprocess.STDOUT)
                deadline=time.monotonic()+90
                while True:
                    if proc.poll() is not None:raise RuntimeError('Isolated Tomcat exited')
                    try:
                        with urllib.request.urlopen(url,timeout=2) as response:
                            ready=b'ng-app="index"' in response.read()
                        if ready:break
                    except OSError:pass
                    if time.monotonic()>deadline:raise RuntimeError('Isolated Tomcat readiness timeout')
                    time.sleep(.5)
                if theme!='default':
                    with urllib.request.urlopen(url+'app/ext/gtm-'+theme+'/theme-marker.json',timeout=5) as response:
                        assert json.load(response)=={'id':theme,'version':'1.1.0'}
                    expected='LibreNMS Style' if theme=='librenms' else 'GuacTheme Dark'
                    assert 'Extension "'+expected+'" (gtm-'+theme+') loaded.' in log.read_text(errors='replace')
                script='native-browser.mjs' if theme=='default' else 'browser.mjs'
                result=run(['node',str(ROOT/'tests'/script)],env=browser_env)
                print(theme+': '+result.decode().strip())
                assert hashlib.sha256((home/'extensions/guacamole-zh-tw.jar').read_bytes()).hexdigest()==original_zh
                stop(proc);proc=None
            print('Standalone acceptance passed. Native -> LibreNMS -> Dark -> native; same isolated database and unchanged translation JAR.')
        finally:
            if proc is not None:
                stop(proc)
            run([str(args.pg_bin/'pg_ctl'),'-D',str(db),'-m','fast','stop'],env=env)


if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError,subprocess.TimeoutExpired,AssertionError):
        print('Standalone acceptance failed. Dependency/server details suppressed to protect test credentials.',file=sys.stderr)
        sys.exit(1)
