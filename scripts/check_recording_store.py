#!/usr/bin/env python3
"""Run isolated Java recording validation cases against provided WAR APIs.

No download, installation, container, database or deployment operations.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parent.parent


def main(args):
    with tempfile.TemporaryDirectory(prefix='gtm-recording-check-') as temporary:
        base=Path(temporary);libraries=base/'lib';libraries.mkdir();classes=base/'classes';classes.mkdir()
        with zipfile.ZipFile(args.war) as war:
            for info in war.infolist():
                if info.filename.startswith('WEB-INF/lib/') and info.filename.endswith('.jar'):
                    (libraries/Path(info.filename).name).write_bytes(war.read(info))
        classpath=os.pathsep.join([str(Path(args.probe_jar).resolve(strict=True)),*[str(path) for path in sorted(libraries.glob('*.jar'))]])
        compiler=[args.java,'-jar',args.ecj,'-source','1.8','-target','1.8'] if args.ecj else [args.javac,'--release','8']
        result=subprocess.run(compiler+['-encoding','UTF-8','-cp',classpath,'-d',str(classes),str(ROOT/'tests/java/RecordingStoreChecks.java')],
            capture_output=True,timeout=120)
        if result.returncode:raise ValueError('Boundary harness compilation failed')
        result=subprocess.run([args.java,'-cp',str(classes)+os.pathsep+classpath,'org.guactheme.pam.sessionprobe.RecordingStoreChecks'],
            capture_output=True,timeout=30)
        if result.returncode:raise ValueError('Recording boundary checks failed')
        print(result.stdout.decode().strip())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--war',required=True);parser.add_argument('--probe-jar',required=True)
    parser.add_argument('--java',default='java');parser.add_argument('--javac',default='javac');parser.add_argument('--ecj')
    try:main(parser.parse_args())
    except (OSError,ValueError,subprocess.TimeoutExpired,zipfile.BadZipFile) as failure:
        print('Recording check failed: '+str(failure),file=sys.stderr);sys.exit(1)
