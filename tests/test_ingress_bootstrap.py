"""Independent startup check must refuse absent or altered executable modules."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parent.parent/'modules/guacamole-adapter-1.6/ingress-probe/bootstrap.sh'


class IngressBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.jar=self.directory/'guacamole-pam-session-probe.jar'
        self.jar.write_bytes(b'operator-pinned-module')
        self.env={**os.environ,'PAM_SESSION_PROBE_ENABLED':'fixture-only',
            'PAM_SESSION_PROBE_EXTENSIONS_DIR':str(self.directory),
            'PAM_SESSION_PROBE_REQUIRED_SHA256':hashlib.sha256(self.jar.read_bytes()).hexdigest()}

    def check(self,success=False,argument='--check-only'):
        result=subprocess.run(['/bin/sh',str(SCRIPT),argument],env=self.env,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0 if success else 78)
        self.assertEqual(result.stdout,b'PAM_PROBE_BOOTSTRAP_READY\n' if success else b'')
        self.assertEqual(result.stderr,b'' if success else b'PAM_PROBE_BOOTSTRAP_REFUSED\n')

    def test_known_digest_passes_stopped_check(self):self.check(success=True)

    def test_missing_module_refused(self):
        self.jar.unlink();self.check()

    def test_modified_module_refused(self):
        self.jar.write_bytes(b'altered');self.check()

    def test_symlink_module_refused(self):
        actual=self.directory/'actual.jar';self.jar.rename(actual);self.jar.symlink_to(actual);self.check()

    def test_bad_or_missing_pinned_digest_refused(self):
        for digest in ['', 'A'*64, 'a'*63, 'a'*65, '--help', 'a'*64+'\n']:
            self.env['PAM_SESSION_PROBE_REQUIRED_SHA256']=digest;self.check()

    def test_explicit_fixture_opt_in_required(self):
        for value in ['', 'true', 'production']:
            self.env['PAM_SESSION_PROBE_ENABLED']=value;self.check()

    def test_arbitrary_start_command_refused(self):
        self.check(argument='/bin/true')
