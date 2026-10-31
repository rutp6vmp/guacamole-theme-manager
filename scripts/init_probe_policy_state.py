#!/usr/bin/env python3
"""Initialize a NEW test-probe checkpoint directory; never resets existing state.

Run only while the probe is stopped, from a known-good policy. Chown the resulting
0700 directory/0600 files to the Web runtime account before enabling the probe.
No database, credential or container operations are performed.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import uuid

POLICY=re.compile(rb'schemaVersion=1\ngeneration=([1-9][0-9]{0,8})\nmode=(sharing-control|enforce)\n\Z')


def safe_path(path):
    path=Path(os.path.abspath(path))
    if any(part.is_symlink() for part in [path,*path.parents]):
        raise ValueError('Symlink paths are not allowed')
    return path


def initialize(directory,policy_file):
    directory=safe_path(directory); source=safe_path(policy_file)
    with source.open('rb') as stream: policy=stream.read(257)
    if not POLICY.fullmatch(policy): raise ValueError('Known-good canonical policy required')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=directory.stat()
    if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
        raise ValueError('State directory must be operator-owned with mode 0700')
    if any(directory.iterdir()): raise ValueError('State directory is not empty; restore/review instead of reinitializing')
    lock=directory/'policy.lock'
    # O_EXCL also serializes competing initializers. Interrupted initialization
    # deliberately remains incomplete and fail-closed, never auto-resets.
    descriptor=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as stream: stream.flush(); os.fsync(stream.fileno())
    temp=directory/('.checkpoint-'+uuid.uuid4().hex)
    try:
        descriptor=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(policy+b'sha256='+hashlib.sha256(policy).hexdigest().encode()+b'\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp,directory/'policy.checkpoint')
        descriptor=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        if temp.exists(): temp.unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',required=True)
    parser.add_argument('--policy-file',required=True)
    try:
        args=parser.parse_args(); initialize(args.state_dir,args.policy_file)
        print('New test-probe checkpoint initialized; no running deployment changed.')
    except (OSError,ValueError) as failure:
        print('Checkpoint initialization refused: '+(str(failure) if isinstance(failure,ValueError) else 'check private paths and permissions'),file=sys.stderr)
        sys.exit(1)
