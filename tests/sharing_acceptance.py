#!/usr/bin/env python3
"""Live sharing controls inside session_acceptance's disposable fixture only.

Invoked with session_acceptance.py --suite sharing. Never prints share keys,
login/tunnel bearer tokens, private browser references or complete responses.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from session_acceptance import Browser
from pam_acceptance import AcceptanceFailure
from docker_acceptance import run
from probe_state_fixture import ProbeStateFixture


def runner(probe,ssh_metadata):
    def execute(base,command,cli,url,client,ext,password):
        checks=[]; measurements={}; browser=None; state_fixture=None
        policy_dir=base/'sharing-policy'; policy_dir.mkdir(mode=0o755)
        policy_file=policy_dir/'policy.conf'

        def check(condition,name):
            if not condition: raise AcceptanceFailure(name)
            checks.append(name)

        def write_policy(generation,mode='enforce',raw=None):
            temporary=policy_dir/'policy.next'
            temporary.write_text(raw if raw is not None else
                'schemaVersion=1\ngeneration='+str(generation)+'\nmode='+mode+'\n')
            temporary.chmod(0o644); os.replace(temporary,policy_file)

        def login(name):
            status,body=client.login(name,password)
            check(status==200 and bool(body.get('authToken')),name+': login available')
            return body['authToken']

        def api(path,token,method='GET',data=None):
            return client.request('api/session/'+path,method,data,token=token)

        resource='ext/postgresql/pam-session-probe/'
        def policy_health(token,healthy,control=False,generation=None):
            deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                status,body=api(resource+'policy',token)
                if status==200 and body.get('healthy')==healthy and body.get('sharingControl')==control \
                        and (generation is None or body.get('generation')==generation):
                    check(True,'server accepts expected policy health/version'); return body
                time.sleep(.05)
            raise AcceptanceFailure('policy health/version transition')

        def issue(token,asset='2',duration=60000):
            status,body=api(resource+'intents',token,'POST',{'connectionId':asset,'ttlMillis':10000,'leaseMillis':duration})
            check(status==200 and bool(body.get('connectionId')),'authenticated fixture intent issued')
            return body['connectionId']

        def open_client(id,token,connectionId,source='postgresql',kind='c',transport='WebSocket'):
            browser.call(op='open',id=id,token=token,connectionId=connectionId,source=source,kind=kind,transport=transport)

        def exists(name):
            return subprocess.run(command+['exec','-T','ssh','test','-s','/tmp/'+name],
                capture_output=True,timeout=10).returncode==0

        def wait_marker(name):
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                if exists(name): return
                time.sleep(.1)
            raise AcceptanceFailure('target command marker missing')

        def marker(id,name):
            browser.wait(id,lambda s:s['connected'] and s['frames']>0)
            browser.call(op='send',id=id,text='printf READY > /tmp/'+name+'\n')
            wait_marker(name)

        def forbidden(id,token,target,source='postgresql',kind='c',transport='WebSocket'):
            open_client(id,token,target,source,kind,transport)
            state=browser.wait(id,lambda s:s['closed'])
            check(not state['connected'] and state['code']==771,id+': new tunnel forbidden')

        def active_owner(admin):
            deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                status,body=api('data/postgresql/activeConnections',admin)
                if status==200:
                    for id,item in body.items():
                        if item['connectionIdentifier']=='2' and item.get('username')=='gtm-reader': return id
                time.sleep(.1)
            raise AcceptanceFailure('real owner active session not found')

        def sharing_credentials(owner,active_id):
            status,body=api('data/postgresql/activeConnections/'+active_id+'/sharingCredentials/1',owner)
            check(status==200 and set(body.get('values',{}))=={'key'},'native sharing credential issued under explicit positive control')
            return body['values']

        def shared_login(values):
            status,body=client.request('api/tokens','POST',values,form=True)
            check(status==200 and bool(body.get('authToken')),'previously issued share key still authenticates natively')
            token=body['authToken']; source=body['availableDataSources'][0]
            status,tree=api('data/'+source+'/connectionGroups/ROOT/tree',token)
            check(status==200 and bool(tree.get('childConnections')),'native shared target remains visible to valid sharing login')
            return token,source,tree['childConnections'][0]['identifier']

        def raw_http(reference,operation,payload=None):
            request=urllib.request.Request(url+'tunnel?'+operation+':'+reference['uuid'],
                data=payload,headers={'Guacamole-Tunnel-Token':reference['token']},
                method='POST' if operation=='write' else 'GET')
            try: response=client.opener.open(request,timeout=5)
            except urllib.error.HTTPError as failure: response=failure
            with response:
                response.read(65536)
                return response.code

        def key_instructions(text):
            result=[]
            for char in text:
                code=str(0xff0d if char=='\n' else ord(char))
                for down in ['1','0']: result.append('3.key,'+str(len(code))+'.'+code+',1.'+down+';')
            return ''.join(result).encode()

        sql="""
UPDATE guacamole_connection_parameter SET parameter_value='ssh' WHERE connection_id IN (2,3) AND parameter_name='hostname';
UPDATE guacamole_connection_parameter SET parameter_value='22' WHERE connection_id IN (2,3) AND parameter_name='port';
UPDATE guacamole_connection_parameter SET parameter_value='%s' WHERE connection_id IN (2,3) AND parameter_name='password';
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) VALUES (2,'username','probe'),(3,'username','probe');
INSERT INTO guacamole_sharing_profile (sharing_profile_name,primary_connection_id) VALUES ('Sharing fixture',2);
INSERT INTO guacamole_sharing_profile_permission (entity_id,sharing_profile_id,permission) SELECT e.entity_id,1,'READ' FROM guacamole_entity e WHERE e.name='gtm-reader';
"""%password
        run(command+['exec','-T','db','psql','-U','gtmtest','-d','gtmtest','-v','ON_ERROR_STOP=1'],input=sql.encode())
        write_policy(1,'sharing-control')
        jar=ext/'guacamole-pam-session-probe.jar'; shutil.copyfile(probe,jar); jar.chmod(0o644)
        compose=base/'compose.json'; config=json.loads(compose.read_bytes())
        config['services']['web']['environment'].update({'PAM_SESSION_PROBE_ENABLED':'fixture-only',
            'PAM_SESSION_PROBE_POLICY_FILE':'/run/pam-session-policy/policy.conf'})
        config['services']['web']['volumes'].append({'type':'bind','source':str(policy_dir),
            'target':'/run/pam-session-policy','read_only':True})
        state_fixture=ProbeStateFixture(base,config,policy_file)
        try:
            compose.write_text(json.dumps(config))
            original=[run(command+['ps','--quiet',s]).strip() for s in ['db','guacd','ssh']]
            run(command+['up','-d','--no-deps','--force-recreate','--pull','never','--no-build','web'])
            run(cli+['doctor'])
            browser=Browser(url)
            owner=login('gtm-reader'); other=login('gtm-editor'); admin=login('gtm-admin')
            policy_health(owner,True,True,1)
            open_client('owner',owner,issue(owner)); marker('owner','pam-share-owner')
            open_client('other',other,issue(other,'3')); marker('other','pam-share-other')
            active_id=active_owner(admin)
            values=sharing_credentials(owner,active_id)
            guest,source,target=shared_login(values)
            check(source=='postgresql-shared','actual PostgreSQL sharing authentication provider exercised')
            open_client('viewer-ws',guest,target,source); marker('viewer-ws','pam-share-ws')
            open_client('viewer-http',guest,target,source,transport='HTTP'); marker('viewer-http','pam-share-http')
            open_client('admin-join',admin,active_id,kind='a'); marker('admin-join','pam-share-admin-join')
            check(True,'existing anonymous HTTP/WS sharing and native active join execute real SSH commands')
            status,_=api('ext/'+source+'/pam-session-probe/intents',guest,'POST',
                {'connectionId':'3','ttlMillis':1000,'leaseMillis':5000})
            check(status==403,'anonymous sharing identity cannot mint primary intents')
            reference=browser.call(op='http-reference',id='viewer-http')
            check(raw_http(reference,'write',key_instructions('printf READY > /tmp/pam-raw-before\n'))==200,
                  'raw authenticated HTTP tunnel write succeeds before tightening')
            wait_marker('pam-raw-before')
            start=time.monotonic(); write_policy(2)
            policy_health(owner,True,False,2)
            for id in ['viewer-ws','viewer-http','admin-join']: browser.wait(id,lambda s:s['closed'],timeout=5)
            measurements['policyTighteningToAllSharedClosedMs']=round((time.monotonic()-start)*1000)
            check(True,'policy tightening really closes previously connected HTTP/WS/shared joins')
            marker('owner','pam-owner-after-tightening'); marker('other','pam-other-after-tightening')
            check(True,'tightening sharing preserves usable primary sessions of both actors')
            # Native credential/authentication still succeeds: denial must be
            # at the new connect policy, not invalidated or fabricated keys.
            new_guest,new_source,new_target=shared_login(values)
            forbidden('old-login-new-ws',guest,target,source)
            forbidden('old-key-new-login-http',new_guest,new_target,new_source,transport='HTTP')
            forbidden('native-active-after-tightening',admin,active_id,kind='a')
            status,_=api('data/postgresql/activeConnections/'+active_id+'/sharingCredentials/1',owner)
            check(status==403,'new credentials cannot be issued after tightening')
            read_status=raw_http(reference,'read')
            check(read_status==404,'closed HTTP tunnel cannot be resumed for reading')
            measurements['lateClosedHttpWriteStatus']=raw_http(reference,'write',
                key_instructions('printf LATE > /tmp/pam-raw-after\n'))
            time.sleep(.2)
            check(not exists('pam-raw-after'),'raw late write cannot execute target command after closure')
            # A lower generation cannot resurrect old sharing rights.
            write_policy(1,'sharing-control'); policy_health(owner,False,False,2)
            status,_=api(resource+'intents',owner,'POST',{'connectionId':'2','ttlMillis':1000,'leaseMillis':5000})
            check(status==403,'policy rollback fails closed for new launches')
            forbidden('rollback-old-sharing',guest,target,source)
            marker('other','pam-other-during-rollback')
            write_policy(3); policy_health(owner,True,False,3)
            # Same generation, changed meaning must fail instead of mutate.
            write_policy(3,'sharing-control'); policy_health(owner,False,False,3)
            check(True,'same-generation policy substitution rejected')
            write_policy(4); policy_health(owner,True,False,4)
            status,body=api(resource+'leases',owner)
            lease=next(item for item in body if item['status']=='ACTIVE')
            status,result=api(resource+'leases/'+lease['id']+'/terminate',owner,'POST')
            check(status==200 and result['status']=='ENDED','positive-control parent can be confirmed closed')
            browser.wait('owner',lambda s:s['closed'])
            # Dependency loss closes live sharing and denies new launches, but
            # the independent local timer still enforces the primary deadline.
            write_policy(5,'sharing-control'); policy_health(other,True,True,5)
            timed_owner=login('gtm-reader')
            open_client('timed-owner',timed_owner,issue(timed_owner,duration=5000)); marker('timed-owner','pam-timed-owner')
            timed_id=active_owner(admin)
            timed_values=sharing_credentials(timed_owner,timed_id)
            timed_guest,timed_source,timed_target=shared_login(timed_values)
            open_client('timed-share',timed_guest,timed_target,timed_source); marker('timed-share','pam-timed-share')
            policy_file.unlink(); policy_health(other,False,False,5)
            browser.wait('timed-share',lambda s:s['closed'],timeout=5)
            status,_=api(resource+'intents',other,'POST',{'connectionId':'3','ttlMillis':1000,'leaseMillis':5000})
            check(status==403,'missing required policy denies new launches')
            marker('other','pam-other-during-policy-loss')
            browser.wait('timed-owner',lambda s:s['closed'],timeout=8)
            status,body=api(resource+'leases',timed_owner)
            check(status==200 and any(item['status']=='ENDED' and item['reason']=='DEADLINE' for item in body),
                  'local primary deadline survives required-policy loss')
            write_policy(6,raw='schemaVersion=2\ngeneration=6\nmode=sharing-control\n')
            policy_health(other,False,False,5)
            check(True,'unsupported policy schema cannot enable sharing')
            write_policy(6,'sharing-control'); policy_health(other,True,True,6)
            # Track the parent with native active UUID, not shared-by username.
            revoked_owner=login('gtm-reader')
            open_client('revoke-owner',revoked_owner,issue(revoked_owner)); marker('revoke-owner','pam-revoke-owner')
            revoke_id=active_owner(admin)
            revoke_values=sharing_credentials(revoked_owner,revoke_id)
            revoke_guest,revoke_source,revoke_target=shared_login(revoke_values)
            open_client('revoke-share',revoke_guest,revoke_target,revoke_source); marker('revoke-share','pam-revoke-share')
            open_client('revoke-join',admin,revoke_id,kind='a'); marker('revoke-join','pam-revoke-join')
            start=time.monotonic()
            status,_=api(resource+'revoke',revoked_owner,'POST')
            check(status==200,'parent context revoke accepted under sharing positive control')
            for id in ['revoke-owner','revoke-share','revoke-join']: browser.wait(id,lambda s:s['closed'],timeout=5)
            measurements['parentRevokeToAllChildrenClosedMs']=round((time.monotonic()-start)*1000)
            marker('other','pam-other-after-parent-revoke')
            check(True,'parent revocation closes tracked child sharing and preserves unrelated primary execution')
            write_policy(7); policy_health(other,True,False,7)
            check([run(command+['ps','--quiet',s]).strip() for s in ['db','guacd','ssh']]==original,
                  'only isolated Web was recreated; no production service selected')
            print(json.dumps({'suite':'G01-sharing-policy-live-SSH','passed':len(checks),'checks':checks,
                'measurements':measurements,'artifactSha256':hashlib.sha256(probe.read_bytes()).hexdigest(),
                'sshTarget':ssh_metadata,'limitations':['TEST-ONLY explicit sharing-control mode; not production policy/grant/MFA',
                    'Native share login can remain valid while connect is denied; not IdP revocation',
                    'Single-node/JDBC/SSH; restart durability is verified by the separate restart suite',
                    'No balancing selected-asset, RDP/VNC, recording or HA acceptance',
                    'In-flight target handshakes are not synchronously cancellable']},ensure_ascii=False),flush=True)
        finally:
            if browser is not None: browser.close()
            if state_fixture is not None: state_fixture.cleanup()
    return execute
