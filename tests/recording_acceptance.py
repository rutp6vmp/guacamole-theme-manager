#!/usr/bin/env python3
"""Real SSH recording, native history ACL and context-bound playback prototype."""
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from docker_acceptance import run
from pam_acceptance import AcceptanceFailure
from recording_fixture import RecordingFixture
from session_acceptance import Browser


def runner(probe,ssh_metadata):
    def execute(base,command,cli,url,client,ext,password):
        checks=[];browser=None;storage=None;stage='setup';playbacks=[]
        def check(condition,name):
            if not condition:raise AcceptanceFailure(name)
            checks.append(name)
        def sql(value):
            return run(command+['exec','-T','db','psql','-U','gtmtest','-d','gtmtest','-v','ON_ERROR_STOP=1','-At'],input=value.encode())
        def login(name):
            status,body=client.login(name,password)
            check(status==200 and bool(body.get('authToken')),name+': native JDBC login available')
            return body['authToken']
        def api(path,token,method='GET',data=None):
            return client.request('api/session/'+path,method,data,token=token)
        root='ext/postgresql/pam-session-probe/'
        def raw(path,token=None):
            request=urllib.request.Request(url+path,headers={'Guacamole-Token':token} if token else {})
            try:response=client.opener.open(request,timeout=10)
            except urllib.error.HTTPError as failure:response=failure
            with response:return response.status,response.read(9*1024*1024),response.headers
        def download(lease,token):
            return raw('api/session/'+root+'leases/'+lease+'/recording',token)
        def denied(lease,token,label):
            status,body,_=download(lease,token)
            check(status==403,label+': scoped recording denied')
        def leases(token):
            status,body=api(root+'leases',token)
            check(status==200,'current login lease metadata available')
            return body
        def record(token,identifier,asset='2'):
            status,body=api(root+'intents',token,'POST',{'connectionId':asset,'ttlMillis':10000,'leaseMillis':60000})
            check(status==200,'recording fixture receives one-use intent')
            browser.call(op='open',id=identifier,token=token,connectionId=body['connectionId'],transport='WebSocket')
            browser.wait(identifier,lambda item:item['connected'] and item['frames']>0)
            active=[item for item in leases(token) if item['status']=='ACTIVE']
            check(len(active)==1,'exactly one active recording fixture lease')
            initial=active[0]
            denied(initial['id'],token,identifier+' active recording')
            time.sleep(.6)
            browser.call(op='send',id=identifier,text="printf '\\033[41m\\033[2J\\033[HPAM_RECORDING_"+identifier+"\\n'\n")
            time.sleep(.8)
            browser.call(op='send',id=identifier,text='printf READY > /tmp/pam-recording-'+identifier+'\n')
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                result=subprocess.run(command+['exec','-T','ssh','test','-s','/tmp/pam-recording-'+identifier],capture_output=True,timeout=10)
                if result.returncode==0:break
                time.sleep(.1)
            else:raise AcceptanceFailure('real SSH recording marker')
            time.sleep(.5)
            status,body=api(root+'leases/'+initial['id']+'/terminate',token,'POST')
            check(status==200 and body['status']=='ENDED',identifier+': local tunnel confirmed closed before recording read')
            browser.wait(identifier,lambda item:item['closed'])
            return initial['id']
        def find_history(admin,username,asset='2'):
            status,body=api('data/postgresql/history/connections',admin)
            check(status==200,'native admin history API returns real session records')
            matches=[item for item in body if item['username']==username and item['connectionIdentifier']==asset and item['endDate']]
            check(bool(matches),'native history links ended session with correct actor and asset')
            return max(matches,key=lambda item:item['startDate'])
        def validate(lease,token,label):
            path='api/session/'+root+'leases/'+lease+'/recording'
            report=browser.call(op='recording',path=path,token=token)
            check(report.get('status')==200 and report['bytes']>1000,label+': authenticated browser downloads real recording')
            check(report['duration']>0 and report['playedPosition']>0,label+': recording actually advances in browser player (duration='
                +str(report['duration'])+', position='+str(report['playedPosition'])+')')
            check(report['first']['width']>0 and report['last']['height']>0
                and report['first']['hash']!=report['last']['hash'],label+': browser renders changing recorded pixels')
            check(report['keys']==0,label+': key event recording remains disabled')
            playbacks.append({'label':label,'bytes':report['bytes'],'durationMs':report['duration']})
            return report

        sql("""
UPDATE guacamole_connection_parameter SET parameter_value='ssh' WHERE connection_id IN (2,3) AND parameter_name='hostname';
UPDATE guacamole_connection_parameter SET parameter_value='22' WHERE connection_id IN (2,3) AND parameter_name='port';
UPDATE guacamole_connection_parameter SET parameter_value='%s' WHERE connection_id IN (2,3) AND parameter_name='password';
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value) VALUES (2,'username','probe'),(3,'username','probe');
INSERT INTO guacamole_connection_parameter (connection_id,parameter_name,parameter_value)
SELECT c.connection_id,p.name,p.value FROM guacamole_connection c CROSS JOIN (VALUES
 ('recording-path','${HISTORY_PATH}/${HISTORY_UUID}'),('recording-name','session.guac'),
 ('create-recording-path','true'),('recording-include-keys','false'),('recording-exclude-mouse','true')) p(name,value)
WHERE c.connection_id IN (2,3);
"""%password)
        jar=ext/'guacamole-pam-session-probe.jar';shutil.copyfile(probe,jar);jar.chmod(0o644)
        compose=base/'compose.json';config=json.loads(compose.read_bytes())
        config['services']['web']['environment']['PAM_SESSION_PROBE_ENABLED']='fixture-only'
        storage=RecordingFixture(base,config)
        try:
            compose.write_text(json.dumps(config))
            original={service:run(command+['ps','--quiet',service]).strip() for service in ['db','ssh']}
            run(command+['up','-d','--no-deps','--force-recreate','--pull','never','--no-build','guacd','web'])
            run(cli+['doctor'])
            for service,writable in [('web',False),('guacd',True)]:
                identifier=run(command+['ps','--quiet',service]).decode().strip()
                metadata=json.loads(run(['docker','inspect',identifier]))[0]
                mount=[item for item in metadata['Mounts'] if item['Destination']=='/var/lib/guacamole/recordings']
                check(len(mount)==1 and mount[0]['RW']==writable,service+': recording mount has required access mode')
            browser=Browser(url)
            reader=login('gtm-reader');same=login('gtm-reader');editor=login('gtm-editor');admin=login('gtm-admin');empty=login('gtm-empty')
            stage='real-recording'
            own=record(reader,'reader');other=record(editor,'editor')
            own_history=find_history(admin,'gtm-reader');other_history=find_history(admin,'gtm-editor')
            # Stop this isolated writer after both leases have ended. Quiescent
            # reads alone are not writer-completion evidence. Offline playback
            # also demonstrates that the Web does not need guacd to replay.
            run(command+['stop','--timeout','10','guacd'])
            writer_id=run(command+['ps','--all','--quiet','guacd']).decode().strip()
            writer=json.loads(run(['docker','inspect',writer_id]))[0]
            check(not writer['State']['Running'],'isolated recording writer is stopped before exact snapshot comparison')
            saved=storage.read(own_history['uuid']);other_bytes=storage.read(other_history['uuid'])
            check(saved!=other_bytes,'separate native history UUIDs produce distinct actual recording bytes')
            status,data,headers=download(own,reader)
            check(status==200 and data==saved,'owned lease binds exact native history UUID recording (HTTP '
                +str(status)+', matches='+str(data==saved)+', bodyBytes='+str(len(data))+', fileBytes='+str(len(saved))
                +', appended='+str(data.startswith(saved))+', snapshotMatchesFile='
                +str(headers.get('X-PAM-Recording-SHA256')==hashlib.sha256(saved).hexdigest())
                +', bodyMatchesSnapshot='+str(headers.get('X-PAM-Recording-SHA256')==hashlib.sha256(data).hexdigest())+')')
            check(headers.get('X-PAM-Recording-SHA256')==hashlib.sha256(saved).hexdigest(),'response checksum matches complete stored snapshot')
            check('no-store' in headers.get('Cache-Control','') and headers.get('X-Content-Type-Options')=='nosniff',
                'scoped recording response uses private cache and content type controls')
            check(headers.get('X-PAM-Recording-State')=='validated-snapshot','prototype response never claims final evidence sealing')
            validate(own,reader,'owner');validate(other,editor,'other owner')
            stage='isolation'
            for token,label in [(editor,'different actor'),(same,'same subject different login'),(empty,'unprivileged actor'),(admin,'administrator without owning context')]:
                denied(own,token,label)
            denied(other,reader,'cross-actor guessed lease')
            status,_,_=raw('api/session/'+root+'leases/'+own+'/recording')
            check(status in {401,403},'unauthenticated scoped download rejected')
            # Native playback requires UPDATE or ADMINISTER, not READ alone.
            log=next(iter(own_history['logs']))
            native='api/session/data/postgresql/history/connections/'+own_history['identifier']+'/logs/'+log
            status,native_bytes,_=raw(native,admin)
            check(status==200 and native_bytes==saved,'native admin playback is a real positive control')
            status,_,_=raw(native,reader)
            check(status in {403,404},'READ-only owner cannot bypass via native recording log endpoint')
            status,_=api('data/postgresql/connections/2/parameters',reader)
            check(status==403,'scoped playback never grants native connection parameter read')
            for path in ['recordings/'+own_history['uuid']+'/session.guac','api/recordings/'+own_history['uuid']]:
                status,_,_=raw(path,reader)
                check(status in {403,404},'recording storage is not a public static directory')
            sql("DELETE FROM guacamole_connection_permission WHERE connection_id=2 AND permission='READ' AND entity_id=(SELECT entity_id FROM guacamole_entity WHERE name='gtm-reader');")
            denied(own,reader,'native READ revoked after session ends')
            sql("INSERT INTO guacamole_connection_permission (entity_id,connection_id,permission) SELECT entity_id,2,'READ' FROM guacamole_entity WHERE name='gtm-reader';")
            check(download(own,reader)[0]==200,'restored native READ permits only the original own-login recording')
            stage='storage-faults'
            for content,label in [(b'','empty file'),(saved[:-1],'incomplete final instruction'),(b'\xff','invalid UTF-8')]:
                storage.write(own_history['uuid'],content);denied(own,reader,label)
                storage.write(own_history['uuid'],saved)
            storage.symlink(own_history['uuid'],other_history['uuid']);denied(own,reader,'symlink to another recording')
            storage.write(own_history['uuid'],saved)
            storage.oversize(own_history['uuid']);denied(own,reader,'oversized recording')
            storage.write(own_history['uuid'],saved)
            validate(own,reader,'restored file')
            stage='missing-recording-control'
            run(command+['start','guacd'])
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                writer=json.loads(run(['docker','inspect',writer_id]))[0]
                if writer['State']['Running'] and writer['State'].get('Health',{}).get('Status')=='healthy':break
                time.sleep(.2)
            else:raise AcceptanceFailure('recording writer restart readiness')
            check(True,'same isolated guacd resumes after offline recording playback')
            sql("UPDATE guacamole_connection_parameter SET parameter_value='/recording-path-that-does-not-exist' WHERE connection_id=3 AND parameter_name='recording-path'; UPDATE guacamole_connection_parameter SET parameter_value='false' WHERE connection_id=3 AND parameter_name='create-recording-path';")
            missing=record(reader,'missing',asset='3')
            denied(missing,reader,'native SSH succeeded but recording creation failed')
            check(True,'negative control proves native recording configuration alone does not enforce mandatory capture')
            status,_=api(root+'revoke',reader,'POST');check(status==200,'own login context revoked')
            check(download(own,reader)[0]==403,'revoked context cannot read prior recording')
            check(all(run(command+['ps','--quiet',service]).strip()==identifier for service,identifier in original.items()),
                'recording pilot preserves isolated database and SSH target containers')
            print(json.dumps({'suite':'G03-P01-real-SSH-recording','passed':len(checks),'checks':checks,'playbacks':playbacks,
                'artifactSha256':hashlib.sha256(probe.read_bytes()).hexdigest(),'sshTarget':ssh_metadata,
                'limitations':['Fixture-only same-login own recording; not durable vendor/organization authorization',
                    'SSH only; no RDP/VNC, quota/full-disk, retention or HA acceptance',
                    'Max 8 MiB snapshots, full instruction framing; not immutable evidence or seal',
                    'Native failed recording creation can still allow SSH; mandatory recording enforcement remains incomplete',
                    'Viewing bytes also allows download; no separate production view/download permissions',
                    'Host/DB admins and valid-instruction-boundary truncation remain outside this integrity proof']},ensure_ascii=False),flush=True)
        except AcceptanceFailure as failure:
            raise AcceptanceFailure('recording '+stage+': '+str(failure)) from None
        finally:
            if browser is not None:browser.close()
            if storage is not None:storage.cleanup()
    return execute
