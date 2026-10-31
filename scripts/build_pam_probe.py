#!/usr/bin/env python3
"""Build a separate TEST-ONLY Guacamole 1.6.0 gate probe, without bundling APIs.

JDK: --war official-1.6.0.war [--javac /path/to/javac]
ECJ alternative: --war ... --java /path/to/java --ecj /path/to/ecj.jar
No downloads, installation, DB changes or container operations are performed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.1.0'


def build(args):
    kind = getattr(args, 'probe', 'gate')
    version = '0.5.0' if kind == 'session' else VERSION
    source = ROOT / 'modules/guacamole-adapter-1.6' / ('session-probe' if kind == 'session' else 'probe') / 'src/main'
    with tempfile.TemporaryDirectory(prefix='pam-probe-build-') as temp:
        base = Path(temp); lib = base / 'lib'; lib.mkdir(); classes = base / 'classes'; classes.mkdir()
        war_path = Path(args.war).resolve(strict=True)
        with zipfile.ZipFile(war_path) as war:
            expected = {'WEB-INF/lib/guacamole-ext-1.6.0.jar', 'WEB-INF/lib/guacamole-common-1.6.0.jar'}
            if not expected <= set(war.namelist()):
                raise ValueError('Official Guacamole 1.6.0 WAR APIs required')
            for info in war.infolist():
                if info.filename.startswith('WEB-INF/lib/') and info.filename.endswith('.jar'):
                    (lib / Path(info.filename).name).write_bytes(war.read(info))
        sources = sorted((source / 'java').rglob('*.java'))
        import os
        classpath = os.pathsep.join(str(p) for p in sorted(lib.glob('*.jar')))
        if args.ecj:
            command = [args.java, '-jar', str(Path(args.ecj).resolve(strict=True)), '-source', '1.8', '-target', '1.8']
        else:
            command = [args.javac, '--release', '8']
        command += ['-encoding', 'UTF-8', '-classpath', classpath, '-d', str(classes)] + [str(p) for p in sources]
        result = subprocess.run(command, capture_output=True, timeout=120)
        if result.returncode:
            # Compiler diagnostics contain source references, never runtime secrets.
            print(result.stderr.decode(errors='replace')[:10000], file=sys.stderr)
            raise ValueError('Probe compilation failed')
        files = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob('*.class')}
        prefix = 'org/guactheme/pam/' + ('sessionprobe/' if kind == 'session' else 'probe/')
        if not files or any(not name.startswith(prefix) for name in files):
            raise ValueError('Unexpected compiled classes')
        if any(data[:4] != b'\xca\xfe\xba\xbe' or int.from_bytes(data[6:8],'big') != 52 for data in files.values()):
            raise ValueError('Expected Java 8 class target (major 52)')
        files['guac-manifest.json'] = (source / 'resources/guac-manifest.json').read_bytes()
        files['LICENSE'] = (ROOT / 'LICENSE').read_bytes()
        files['NOTICE'] = b'Test-only original PAM gate probe; Guacamole APIs provided by host, not bundled.\n'
        destination = args.output or ROOT / 'dist' / ('poc-session' if kind == 'session' else 'poc')
        output = Path(destination).resolve(); output.mkdir(parents=True, exist_ok=True)
        target = output / ('guacamole-pam-' + ('session-probe-' if kind == 'session' else 'probe-') + version + '.jar')
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as jar:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name, (2025, 1, 1, 0, 0, 0))
                info.create_system = 3; info.external_attr = 0o100644 << 16; info.compress_type = zipfile.ZIP_DEFLATED
                jar.writestr(info, data)
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        (output / 'SHA256SUMS').write_text(sha + '  ' + target.name + '\n')
        (output / 'build-info.json').write_text(json.dumps({
            'version': version, 'guacamoleVersion': '1.6.0', 'javaClassTarget': 52,
            'warSha256': hashlib.sha256(war_path.read_bytes()).hexdigest(), 'sha256': sha,
            'testOnly': True, 'bundledDependencies': [],
            'probeType': kind,
            'compiler': {'kind':'ecj', 'artifactSha256':hashlib.sha256(Path(args.ecj).read_bytes()).hexdigest()}
                if args.ecj else {'kind':'javac', 'release':8},
        }, indent=2) + '\n')
        print('Built TEST-ONLY ' + kind + ' probe: ' + target.name + ' SHA-256 ' + sha)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--war', required=True)
    parser.add_argument('--javac', default='javac')
    parser.add_argument('--java', default='java')
    parser.add_argument('--ecj')
    parser.add_argument('--probe', choices=['gate','session'], default='gate')
    parser.add_argument('--output', help='Defaults to dist/poc or dist/poc-session according to --probe')
    try:
        build(parser.parse_args())
    except (ValueError, OSError, subprocess.TimeoutExpired, zipfile.BadZipFile) as failure:
        print('Probe build failed: ' + str(failure), file=sys.stderr)
        sys.exit(1)
