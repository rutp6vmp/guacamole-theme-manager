"""Private recording mount and fault injection for new synthetic fixtures only."""
import os
import uuid
from docker_acceptance import run


class RecordingFixture:
    def __init__(self,base,config):
        self.root=base/'recording-files';self.root.mkdir(mode=0o700)
        self.operator=(os.geteuid(),os.getegid())
        def identity(image):
            return tuple(map(int,run(['docker','run','--rm','--entrypoint','/bin/sh',image,
                '-c','id -u; id -g']).decode().split()))
        self.writer=identity('guacamole/guacd:1.6.0')[0]
        self.reader_group=identity('guacamole/guacamole:1.6.0')[1]
        self.utility('chown "$1:$2" /recordings && chmod 2750 /recordings',
            'recording-fixture',str(self.writer),str(self.reader_group))
        target='/var/lib/guacamole/recordings'
        config['services']['web']['environment'].update({'RECORDING_ENABLED':'true',
            'PAM_SESSION_PROBE_RECORDING_ENABLED':'fixture-only','PAM_SESSION_PROBE_RECORDING_ROOT':target})
        config['services']['web']['volumes'].append({'type':'bind','source':str(self.root),'target':target,'read_only':True})
        config['services']['guacd']['volumes']=[{'type':'bind','source':str(self.root),'target':target,'read_only':False}]
        config['services']['guacd']['entrypoint']=['/bin/sh','-c','umask 007; exec /opt/guacamole/entrypoint.sh']

    def utility(self,*arguments,input=None):
        return run(['docker','run','--rm','-i','--user','0','--mount',
            'type=bind,source='+str(self.root)+',target=/recordings','--entrypoint','/bin/sh',
            'guacamole/guacamole:1.6.0','-c',*arguments],input=input)

    @staticmethod
    def identifier(value):
        if str(uuid.UUID(value))!=value:raise ValueError('Non-canonical history UUID')
        return value

    def read(self,history):
        history=self.identifier(history)
        return self.utility('cat "/recordings/$1/session.guac"','recording-fixture',history)

    def write(self,history,data):
        history=self.identifier(history)
        self.utility('cat > "/recordings/$1/.repair-next" && chmod 640 "/recordings/$1/.repair-next" && '
            'chown "$2:$3" "/recordings/$1/.repair-next" && mv "/recordings/$1/.repair-next" "/recordings/$1/session.guac"',
            'recording-fixture',history,str(self.writer),str(self.reader_group),input=data)

    def symlink(self,history,other):
        self.utility('rm "/recordings/$1/session.guac" && ln -s "../$2/session.guac" "/recordings/$1/session.guac"',
            'recording-fixture',self.identifier(history),self.identifier(other))

    def oversize(self,history):
        self.utility('truncate -s 8388609 "/recordings/$1/session.guac"','recording-fixture',self.identifier(history))

    def cleanup(self):
        self.utility('chown -R "$1:$2" /recordings && chmod -R u+rwX /recordings',
            'recording-fixture',str(self.operator[0]),str(self.operator[1]))
