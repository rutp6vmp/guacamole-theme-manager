#!/usr/bin/env python3
"""Independent bootstrap and NGINX entry gate in a new private fixture only."""
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from docker_acceptance import ROOT, run
from pam_acceptance import AcceptanceFailure, Client
from probe_state_fixture import ProbeStateFixture
from session_acceptance import Browser

NGINX='nginx:1.28.0-alpine'


def runner(probe,ssh_metadata):
    def execute(base,command,cli,url,client,ext,password):
        checks=[];browser=None;private_browser=None;state_fixture=None;stage='setup'
        def check(condition,name):
            if not condition:raise AcceptanceFailure(name)
            checks.append(name)
        def info(service):
            identifier=run(command+['ps','--all','--quiet',service]).decode().strip()
            return json.loads(run(['docker','inspect',identifier]))[0]
        def private_client():
            values=list(info('web')['NetworkSettings']['Networks'].values())
            if len(values)!=1:raise AcceptanceFailure('ambiguous private Web network')
            return Client('http://'+values[0]['IPAddress']+':8080/guacamole/')
        def fetch(address,method='GET',data=None,headers=None):
            request=urllib.request.Request(address,method=method,data=data,headers=headers or {})
            try:response=client.opener.open(request,timeout=5)
            except urllib.error.HTTPError as failure:response=failure
            with response:return response.code,response.read(1048576)
        def wait_page(address,status,timeout=90):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                try:
                    if fetch(address)[0]==status:return
                except (OSError,urllib.error.URLError):pass
                time.sleep(.2)
            raise AcceptanceFailure('entry/backend HTTP readiness '+str(status))
        def recreate():
            compose.write_text(json.dumps(config))
            run(command+['up','-d','--no-deps','--force-recreate','--pull','never','--no-build','web'])
        def login(target=client):
            status,body=target.login('gtm-reader',password)
            check(status==200 and bool(body.get('authToken')),'controlled native JDBC login available')
            return body['authToken']
        resource='ext/postgresql/pam-session-probe/'
        def api(path,token,method='GET',data=None):
            return client.request('api/session/'+path,method,data,token=token)
        def issue(token,duration=60000):
            status,body=api(resource+'intents',token,'POST',{'connectionId':'2','ttlMillis':10000,'leaseMillis':duration})
            check(status==200 and bool(body.get('connectionId')),'healthy guarded entry issues one-use intent')
            return body['connectionId']
        def open_client(identifier,token,intent,transport='WebSocket',driver=None):
            (driver or browser).call(op='open',id=identifier,token=token,connectionId=intent,transport=transport)
        def marker(identifier,name,driver=None):
            driver=driver or browser
            driver.wait(identifier,lambda state:state['connected'] and state['frames']>0)
            driver.call(op='send',id=identifier,text='printf READY > /tmp/'+name+'\n')
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                result=subprocess.run(command+['exec','-T','ssh','test','-s','/tmp/'+name],capture_output=True,timeout=10)
                if result.returncode==0:return
                time.sleep(.1)
            raise AcceptanceFailure('guarded real SSH command marker')
        def write_policy(generation):
            temporary=policy_dir/'next';temporary.write_text('schemaVersion=1\ngeneration='+str(generation)+'\nmode=enforce\n')
            temporary.chmod(0o644);os.replace(temporary,policy_file)
        def blocked(label,token):
            check(fetch(url)[0]==503,label+': homepage blocked')
            status,_=fetch(url+'api/tokens','POST',
                urllib.parse.urlencode({'username':'gtm-reader','password':password}).encode(),
                {'Content-Type':'application/x-www-form-urlencoded'})
            check(status==503,label+': login POST blocked')
            status,_=fetch(url+'api/session/data/postgresql/connections/2',headers={'Guacamole-Token':token})
            check(status==503,label+': native REST blocked')
            status,_=fetch(url,headers={'X-PAM-Ready':'true','X-Forwarded-User':'gtm-admin'})
            check(status==503,label+': forged browser readiness headers do not open entry')
            for transport in ['HTTP','WebSocket']:
                identifier=label+'-'+transport
                open_client(identifier,token,'2',transport)
                result=browser.wait(identifier,lambda state:state['closed'])
                check(not result['connected'],label+': '+transport+' tunnel cannot connect')
        def bootstrap_refused(label):
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                current=info('web')['State']
                if current['Status']=='exited':break
                time.sleep(.1)
            check(current['Status']=='exited' and current['ExitCode']==78,label+': Web refused before official entrypoint')
            check(b'PAM_PROBE_BOOTSTRAP_REFUSED' in run(command+['logs','--no-color','web']),
                label+': fixed bootstrap failure evidence present')

        sql="""
UPDATE guacamole_connection_parameter SET parameter_value='ssh' WHERE connection_id=2 AND parameter_name='hostname';
UPDATE guacamole_connection_parameter SET parameter_value='22' WHERE connection_id=2 AND parameter_name='port';
UPDATE guacamole_connection_parameter SET parameter_value='%s' WHERE connection_id=2 AND parameter_name='password';
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) VALUES (2,'username','probe');
"""%password
        run(command+['exec','-T','db','psql','-U','gtmtest','-d','gtmtest','-v','ON_ERROR_STOP=1'],input=sql.encode())
        policy_dir=base/'entry-policy';policy_dir.mkdir(mode=0o755);policy_file=policy_dir/'policy.conf';write_policy(1)
        jar=ext/'guacamole-pam-session-probe.jar';shutil.copyfile(probe,jar);jar.chmod(0o644)
        compose=base/'compose.json';config=json.loads(compose.read_bytes())
        web=config['services']['web'];ports=web.pop('ports')
        module=ROOT/'modules/guacamole-adapter-1.6/ingress-probe'
        web['entrypoint']=['/bin/sh','/run/pam-ingress/bootstrap.sh']
        web['command']=['/opt/guacamole/bin/entrypoint.sh']
        web['environment'].update({'PAM_SESSION_PROBE_ENABLED':'fixture-only',
            'PAM_SESSION_PROBE_POLICY_FILE':'/run/pam-entry-policy/policy.conf',
            'PAM_SESSION_PROBE_REQUIRED_SHA256':hashlib.sha256(probe.read_bytes()).hexdigest()})
        web['volumes']+=[{'type':'bind','source':str(module),'target':'/run/pam-ingress','read_only':True},
            {'type':'bind','source':str(policy_dir),'target':'/run/pam-entry-policy','read_only':True}]
        config['services']['entry']={'image':NGINX,
            'ports':[dict(item,target=8080) for item in ports],
            'volumes':[{'type':'bind','source':str(module/'nginx.conf'),'target':'/etc/nginx/nginx.conf','read_only':True}],
            'entrypoint':['nginx','-g','daemon off;']}
        state_fixture=ProbeStateFixture(base,config,policy_file)
        original={service:run(command+['ps','--quiet',service]).strip() for service in ['db','guacd','ssh']}
        try:
            recreate()
            run(command+['up','-d','--no-deps','--pull','never','--no-build','entry'])
            wait_page(url,200);run(cli+['doctor'])
            for service in ['web','db','guacd','ssh']:
                check(not info(service)['HostConfig'].get('PortBindings'),service+': no host-published bypass port')
            check(all(item['HostIp']=='127.0.0.1' for items in info('entry')['HostConfig']['PortBindings'].values() for item in items),
                'only entry publishes a localhost port')
            private=private_client()
            ready=private.url+'api/ext/pam-session-probe/ingress-ready'
            status,body=fetch(ready)
            check(status==204 and body==b'','loaded provider and valid durable policy return empty readiness proof')
            check(b'PAM_PROBE_BOOTSTRAP_READY' in run(command+['logs','--no-color','web']),'pinned module accepted before official entrypoint')
            browser=Browser(url);owner=login()
            stage='healthy-transports'
            open_client('guard-http',owner,issue(owner,6000),'HTTP');marker('guard-http','pam-entry-http')
            open_client('guard-ws',owner,issue(owner,6000));marker('guard-ws','pam-entry-ws')
            check(True,'guarded HTTP and WebSocket both execute real SSH')
            stage='policy-failure';policy_file.unlink();wait_page(url,503)
            blocked('missing-policy',owner)
            # An upgraded WebSocket is not reauthorized per frame by NGINX;
            # the independent provider deadline remains the bounded control.
            browser.wait('guard-ws',lambda state:state['closed'],timeout=10)
            check(True,'already upgraded WebSocket still ends through local lease deadline')
            write_policy(2);wait_page(url,200)
            check(True,'entry recovers only after a higher valid policy is restored')
            stage='missing-module';jar.unlink();recreate();bootstrap_refused('missing-module');wait_page(url,503)
            blocked('missing-module',owner)
            stage='modified-module';jar.write_bytes(b'altered fixture artifact');jar.chmod(0o644)
            recreate();bootstrap_refused('modified-module');wait_page(url,503)
            check(True,'modified executable artifact cannot start the Web')
            # Deliberately omit startup guard in this private negative control:
            # native Guacamole is usable; independent entry must STILL refuse.
            stage='unguarded-control';jar.unlink();del web['entrypoint'];recreate()
            private=private_client();wait_page(private.url,200)
            check(fetch(private.url+'api/ext/pam-session-probe/ingress-ready')[0]==404,
                'unguarded native Web truly runs without required provider')
            native=login(private);private_browser=Browser(private.url)
            open_client('native-without-gate',native,'2',driver=private_browser)
            marker('native-without-gate','pam-private-without-gate',private_browser)
            check(True,'private negative control really executes native SSH without adapter')
            wait_page(url,503);blocked('unguarded-web',native)
            private_browser.close();private_browser=None
            stage='restore-module';shutil.copyfile(probe,jar);jar.chmod(0o644)
            web['entrypoint']=['/bin/sh','/run/pam-ingress/bootstrap.sh'];recreate()
            wait_page(url,200);run(cli+['doctor'])
            owner=login();open_client('restored',owner,issue(owner));marker('restored','pam-entry-restored')
            check(True,'pinned module and valid policy restore guarded SSH with fresh intent')
            # The existing shared deployment manifest must preserve the new
            # entrypoint and module pins during real theme operations.
            web_before=info('web')['Id'];entry_before=info('entry')['Id']
            run(cli+['protect-deployment','--compose-file',str(compose),
                '--protect-extension','guacamole-pam-session-probe.jar'])
            check(info('web')['Id']==web_before,'adopting required module pin does not recreate Web')
            for name in ['librenms','dark']:
                run(cli+['import',str(ROOT/('dist/guac-theme-'+name+'-1.1.0.zip'))])
            backup=None
            for label,arguments in [('install',['install','librenms','--yes','--trust-theme']),
                    ('switch',['switch','dark','--yes','--trust-theme']),('reset',['reset','--yes']),('restore',None)]:
                stage='theme-'+label
                browser.close();browser=None
                run(cli+(arguments or ['restore',backup,'--yes','--trust-theme']))
                current=info('web')['Config']
                check(current['Entrypoint']==['/bin/sh','/run/pam-ingress/bootstrap.sh']
                    and hashlib.sha256(jar.read_bytes()).hexdigest()==hashlib.sha256(probe.read_bytes()).hexdigest(),
                    label+': independent bootstrap and pinned executable preserved')
                browser=Browser(url);owner=login();identifier='theme-'+label
                open_client(identifier,owner,issue(owner));marker(identifier,'pam-entry-'+label)
                check(True,label+': fresh real SSH works through guarded entry')
                check(info('entry')['Id']==entry_before,label+': entry container not recreated by theme CLI')
                if label=='install':backup=run(cli+['backup']).decode().strip()
            check(all(run(command+['ps','--quiet',service]).strip()==identifier for service,identifier in original.items()),
                'database, guacd and SSH containers preserved across entry faults')
            nginx=json.loads(run(['docker','image','inspect',NGINX]))[0]
            print(json.dumps({'suite':'G04-independent-entry-bootstrap','passed':len(checks),'checks':checks,
                'artifactSha256':hashlib.sha256(probe.read_bytes()).hexdigest(),'sshTarget':ssh_metadata,
                'nginx':{'reference':NGINX,'imageId':nginx['Id']},
                'limitations':['TEST ONLY one private Web/JDBC/SSH, localhost HTTP; no vendor production access',
                    'Readiness proves provider/policy availability, not identity/MFA/grant/DB health',
                    'No HA: readiness and proxied request must reach the same private Web instance',
                    'Existing upgraded tunnels rely on provider lease deadlines, not per-frame proxy checks',
                    'Host/Docker administrators can reach private networks or replace trusted configuration',
                    'No formal HTTPS, IdP/worker, RDP/VNC, recording or SLA acceptance']},ensure_ascii=False),flush=True)
        except AcceptanceFailure as failure:
            raise AcceptanceFailure('ingress '+stage+': '+str(failure)) from None
        finally:
            if private_browser is not None:private_browser.close()
            if browser is not None:browser.close()
            state_fixture.cleanup()
    return execute
