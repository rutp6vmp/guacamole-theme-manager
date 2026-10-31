"""Private durable bind mount for synthetic probes, never a deployment helper."""
import os
import sys

from docker_acceptance import ROOT, run


class ProbeStateFixture:
    def __init__(self,base,config,policy_file):
        self.root=base/'policy-state'; self.root.mkdir(mode=0o700)
        self.operator=(os.geteuid(),os.getegid())
        values=run(['docker','run','--rm','--entrypoint','/bin/sh','guacamole/guacamole:1.6.0',
                    '-c','id -u; id -g']).decode().split()
        self.owner=tuple(map(int,values))
        run([sys.executable,str(ROOT/'scripts/init_probe_policy_state.py'),
             '--state-dir',str(self.root),'--policy-file',str(policy_file)])
        self.chown(*self.owner)
        config['services']['web']['environment']['PAM_SESSION_PROBE_STATE_DIR']='/var/lib/pam-session-probe-state'
        config['services']['web']['volumes'].append({'type':'bind','source':str(self.root),
            'target':'/var/lib/pam-session-probe-state','read_only':False})

    def utility(self,*arguments,input=None):
        return run(['docker','run','--rm','-i','--user','0','--mount',
            'type=bind,source='+str(self.root)+',target=/state','--entrypoint','/bin/sh',
            'guacamole/guacamole:1.6.0','-c',*arguments],input=input)

    def chown(self,uid,gid):
        if os.geteuid()==0:
            for path in [self.root,*self.root.iterdir()]: os.chown(path,uid,gid)
        else:
            self.utility('chown -R "$1:$2" /state','probe-state',str(uid),str(gid))

    def read(self,name='policy.checkpoint'):
        if name not in {'policy.checkpoint','policy.lock'}: raise ValueError('Unknown fixture file')
        if os.geteuid()==0 or os.geteuid()==self.owner[0]: return (self.root/name).read_bytes()
        return self.utility('cat "/state/$1"','probe-state',name)

    def exists(self):
        if os.geteuid()==0 or os.geteuid()==self.owner[0]:
            return (self.root/'policy.checkpoint').exists()
        return self.utility('if test -e /state/policy.checkpoint; then printf yes; fi','probe-state')==b'yes'

    def write(self,data,name='policy.checkpoint'):
        if name not in {'policy.checkpoint','policy.lock'}: raise ValueError('Unknown fixture file')
        if os.geteuid()==0 or os.geteuid()==self.owner[0]:
            temporary=self.root/'.repair-next'; temporary.write_bytes(data);temporary.chmod(0o600)
            if os.geteuid()==0: os.chown(temporary,*self.owner)
            os.replace(temporary,self.root/name)
        else:
            self.utility('cat > /state/.repair-next && chmod 600 /state/.repair-next && '
                'chown "$1:$2" /state/.repair-next && mv /state/.repair-next "/state/$3"',
                'probe-state',str(self.owner[0]),str(self.owner[1]),name,input=data)

    def remove(self,name='policy.checkpoint'):
        if name not in {'policy.checkpoint','policy.lock'}: raise ValueError('Unknown fixture file')
        if os.geteuid()==0 or os.geteuid()==self.owner[0]: (self.root/name).unlink()
        else: self.utility('rm "/state/$1"','probe-state',name)

    def chmod(self,mode):
        if os.geteuid()==0 or os.geteuid()==self.owner[0]: self.root.chmod(mode)
        else: self.utility('chmod "$1" /state','probe-state',format(mode,'o'))

    def cleanup(self):
        self.chmod(0o700)
        self.chown(*self.operator)
