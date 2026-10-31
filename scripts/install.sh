#!/bin/sh
# Install a standalone CLI; never changes Guacamole or invokes sudo implicitly.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
prefix=${PREFIX:-/usr/local}
case "${1-}" in ''|--upgrade) ;; *) echo 'Usage: install.sh [--upgrade]' >&2; exit 2;; esac
[ "$#" -le 1 ] || exit 2
case "$prefix" in /*) ;; *) echo 'PREFIX must be absolute' >&2; exit 1;; esac
python3 - "$prefix" "$project_dir" "${1-}" <<'PY'
import os,pathlib,sys,importlib.machinery,importlib.util
prefix,root=map(pathlib.Path,sys.argv[1:3])
loader=importlib.machinery.SourceFileLoader('gtm',str(root/'bin/guac-theme'))
spec=importlib.util.spec_from_loader(loader.name,loader);g=importlib.util.module_from_spec(spec);loader.exec_module(g)
dest=g.safe_path(prefix/'bin');dest.mkdir(parents=True,exist_ok=True)
target=g.safe_path(dest/'guac-theme')
if target.exists():
 old=target.read_bytes();new=(root/'bin/guac-theme').read_bytes()
 if old!=new:
  g.require(sys.argv[3]=='--upgrade','Existing CLI differs; use --upgrade to preserve and replace it explicitly')
  g.require(old.startswith(b'#!/usr/bin/env python3') and b'"""GuacTheme Manager.' in old and b'class Manager:' in old,'Unrecognized executable; refusing replacement')
  backups=g.safe_path(prefix/'share/guac-theme/cli-backups');backups.mkdir(mode=0o700,parents=True,exist_ok=True)
  saved=g.safe_path(backups/(g.digest(old)+'.py'))
  if saved.exists():g.require(saved.read_bytes()==old,'Existing CLI backup mismatch')
  else:g.write_atomic(saved,old)
  g.write_atomic(target,new,0o755)
else:g.write_atomic(target,(root/'bin/guac-theme').read_bytes(),0o755)
print('Installed '+str(target))
print('Next: configure explicit deployment paths and import release ZIPs. No containers changed.')
PY
