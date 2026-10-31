#!/usr/bin/env python3
"""G01/G02 live SSH test. Creates only new localhost synthetic fixtures.

Requires a session probe JAR, Docker, Node and Playwright. Builds an isolated
OpenSSH image by default; --ssh-image accepts an already-built test image.
No production paths, identities or equipment are used.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

from pam_acceptance import main as isolated_fixture, AcceptanceFailure
from docker_acceptance import ROOT, run


class Browser:
    def __init__(self,url):
        self.process=subprocess.Popen(['node',str(ROOT/'tests/session-browser.mjs')],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=os.environ)
        self.call(op='init',url=url)

    def call(self,**request):
        self.process.stdin.write(json.dumps(request).encode()+b'\n'); self.process.stdin.flush()
        if not select.select([self.process.stdout],[],[],40)[0]:
            raise AcceptanceFailure('private browser protocol timeout')
        line=self.process.stdout.readline()
        result=json.loads(line)
        if not result.get('ok'): raise AcceptanceFailure('private browser operation')
        return result['result']

    def wait(self,id,condition,timeout=12):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            state=self.call(op='state',id=id)
            if condition(state): return state
            time.sleep(.1)
        raise AcceptanceFailure('browser client state deadline '+id+' '+json.dumps(state))

    def close(self):
        try: self.call(op='shutdown')
        except Exception: pass
        try: self.process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.communicate()


def run_suite(probe,ssh_image,ssh_metadata,scenario=None):
    def setup(base,config,password):
        secret=base/'ssh-password'; secret.write_text(password+'\n'); secret.chmod(0o600)
        config['services']['ssh']={'image':ssh_image,
            'volumes':[{'type':'bind','source':str(secret),'target':'/run/secrets/ssh-password','read_only':True}],
            'healthcheck':{'test':['CMD-SHELL','test -s /run/sshd.pid'],'interval':'1s','timeout':'3s','retries':30}}

    def execute(base,command,cli,url,client,ext,password):
        checks=[]; measurements={}; browser=None
        def check(ok,name):
            if not ok: raise AcceptanceFailure(name)
            checks.append(name)
        def login(name='gtm-reader'):
            status,body=client.login(name,password)
            check(status==200 and bool(body.get('authToken')),name+': native login')
            return body['authToken']
        def api(path,token,method='GET',data=None):
            return client.request('api/session/'+path,method,data,token=token)
        def active(token):
            status,body=api('data/postgresql/activeConnections',token)
            check(status==200,'authorized active directory readable')
            return body
        def open_client(id,token,connectionId='2',source='postgresql',kind='c',transport='WebSocket'):
            browser.call(op='open',id=id,token=token,connectionId=connectionId,source=source,kind=kind,transport=transport)
        def marker(id,name):
            browser.wait(id,lambda s:s['connected'] and s['frames']>0)
            browser.call(op='send',id=id,text='printf READY > /tmp/'+name+'\n')
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                result=subprocess.run(command+['exec','-T','ssh','test','-s','/tmp/'+name],capture_output=True,timeout=10)
                if result.returncode==0: return
                time.sleep(.15)
            raise AcceptanceFailure('real SSH command marker')
        def positive_share(owner,admin,connection='2'):
            items=active(admin)
            values=[(ident,item) for ident,item in items.items() if item['connectionIdentifier']==connection]
            check(bool(values),'real active SSH identifier exists')
            ident=values[0][0]
            status,credentials=api('data/postgresql/activeConnections/'+ident+'/sharingCredentials/1',owner)
            check(status==200 and bool(credentials.get('values')),'native sharing credentials available before probe')
            status,shared=client.request('api/tokens','POST',credentials['values'],form=True)
            check(status==200 and bool(shared.get('authToken')),'native shared login before probe')
            sources=shared['availableDataSources']; source=sources[0]
            status,tree=api('data/'+source+'/connectionGroups/ROOT/tree',shared['authToken'])
            check(status==200 and bool(tree.get('childConnections')),'shared data source exposes a real target')
            return ident,shared['authToken'],source,tree['childConnections'][0]['identifier']

        sql="""
UPDATE guacamole_connection_parameter SET parameter_value='ssh' WHERE connection_id IN (2,3) AND parameter_name='hostname';
UPDATE guacamole_connection_parameter SET parameter_value='22' WHERE connection_id IN (2,3) AND parameter_name='port';
UPDATE guacamole_connection_parameter SET parameter_value='%s' WHERE connection_id IN (2,3) AND parameter_name='password';
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) VALUES (2,'username','probe'),(3,'username','probe');
INSERT INTO guacamole_sharing_profile (sharing_profile_name,primary_connection_id) VALUES ('Fixture share',2);
INSERT INTO guacamole_sharing_profile_permission (entity_id,sharing_profile_id,permission) SELECT e.entity_id,1,'READ' FROM guacamole_entity e WHERE e.name='gtm-reader';
"""%password
        run(command+['exec','-T','db','psql','-U','gtmtest','-d','gtmtest','-v','ON_ERROR_STOP=1'],input=sql.encode())
        target_id=run(command+['ps','--quiet','ssh']).decode().strip()
        info=json.loads(run(['docker','inspect',target_id]))[0]
        check(not info['HostConfig'].get('PortBindings'),'SSH target has no host-published port')
        try:
            browser=Browser(url)
            owner=login(); admin=login('gtm-admin')
            open_client('baseline',owner)
            marker('baseline','pam-baseline')
            check(True,'real OpenSSH shell accepts Guacamole keyboard input')
            active_id,shared_token,source,shared_id=positive_share(owner,admin)
            open_client('baseline-join',admin,active_id,kind='a')
            marker('baseline-join','pam-baseline-join')
            check(True,'native administrator can really join active SSH before probe')
            open_client('baseline-share',shared_token,shared_id,source=source)
            marker('baseline-share','pam-baseline-share')
            check(True,'native sharing credentials really connect before probe')
            for id in ['baseline-share','baseline-join','baseline']:
                browser.call(op='disconnect',id=id)
            # A separately named experimental JAR, never the deny-only probe.
            jar=ext/'guacamole-pam-session-probe.jar'; shutil.copyfile(probe,jar); jar.chmod(0o644)
            compose=base/'compose.json'; config=json.loads(compose.read_bytes())
            config['services']['web']['environment']['PAM_SESSION_PROBE_ENABLED']='fixture-only'
            compose.write_text(json.dumps(config))
            original=[run(command+['ps','--quiet',s]).strip() for s in ['db','guacd','ssh']]
            run(command+['up','-d','--no-deps','--force-recreate','--pull','never','--no-build','web'])
            run(cli+['doctor'])
            owner=login(); same_user=login(); other=login('gtm-editor'); admin=login('gtm-admin')
            resource='ext/postgresql/pam-session-probe/'
            def issue(token,asset='2',ttl=10000,duration=60000):
                status,body=api(resource+'intents',token,'POST',{'connectionId':asset,'ttlMillis':ttl,'leaseMillis':duration})
                check(status==200 and body.get('connectionId','').startswith('pam-intent-'),'context-bound intent issued')
                return body['connectionId']
            def leases(token):
                status,body=api(resource+'leases',token)
                check(status==200,'own leases available without credentials')
                return body
            def denied(id,token,destination,kind='c',source='postgresql',transport='WebSocket'):
                open_client(id,token,destination,kind=kind,source=source,transport=transport)
                result=browser.wait(id,lambda s:s['closed'])
                check(not result['connected'] and result['code']==771,id+': actual tunnel forbidden')

            denied('native-bypass',owner,'2')
            status,_=api(resource+'intents',owner,'POST',{'connectionId':'2','ttlMillis':1000,'leaseMillis':1000,'user_id':'gtm-admin'})
            check(status==400,'launch API rejects caller-supplied identity claims')
            status,_=api(resource+'intents',owner,'POST',{'connectionId':'2','ttlMillis':1000,'leaseMillis':500.5})
            check(status==400,'launch durations must be integral server-validated values')
            launch=issue(owner)
            denied('same-name-other-login',same_user,launch)
            denied('different-identity',other,launch)
            open_client('owner',owner,launch)
            marker('owner','pam-owner')
            check(True,'own intent reaches real SSH after cross-context denials')
            denied('replay',owner,launch,transport='HTTP')
            live=[item for item in leases(owner) if item['status']=='ACTIVE']; check(len(live)==1,'one launch creates exactly one tracked lease')
            lease_id=live[0]['id']
            # Find the real native active session, not a fabricated identifier.
            active_id=next(ident for ident,item in active(admin).items() if item['connectionIdentifier']=='2')
            denied('active-join',admin,active_id,kind='a')
            status,_=api('data/postgresql/activeConnections/'+active_id+'/sharingCredentials/1',owner)
            check(status==403,'new sharing credentials blocked for real active session')
            status,_=api(resource+'leases/'+lease_id+'/terminate',same_user,'POST')
            check(status==403,'another login of same subject cannot terminate owner lease')
            # Reauthenticate the same token: state must remain bound to this login.
            pending=issue(owner,'3')
            status,body=client.request('api/tokens','POST',{'token':owner,'username':'gtm-reader','password':password},form=True)
            check(status==200,'same login can reauthenticate')
            owner=body['authToken']
            open_client('other-asset',other,issue(other,'3'))
            marker('other-asset','pam-other')
            check(True,'unrelated actor has independent real SSH lease')
            start=time.monotonic()
            status,result=api(resource+'leases/'+lease_id+'/terminate',owner,'POST')
            check(status==200 and result['status']=='ENDED' and result['terminationConfirmedAt'],'terminate returns confirmed local tunnel closure')
            browser.wait('owner',lambda s:s['closed'])
            measurements['ownerTerminateToBrowserCloseMs']=round((time.monotonic()-start)*1000)
            check(not browser.call(op='state',id='other-asset')['closed'],'owner termination preserves unrelated actor')
            marker('other-asset','pam-other-still-executes')
            status,result=api(resource+'leases/'+lease_id+'/terminate',owner,'POST')
            check(status==200 and result['status']=='ENDED','repeated terminate is idempotent')
            # Native administrator removal is another independently verified path.
            active_other=next(ident for ident,item in active(admin).items() if item['connectionIdentifier']=='3')
            status,_=api('data/postgresql/activeConnections/'+active_other,owner,'DELETE')
            check(status in (403,404) and not browser.call(op='state',id='other-asset')['closed'],
                  'native non-admin removal cannot kill unrelated actor')
            start=time.monotonic()
            status,_=api('data/postgresql/activeConnections/'+active_other,admin,'DELETE')
            check(status in (200,204),'native administrator can remove live SSH session')
            browser.wait('other-asset',lambda s:s['closed'])
            measurements['nativeRemoveToBrowserCloseMs']=round((time.monotonic()-start)*1000)
            # Preserve the existing login-bound pending intent through redecorate.
            open_client('after-reauth',owner,pending)
            marker('after-reauth','pam-reauth')
            check(True,'intent remains with same login after redecorate')
            # Deadline: actual terminal executes before its tunnel is closed.
            launch=issue(same_user,duration=3500)
            open_client('deadline',same_user,launch)
            marker('deadline','pam-deadline')
            start=time.monotonic()
            browser.wait('deadline',lambda s:s['closed'],timeout=8)
            measurements['remainingDeadlineToBrowserCloseMs']=round((time.monotonic()-start)*1000)
            ended=leases(same_user)
            check(any(item['status']=='ENDED' and item['reason']=='DEADLINE' for item in ended),'local deadline closes real SSH tunnel')
            deadline_lease=next(item for item in ended if item['reason']=='DEADLINE')
            expected=dt.datetime.fromisoformat(deadline_lease['deadlineAt'].replace('Z','+00:00'))
            confirmed=dt.datetime.fromisoformat(deadline_lease['terminationConfirmedAt'].replace('Z','+00:00'))
            measurements['localDeadlineConfirmationOverrunMs']=round((confirmed-expected).total_seconds()*1000)
            check(0 <= measurements['localDeadlineConfirmationOverrunMs'] < 2000,'deadline confirmation measured after scheduled deadline')
            expired=issue(same_user,ttl=100)
            time.sleep(.2); denied('expired-launch',same_user,expired)
            # Two transports race for one intent while the first SSH handshake
            # is still in flight. Exactly one may reserve the launch.
            racing=issue(same_user,duration=10000)
            open_client('race-A',same_user,racing)
            open_client('race-B',same_user,racing)
            winner=None; deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                outcomes={id:browser.call(op='state',id=id) for id in ['race-A','race-B']}
                winners=[id for id,state in outcomes.items() if state['connected'] and not state['closed'] and state['frames']>0]
                losers=[id for id,state in outcomes.items() if state['closed'] and not state['connected'] and state['code']==771]
                if len(winners)==1 and len(losers)==1:
                    winner=winners[0]; break
                time.sleep(.1)
            check(winner is not None,'concurrent transport attempts consume an intent exactly once')
            marker(winner,'pam-race')
            live=[item for item in leases(same_user) if item['status']=='ACTIVE']
            check(len(live)==1,'one concurrent winner creates one live lease')
            status,_=api(resource+'leases/'+live[0]['id']+'/terminate',same_user,'POST')
            check(status==200,'concurrent winner can be terminated independently')
            # A revoked context cannot consume pending launches or create new ones.
            unconsumed=issue(owner)
            browser.call(op='send',id='after-reauth',text='nohup sleep 60 >/dev/null 2>&1 & echo $! > /tmp/pam-background.pid\n')
            time.sleep(.3)
            start=time.monotonic()
            status,_=api(resource+'revoke',owner,'POST')
            check(status==200,'context revocation accepted')
            browser.wait('after-reauth',lambda s:s['closed'])
            measurements['contextRevokeToBrowserCloseMs']=round((time.monotonic()-start)*1000)
            denied('revoked-pending',owner,unconsumed)
            status,_=api(resource+'intents',owner,'POST',{'connectionId':'2','ttlMillis':1000,'leaseMillis':5000})
            check(status==403,'revoked context cannot mint new launches')
            result=subprocess.run(command+['exec','-T','ssh','sh','-c','kill -0 "$(cat /tmp/pam-background.pid)"'],capture_output=True,timeout=10)
            check(result.returncode==0,'gateway closure does not imply target background process termination')
            check([run(command+['ps','--quiet',s]).strip() for s in ['db','guacd','ssh']]==original,'only isolated Web was recreated')
            print(json.dumps({'suite':'G01-G02-live-SSH','passed':len(checks),'checks':checks,'measurements':measurements,
                'artifactSha256':hashlib.sha256(probe.read_bytes()).hexdigest(),'sshTarget':ssh_metadata,
                'limitations':['TEST-ONLY in-memory context/intent/lease, no grant or MFA proof',
                    'Single JDBC provider and one Web node, not HA or production SLA',
                    'No RDP/VNC or recording acceptance', 'No process logout/kill guarantee',
                    'No policy-service outage or restart recovery guarantee',
                    'Group selected-asset authorization and already-issued shared credentials still need further coverage']},ensure_ascii=False),flush=True)
        finally:
            if browser is not None: browser.close()

    isolated_fixture(gate_runner=scenario or execute,fixture_setup=setup)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-jar',required=True)
    parser.add_argument('--ssh-image')
    parser.add_argument('--suite',choices=['session','sharing','restart','outage','ingress','recording'],default='session')
    built=None
    try:
        args=parser.parse_args(); probe=Path(args.probe_jar).resolve(strict=True)
        with zipfile.ZipFile(probe) as jar:
            if json.loads(jar.read('guac-manifest.json')).get('namespace')!='pam-session-probe':
                raise AcceptanceFailure('wrong session probe artifact')
        image=args.ssh_image
        if not image:
            built='gtm-ssh-target-'+uuid.uuid4().hex[:12]+':test'; image=built
            print('Building isolated OpenSSH fixture image.',flush=True)
            run(['docker','build','--label','org.guactheme.test-fixture=ssh-target','-t',image,str(ROOT/'tests/fixtures/ssh-target')])
        info=json.loads(run(['docker','image','inspect',image]))[0]
        if info.get('Config',{}).get('Labels',{}).get('org.guactheme.test-fixture')!='ssh-target':
            raise AcceptanceFailure('SSH image is not a labeled test fixture')
        result=subprocess.run(['docker','run','--rm','--entrypoint','/bin/sh',image,'-c',
            'test ! -e /etc/ssh/ssh_host_ed25519_key && test ! -e /etc/ssh/ssh_host_rsa_key'],
            capture_output=True,timeout=20)
        if result.returncode:
            raise AcceptanceFailure('SSH fixture image contains prebuilt host keys')
        package=run(['docker','run','--rm','--entrypoint','dpkg-query',image,'-W','-f=${Version}','openssh-server']).decode().strip()
        metadata={'imageId':info['Id'],'opensshServerVersion':package,'noPrebuiltHostKeys':True}
        scenario=None
        if args.suite=='sharing':
            from sharing_acceptance import runner
            scenario=runner(probe,metadata)
        elif args.suite=='restart':
            from restart_acceptance import runner
            scenario=runner(probe,metadata)
        elif args.suite=='outage':
            from outage_acceptance import runner
            scenario=runner(probe,metadata)
        elif args.suite=='ingress':
            from ingress_acceptance import runner
            scenario=runner(probe,metadata)
        elif args.suite=='recording':
            from recording_acceptance import runner
            scenario=runner(probe,metadata)
        run_suite(probe,image,metadata,scenario=scenario)
    except AcceptanceFailure as failure:
        print('Session acceptance failed: '+str(failure),file=sys.stderr); sys.exit(1)
    except Exception:
        print('Session acceptance could not complete; private diagnostics suppressed.',file=sys.stderr); sys.exit(1)
    finally:
        if built:
            subprocess.run(['docker','image','rm',built],capture_output=True,timeout=60)
