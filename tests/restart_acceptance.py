#!/usr/bin/env python3
"""0.3 checkpoint, normal restart and SIGKILL against a disposable SSH fixture."""
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from docker_acceptance import run
from pam_acceptance import AcceptanceFailure
from probe_state_fixture import ProbeStateFixture
from session_acceptance import Browser


def runner(probe,ssh_metadata):
    def execute(base,command,cli,url,client,ext,password):
        checks=[]; measurements={}; browser=None; state_fixture=None
        policy_dir=base/'restart-policy';policy_dir.mkdir(mode=0o755);policy_file=policy_dir/'policy.conf'
        def check(condition,name):
            if not condition:raise AcceptanceFailure(name)
            checks.append(name)
        def write_policy(generation,mode='enforce'):
            temp=policy_dir/'next';temp.write_text('schemaVersion=1\ngeneration='+str(generation)+'\nmode='+mode+'\n')
            temp.chmod(0o644);os.replace(temp,policy_file)
        def login():
            status,body=client.login('gtm-reader',password)
            check(status==200 and bool(body.get('authToken')),'fresh native JDBC login available')
            return body['authToken']
        def api(path,token,method='GET',data=None):
            return client.request('api/session/'+path,method,data,token=token)
        resource='ext/postgresql/pam-session-probe/'
        def health(token,healthy,generation=None):
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                status,body=api(resource+'policy',token)
                if status==200 and body.get('healthy')==healthy and (generation is None or body.get('generation')==generation):
                    check(True,'expected checkpoint/policy health observed');return body
                time.sleep(.05)
            raise AcceptanceFailure('checkpoint health transition')
        def issue(token):
            status,body=api(resource+'intents',token,'POST',{'connectionId':'2','ttlMillis':10000,'leaseMillis':60000})
            check(status==200 and bool(body.get('connectionId')),'new intent issued only from healthy checkpoint')
            return body['connectionId']
        def reject_issue(token,label):
            status,_=api(resource+'intents',token,'POST',{'connectionId':'2','ttlMillis':1000,'leaseMillis':5000})
            check(status==403,label+': new intent rejected')
        def open_client(id,token,intent):
            browser.call(op='open',id=id,token=token,connectionId=intent,transport='HTTP')
        def marker(id,name):
            browser.wait(id,lambda state:state['connected'] and state['frames']>0)
            browser.call(op='send',id=id,text='printf READY > /tmp/'+name+'\n')
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                status=subprocess.run(command+['exec','-T','ssh','test','-s','/tmp/'+name],capture_output=True,timeout=10)
                if status.returncode==0:return
                time.sleep(.1)
            raise AcceptanceFailure('real SSH marker '+id)
        def forbidden(id,token,intent):
            open_client(id,token,intent);result=browser.wait(id,lambda state:state['closed'])
            check(not result['connected'] and result['code']==771,id+': old handle cannot connect')
        def raw_read(reference):
            request=urllib.request.Request(url+'tunnel?read:'+reference['uuid'],
                headers={'Guacamole-Tunnel-Token':reference['token']})
            try:response=client.opener.open(request,timeout=5)
            except urllib.error.HTTPError as failure:response=failure
            with response:response.read(65536);return response.code
        def restart(label,abrupt=False):
            start=time.monotonic()
            if abrupt:run(command+['kill','-s','SIGKILL','web'])
            run(command+['up','-d','--no-deps','--force-recreate','--pull','never','--no-build','web'])
            run(cli+['doctor'])
            measurements[label+'ReadinessMs']=round((time.monotonic()-start)*1000)
            check([run(command+['ps','--quiet',service]).strip() for service in ['db','guacd','ssh']]==original,
                  label+': non-Web fixture containers unchanged')

        sql="""
UPDATE guacamole_connection_parameter SET parameter_value='ssh' WHERE connection_id=2 AND parameter_name='hostname';
UPDATE guacamole_connection_parameter SET parameter_value='22' WHERE connection_id=2 AND parameter_name='port';
UPDATE guacamole_connection_parameter SET parameter_value='%s' WHERE connection_id=2 AND parameter_name='password';
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) VALUES (2,'username','probe');
"""%password
        run(command+['exec','-T','db','psql','-U','gtmtest','-d','gtmtest','-v','ON_ERROR_STOP=1'],input=sql.encode())
        write_policy(1)
        jar=ext/'guacamole-pam-session-probe.jar';shutil.copyfile(probe,jar);jar.chmod(0o644)
        compose=base/'compose.json';config=json.loads(compose.read_bytes())
        config['services']['web']['environment'].update({'PAM_SESSION_PROBE_ENABLED':'fixture-only',
            'PAM_SESSION_PROBE_POLICY_FILE':'/run/pam-restart-policy/policy.conf'})
        config['services']['web']['volumes'].append({'type':'bind','source':str(policy_dir),
            'target':'/run/pam-restart-policy','read_only':True})
        state_fixture=ProbeStateFixture(base,config,policy_file)
        try:
            compose.write_text(json.dumps(config))
            original=[run(command+['ps','--quiet',service]).strip() for service in ['db','guacd','ssh']]
            run(command+['up','-d','--no-deps','--force-recreate','--pull','never','--no-build','web'])
            run(cli+['doctor']);browser=Browser(url)
            owner=login();health(owner,True,1)
            write_policy(2);health(owner,True,2)
            saved=state_fixture.read()
            check(b'generation=2\nmode=enforce\n' in saved,'accepted high-water is persisted before success')
            open_client('normal-before',owner,issue(owner));marker('normal-before','pam-before-normal-restart')
            reference=browser.call(op='http-reference',id='normal-before');pending=issue(owner)
            # Roll back the policy only. The trusted checkpoint is preserved.
            write_policy(1,'sharing-control');restart('normalRestart')
            browser.wait('normal-before',lambda state:state['closed'])
            check(raw_read(reference)==404,'old HTTP bearer cannot read after normal Web recreation')
            status,_=api('data/postgresql/connectionGroups/ROOT/tree',owner)
            check(status==403,'old login bearer rejected after normal Web recreation')
            current=login();body=health(current,False,2)
            check(not body['sharingControl'],'disk high-water blocks pre-restart policy rollback')
            reject_issue(current,'rolled-back policy after restart')
            write_policy(3);health(current,True,3)
            forbidden('old-pending-normal',current,pending)
            status,leases=api(resource+'leases',current)
            check(status==200 and leases==[],'new login does not resurrect old lease records')
            open_client('abrupt-before',current,issue(current));marker('abrupt-before','pam-before-abrupt-restart')
            reference=browser.call(op='http-reference',id='abrupt-before');pending=issue(current)
            write_policy(1,'sharing-control');restart('sigkillRestart',True)
            browser.wait('abrupt-before',lambda state:state['closed'])
            check(raw_read(reference)==404,'old HTTP bearer rejected after abrupt termination')
            status,_=api('data/postgresql/connectionGroups/ROOT/tree',current)
            check(status==403,'old login bearer rejected after abrupt termination')
            current=login();health(current,False,3);reject_issue(current,'rollback after SIGKILL')
            check(b'generation=3\nmode=enforce\n' in state_fixture.read(),'SIGKILL preserves committed high-water')
            write_policy(4);health(current,True,4);forbidden('old-pending-abrupt',current,pending)
            saved=state_fixture.read()
            # A corrupt/missing checkpoint must never mean first installation.
            state_fixture.write(b'corrupted checkpoint\n');health(current,False)
            reject_issue(current,'corrupt checkpoint')
            state_fixture.write(saved);health(current,True,4)
            state_fixture.remove();health(current,False)
            reject_issue(current,'missing checkpoint')
            check(not state_fixture.exists(),'runtime never auto-initializes missing checkpoint')
            state_fixture.write(saved);health(current,True,4)
            state_fixture.chmod(0o777);health(current,False)
            reject_issue(current,'insecure state directory')
            state_fixture.chmod(0o700);health(current,True,4)
            # POSIX byte-range locks match Java FileChannel, unlike BSD flock.
            lock_tested=os.geteuid()==0 or os.geteuid()==state_fixture.owner[0]
            if lock_tested:
                with (state_fixture.root/'policy.lock').open('r+b') as lock:
                    fcntl.lockf(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    health(current,False);reject_issue(current,'checkpoint lock held by another process')
                    fcntl.lockf(lock,fcntl.LOCK_UN)
                health(current,True,4)
            # Test actual filesystem write denial, not just an in-memory error.
            for volume in config['services']['web']['volumes']:
                if volume['target']=='/var/lib/pam-session-probe-state':volume['read_only']=True
            # Stop the writable process before publishing the next generation;
            # otherwise its watcher may correctly persist 5 before recreation.
            run(command+['stop','web'])
            compose.write_text(json.dumps(config));write_policy(5);restart('readOnlyState')
            current=login();health(current,False);reject_issue(current,'read-only durable state mount')
            check(state_fixture.read()==saved,'failed durable advance does not overwrite previous checkpoint')
            for volume in config['services']['web']['volumes']:
                if volume['target']=='/var/lib/pam-session-probe-state':volume['read_only']=False
            compose.write_text(json.dumps(config));restart('writableStateRecovered')
            current=login();health(current,True,5)
            check(b'generation=5\nmode=enforce\n' in state_fixture.read(),'repair advances only after writable persistence restored')
            open_client('recovered',current,issue(current));marker('recovered','pam-after-recovery')
            check(True,'recovered checkpoint permits a fresh real SSH session')
            print(json.dumps({'suite':'G02-durable-policy-restart','passed':len(checks),'checks':checks,
                'measurements':measurements,'byteRangeLockTested':lock_tested,
                'artifactSha256':hashlib.sha256(probe.read_bytes()).hexdigest(),'sshTarget':ssh_metadata,
                'limitations':['Test-only Linux local-filesystem/single-writer checkpoint, no HA',
                    'Policy/checkpoint jointly rolled back by host admin is outside this trust boundary',
                    'No hardware power-loss or network-filesystem durability test',
                    'Login tokens/intents/leases deliberately not restored; no grant/MFA/IdP recovery',
                    'Web loss closes gateway tunnels, not a guarantee of OS logout or process termination']},ensure_ascii=False),flush=True)
        finally:
            if browser is not None:browser.close()
            if state_fixture is not None:state_fixture.cleanup()
    return execute
