"""Checkpoint initialization must never silently reset trusted state."""
import concurrent.futures
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('probe_init',ROOT/'scripts/init_probe_policy_state.py')
initializer=importlib.util.module_from_spec(spec);spec.loader.exec_module(initializer)
POLICY=b'schemaVersion=1\ngeneration=2\nmode=enforce\n'


class ProbeStateInitTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.policy=self.root/'policy.conf';self.policy.write_bytes(POLICY)
        self.state=self.root/'state'

    def test_new_state_is_private_and_checksummed(self):
        initializer.initialize(self.state,self.policy)
        self.assertEqual(self.state.stat().st_mode & 0o777,0o700)
        for file in self.state.iterdir():self.assertEqual(file.stat().st_mode & 0o777,0o600)
        self.assertEqual((self.state/'policy.checkpoint').read_bytes(),POLICY+b'sha256='+hashlib.sha256(POLICY).hexdigest().encode()+b'\n')

    def test_existing_checkpoint_is_never_reset(self):
        initializer.initialize(self.state,self.policy);before=(self.state/'policy.checkpoint').read_bytes()
        self.policy.write_bytes(POLICY.replace(b'2',b'1'))
        with self.assertRaisesRegex(ValueError,'not empty'):initializer.initialize(self.state,self.policy)
        self.assertEqual((self.state/'policy.checkpoint').read_bytes(),before)

    def test_invalid_policy_creates_no_state(self):
        for bad in [POLICY+b'generation=1\n',POLICY.replace(b'2',b'0'),b'not-policy']:
            self.policy.write_bytes(bad)
            with self.assertRaises(ValueError):initializer.initialize(self.state,self.policy)
            self.assertFalse(self.state.exists())

    def test_symlink_paths_cannot_initialize(self):
        actual=self.root/'actual';actual.mkdir(mode=0o700);self.state.symlink_to(actual)
        with self.assertRaisesRegex(ValueError,'Symlink'):initializer.initialize(self.state,self.policy)
        self.assertEqual(list(actual.iterdir()),[])

    def test_insecure_directory_refused(self):
        self.state.mkdir();self.state.chmod(0o777)
        with self.assertRaisesRegex(ValueError,'0700'):initializer.initialize(self.state,self.policy)
        self.assertEqual(list(self.state.iterdir()),[])

    def test_competing_initializers_have_one_winner(self):
        def attempt(_):
            try:initializer.initialize(self.state,self.policy);return True
            except (OSError,ValueError):return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(attempt,[1,2])),1)
        self.assertTrue((self.state/'policy.checkpoint').read_bytes().startswith(POLICY))
