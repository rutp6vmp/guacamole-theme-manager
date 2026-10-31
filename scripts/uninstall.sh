#!/bin/sh
# Reset must be completed explicitly before uninstalling the executable.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
prefix=${PREFIX:-/usr/local}
state_dir=${GUAC_THEME_STATE_DIR:-/var/lib/guac-theme}
python3 - "$prefix" "$state_dir" "$project_dir" <<'PY'
import pathlib,sys,importlib.machinery,importlib.util
prefix,state,root=map(pathlib.Path,sys.argv[1:])
loader=importlib.machinery.SourceFileLoader('gtm',str(root/'bin/guac-theme'))
spec=importlib.util.spec_from_loader(loader.name,loader);g=importlib.util.module_from_spec(spec);loader.exec_module(g)
m=g.Manager(state)
with m.lock():
 g.require(not m.pending.exists() and m.state()['id']=='default','Run guac-theme reset/recover before uninstalling')
 if m.config_file.exists():m.assert_managed(m.config())
 target=g.safe_path(prefix/'bin/guac-theme',exists=True)
 g.require(target.read_bytes()==(root/'bin/guac-theme').read_bytes(),'CLI differs; refusing to remove unknown executable')
 target.unlink()
 print('CLI removed. Backups and theme repository retained at '+str(m.root))
PY
