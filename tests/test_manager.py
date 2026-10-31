"""Security and transaction tests. All files/containers are simulated in temp dirs."""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader('gtm_test', str(ROOT / 'bin/guac-theme'))
spec = importlib.util.spec_from_loader(loader.name, loader)
g = importlib.util.module_from_spec(spec)
loader.exec_module(g)


def zipped(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return output.getvalue()


def package_rewrite(original, transform):
    files = g.archive(original)
    transform(files)
    files['SHA256SUMS'] = ''.join(g.digest(files[n]) + '  ' + n + '\n' for n in sorted(files) if n != 'SHA256SUMS').encode()
    return zipped(files)


class FakeManager(g.Manager):
    def __init__(self, state):
        super().__init__(state)
        self.calls = []
        self.failures = []
        self.bad_mount = False
        self.bad_image = False
        self.shares_mount = False
        self.missing_container = False
        self.web_env = {}
        self.runtime_env = None
        self.runtime_files = None

    def run(self, cmd):
        self.calls.append(cmd)
        c = self.config()
        ext = c['extensionsDir']
        image = 'guacamole/guacamole:1.6.0' if not self.bad_image else 'postgres:16'
        volume = {'type': 'bind', 'source': ext, 'target': '/etc/guacamole/extensions', 'read_only': not self.bad_mount}
        if 'config' in cmd:
            services = {'web': {'image': image, 'volumes': [volume], 'environment': self.web_env}, 'db': {'image': 'postgres:16', 'volumes': []}}
            if self.shares_mount:
                services['db']['volumes'] = [volume]
            result = {'name': 'isolated-test', 'services': services}
        elif 'inspect' in cmd:
            result = [{'Config': {'Image': image, 'Env': [k+'='+v for k,v in (self.web_env if self.runtime_env is None else self.runtime_env).items()],
                       'Labels': {'com.docker.compose.service': 'web', 'com.docker.compose.project': 'isolated-test',
                                  'com.docker.compose.project.config_files': ','.join(self.runtime_files or c['composeFiles'])}},
                       'State': {'Running': True}, 'Mounts': [{'Type': 'bind', 'Source': ext, 'Destination': '/etc/guacamole/extensions', 'RW': False}]}]
        elif 'ps' in cmd:
            return b'' if self.missing_container else b'a' * 64
        elif 'up' in cmd:
            assert cmd[-1] == 'web' and '--no-deps' in cmd and '--pull' in cmd and 'never' in cmd and '--no-build' in cmd
            self.missing_container = False
            return b''
        elif 'logs' in cmd:
            return b''
        else:
            raise AssertionError('Unexpected command: ' + repr(cmd))
        return json.dumps(result).encode()

    def verify(self, config, state):
        if self.failures and self.failures[0] == state['id']:
            self.failures.pop(0)
            raise g.ThemeError('Simulated failed theme load')


class ManagerFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.libre = (ROOT / 'dist/guac-theme-librenms-1.1.0.zip').read_bytes()
        cls.dark = (ROOT / 'dist/guac-theme-dark-1.1.0.zip').read_bytes()

    def setUp(self):
        streams = contextlib.ExitStack()
        self.addCleanup(streams.close)
        streams.enter_context(contextlib.redirect_stdout(io.StringIO()))
        streams.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ext = self.base / 'extensions'; self.ext.mkdir()
        self.zh = self.ext / 'guacamole-zh-tw.jar'; self.zh.write_bytes(b'translation-must-survive')
        self.auth = self.ext / 'jdbc.jar'; self.auth.write_bytes(b'authentication-must-survive')
        self.compose = self.base / 'compose.yaml'; self.compose.write_text('test fixture only')
        self.m = FakeManager(self.base / 'state')
        self.m.configure(argparse.Namespace(extensions_dir=str(self.ext), compose_file=[str(self.compose)],
                         service='web', web_url='http://127.0.0.1:18080/guacamole/', project_name=None, timeout=5))
        self.args = argparse.Namespace(yes=True, trust_theme=True)
        self.import_bytes(self.libre)
        self.import_bytes(self.dark)

    def import_bytes(self, data):
        p = self.base / 'theme.zip'; p.write_bytes(data); self.m.import_theme(p)

    def assert_preserved(self):
        self.assertEqual(self.zh.read_bytes(), b'translation-must-survive')
        self.assertEqual(self.auth.read_bytes(), b'authentication-must-survive')


class ManagerTest(ManagerFixture):
    def test_switch_dark_reset_and_restore(self):
        self.m.change('librenms', self.args)
        bid = self.m.backup(self.m.config())
        self.m.change('dark', self.args)
        self.m.change('default', self.args)
        self.assertFalse((self.ext / g.MANAGED).exists())
        self.m.change(None, self.args, restore=bid)
        self.assertEqual(self.m.state()['id'], 'librenms')
        self.assert_preserved()
        self.assertEqual(len([x for x in self.m.calls if 'up' in x]), 4)

    def test_rollback_restores_previous_bytes(self):
        self.m.change('librenms', self.args)
        before = (self.ext / g.MANAGED).read_bytes()
        self.m.failures = ['dark']
        with self.assertRaisesRegex(g.ThemeError, 'previous theme restored'):
            self.m.change('dark', self.args)
        self.assertEqual((self.ext / g.MANAGED).read_bytes(), before)
        self.assertFalse(self.m.pending.exists()); self.assert_preserved()

    def test_initial_theme_failure_restores_native(self):
        self.m.failures = ['librenms']
        with self.assertRaisesRegex(g.ThemeError,'previous theme restored'):
            self.m.change('librenms',self.args)
        self.assertEqual(self.m.state()['id'],'default')
        self.assertFalse((self.ext/g.MANAGED).exists())
        self.assertFalse(self.m.pending.exists());self.assert_preserved()

    def test_install_command_and_restore_without_repository(self):
        with patch.object(g,'Manager',return_value=self.m):
            self.assertEqual(g.main(['--state-dir',str(self.m.root),'install','librenms','--yes','--trust-theme']),0)
        bid=self.m.backup(self.m.config())
        self.m.change('dark',self.args)
        import shutil
        shutil.rmtree(self.m.root/'themes/librenms')
        self.m.change(None,self.args,restore=bid)
        self.assertEqual(self.m.state()['id'],'librenms');self.assert_preserved()

    def test_failed_rollback_can_recover(self):
        self.m.change('librenms', self.args)
        self.m.failures = ['dark', 'librenms']
        with self.assertRaisesRegex(g.ThemeError, 'recovery could not be verified'):
            self.m.change('dark', self.args)
        self.assertTrue(self.m.pending.exists())
        self.m.recover(self.args)
        self.assertFalse(self.m.pending.exists()); self.assert_preserved()

    def test_recover_after_failed_recreation_left_no_web_container(self):
        self.m.change('librenms',self.args)
        self.m.failures = ['dark','librenms']
        with self.assertRaises(g.ThemeError):
            self.m.change('dark',self.args)
        self.m.missing_container = True
        self.m.recover(self.args)
        self.assertFalse(self.m.pending.exists())
        self.assertFalse(self.m.missing_container)
        self.assert_preserved()

    def test_compose_change_after_validation_refuses_restart(self):
        c = self.m.config();self.m.preflight(c)
        self.m.shares_mount = True
        with self.assertRaisesRegex(g.ThemeError,'changed after validation'):
            self.m.restart(c)
        self.assertFalse(any('up' in x for x in self.m.calls))

    def test_interrupted_write_recovery(self):
        c = self.m.config(); bid = self.m.backup(c)
        meta, jar, manifest = self.m.theme('librenms')
        target = {'id': 'librenms', 'sha256': g.digest(jar), 'name': manifest['name'], 'namespace': manifest['namespace'], 'version': meta['version']}
        g.write_json(self.m.pending, {'backup': bid, 'target': target})
        # Crash after replacing JAR but before updating current.json.
        (self.ext / g.MANAGED).write_bytes(jar)
        self.m.recover(self.args)
        self.assertEqual(self.m.state()['id'], 'default'); self.assert_preserved()

    def test_unknown_reserved_jar_not_overwritten(self):
        p = self.ext / g.MANAGED; p.write_bytes(b'unknown')
        with self.assertRaisesRegex(g.ThemeError, 'Untracked'):
            self.m.change('librenms', self.args)
        self.assertEqual(p.read_bytes(), b'unknown')

    def test_modified_managed_jar_not_deleted(self):
        self.m.change('librenms', self.args)
        p = self.ext / g.MANAGED; p.write_bytes(b'modified')
        with self.assertRaisesRegex(g.ThemeError, 'missing/modified'):
            self.m.change('default', self.args)
        self.assertEqual(p.read_bytes(), b'modified')

    def test_writable_mount_rejected(self):
        self.m.bad_mount = True
        with self.assertRaisesRegex(g.ThemeError, 'read-only'):
            self.m.change('librenms', self.args)
        self.assertFalse((self.ext / g.MANAGED).exists())

    def test_database_service_image_rejected(self):
        self.m.bad_image = True
        with self.assertRaisesRegex(g.ThemeError, 'official pinned'):
            self.m.change('librenms', self.args)

    def test_shared_extensions_mount_rejected(self):
        self.m.shares_mount = True
        with self.assertRaisesRegex(g.ThemeError, 'shared'):
            self.m.change('librenms', self.args)

    def test_untrusted_activation_requires_explicit_trust(self):
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(g.ThemeError, '--trust-theme'):
                self.m.change('librenms', argparse.Namespace(yes=True, trust_theme=False))
        self.assertFalse((self.ext / g.MANAGED).exists())

    def test_restart_requires_explicit_confirmation(self):
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(g.ThemeError, '--yes'):
                self.m.change('librenms', argparse.Namespace(yes=False, trust_theme=True))
        self.assertFalse((self.ext / g.MANAGED).exists())

    def test_duplicate_import_cannot_replace(self):
        with self.assertRaisesRegex(g.ThemeError, 'already imported'):
            self.import_bytes(self.libre)

    def test_explicit_replace_backs_up_repository_without_changing_active_jar(self):
        self.m.change('librenms',self.args)
        before=(self.ext/g.MANAGED).read_bytes()
        def retag(files):
            jar=g.archive(files['guacamole-librenms.jar'])
            jar['theme-marker.json']=b'{"id":"librenms","version":"1.2.0"}'
            files['guacamole-librenms.jar']=zipped(jar)
            meta=json.loads(files['theme.json']);meta['version']='1.2.0'
            meta['sha256']['guacamole-librenms.jar']=g.digest(files['guacamole-librenms.jar'])
            files['theme.json']=json.dumps(meta).encode()
        path=self.base/'upgrade.zip';path.write_bytes(package_rewrite(self.libre,retag))
        self.m.import_theme(path,replace=True)
        self.assertEqual((self.ext/g.MANAGED).read_bytes(),before)
        self.assertEqual(self.m.state()['version'],'1.1.0')
        self.assertEqual(self.m.theme('librenms')[0]['version'],'1.2.0')
        backups=list((self.m.root/'repository-backups').iterdir())
        self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/'guacamole-librenms.jar').read_bytes(),before)
        self.m.change('librenms',self.args)
        self.assertEqual(self.m.state()['version'],'1.2.0');self.assert_preserved()

    def test_invalid_replace_preserves_repository_and_active_jar(self):
        self.m.change('librenms',self.args)
        before=(self.ext/g.MANAGED).read_bytes()
        path=self.base/'bad.zip';path.write_bytes(b'invalid')
        with self.assertRaises(g.ThemeError):self.m.import_theme(path,replace=True)
        self.assertEqual(self.m.theme('librenms')[1],before)
        self.assertEqual((self.ext/g.MANAGED).read_bytes(),before)

    def test_cli_list_current_remove_and_active_protection(self):
        state = str(self.m.root)
        self.assertEqual(g.main(['--state-dir',state,'list']),0)
        self.assertEqual(g.main(['--state-dir',state,'current']),0)
        self.m.change('librenms', self.args)
        self.assertEqual(g.main(['--state-dir',state,'remove','librenms']),1)
        self.assertEqual(g.main(['--state-dir',state,'remove','dark']),0)
        self.assertFalse((self.m.root / 'themes/dark').exists())
        self.assert_preserved()

    def test_pending_blocks_import_remove_backup_and_switch(self):
        g.write_json(self.m.pending, {'backup':'pending'})
        state = str(self.m.root)
        for command in [['import',str(self.base/'theme.zip')], ['remove','dark'], ['backup'], ['switch','dark','--yes','--trust-theme']]:
            self.assertEqual(g.main(['--state-dir',state,*command]),1)
        self.assertEqual(g.main(['--state-dir',state,'current']),0)

    def test_world_writable_state_rejected(self):
        unsafe = self.base / 'unsafe'; unsafe.mkdir(); unsafe.chmod(0o777)
        with self.assertRaisesRegex(g.ThemeError, 'not group/world writable'):
            g.Manager(unsafe)

    def test_native_and_theme_load_verification(self):
        c = self.m.config()
        with patch.object(self.m,'http',return_value=b'<html ng-app="index">'):
            g.Manager.verify(self.m,c,self.m.state())
        self.m.change('librenms',self.args)
        real_run = self.m.run
        def run(cmd):
            if 'logs' in cmd:
                return b'Extension "LibreNMS Style" (gtm-librenms) loaded.'
            return real_run(cmd)
        def http(url):
            if url.endswith('theme-marker.json'):
                return b'{"id":"librenms","version":"1.1.0"}'
            return b'<html ng-app="index">'
        with patch.object(self.m,'run',side_effect=run), patch.object(self.m,'http',side_effect=http):
            g.Manager.verify(self.m,c,self.m.state())
        c['timeout'] = .01
        with patch.object(self.m,'run',side_effect=run), patch.object(self.m,'http',return_value=b'<html ng-app="index">'), patch('time.sleep'):
            with self.assertRaisesRegex(g.ThemeError,'verification timed out'):
                g.Manager.verify(self.m,c,self.m.state())

    def test_symlink_state_rejected(self):
        link = self.base / 'link'; link.symlink_to(self.base / 'state')
        with self.assertRaisesRegex(g.ThemeError, 'Symlink'):
            g.Manager(link)

    def test_tampered_backup_rejected(self):
        self.m.change('librenms', self.args)
        bid = self.m.backup(self.m.config())
        (self.m.root / 'backups' / bid / 'active.jar').write_bytes(b'tampered')
        with self.assertRaisesRegex(g.ThemeError, 'checksum'):
            self.m.change(None, self.args, restore=bid)

    def test_non_theme_change_detected(self):
        real_restart = self.m.restart
        def restart(c):
            real_restart(c)
            self.zh.write_bytes(b'outside change')
        self.m.restart = restart
        with self.assertRaisesRegex(g.ThemeError, 'recovery could not be verified'):
            self.m.change('librenms', self.args)
        self.assertTrue(self.m.pending.exists())
        self.assertEqual(self.zh.read_bytes(), b'outside change')  # Never overwrite somebody else's change.


class ArchiveTest(unittest.TestCase):
    def test_valid_packages(self):
        for p in ROOT.glob('dist/guac-theme-*.zip'):
            g.validate_package(p.read_bytes())

    def test_traversal_absolute_windows_and_control_paths(self):
        for path in ['../escaped', '/absolute', 'a/../../escaped', 'C:/windows', 'a\\b', 'a//b', './a', 'bad\nname']:
            with self.subTest(path=path), self.assertRaises(g.ThemeError):
                g.archive(zipped({path: b'bad'}))

    def test_symlink_in_zip(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            i = zipfile.ZipInfo('link'); i.create_system = 3; i.external_attr = 0o120777 << 16
            z.writestr(i, '../outside')
        with self.assertRaisesRegex(g.ThemeError, 'special'):
            g.archive(out.getvalue())

    def test_duplicate_zip_members(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('a', b'x')
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore'); z.writestr('a', b'y')
        with self.assertRaisesRegex(g.ThemeError, 'Duplicate'):
            g.archive(out.getvalue())

    def test_zip_bomb_ratio_and_size(self):
        with self.assertRaisesRegex(g.ThemeError, 'compression ratio'):
            g.archive(zipped({'a': b'0' * 1000000}))
        with self.assertRaisesRegex(g.ThemeError, 'size limit'):
            g.archive(b'0' * (g.MAX_SIZE + 1))

    def test_checksum_tampering(self):
        original = (ROOT / 'dist/guac-theme-librenms-1.1.0.zip').read_bytes()
        files = g.archive(original); files['guacamole-librenms.jar'] += b'tamper'
        with self.assertRaisesRegex(g.ThemeError, 'checksum'):
            g.validate_package(zipped(files))

    def test_jar_tampering_even_when_outer_checksums_updated(self):
        original = (ROOT / 'dist/guac-theme-librenms-1.1.0.zip').read_bytes()
        data = package_rewrite(original, lambda f: f.update({'guacamole-librenms.jar': f['guacamole-librenms.jar'] + b'bad'}))
        with self.assertRaisesRegex(g.ThemeError, 'JAR SHA'):
            g.validate_package(data)

    def test_incompatible_metadata(self):
        original = (ROOT / 'dist/guac-theme-librenms-1.1.0.zip').read_bytes()
        def change(f):
            m = json.loads(f['theme.json']); m['guacamoleVersions'] = ['*']; f['theme.json'] = json.dumps(m).encode()
        with self.assertRaisesRegex(g.ThemeError, '1.6.0 only'):
            g.validate_package(package_rewrite(original, change))

    def test_extra_install_script_rejected(self):
        original = (ROOT / 'dist/guac-theme-librenms-1.1.0.zip').read_bytes()
        with self.assertRaisesRegex(g.ThemeError, 'Unexpected'):
            g.validate_package(package_rewrite(original, lambda f: f.update({'install.sh': b'never execute'})))

    def test_java_auth_provider_rejected(self):
        original = (ROOT / 'dist/guac-theme-librenms-1.1.0.zip').read_bytes()
        def change(f):
            jar = g.archive(f['guacamole-librenms.jar']); manifest = json.loads(jar['guac-manifest.json'])
            manifest['authProviders'] = ['malicious.Provider']; jar['guac-manifest.json'] = json.dumps(manifest).encode()
            f['guacamole-librenms.jar'] = zipped(jar)
            meta = json.loads(f['theme.json']); meta['sha256']['guacamole-librenms.jar'] = g.digest(f['guacamole-librenms.jar'])
            f['theme.json'] = json.dumps(meta).encode()
        with self.assertRaisesRegex(g.ThemeError, 'static theme'):
            g.validate_package(package_rewrite(original, change))

    def test_duplicate_json_properties(self):
        with self.assertRaisesRegex(g.ThemeError, 'Duplicate JSON'):
            g.json_read('{"id":"safe","id":"unsafe"}')

    def test_corrupt_zip(self):
        with self.assertRaisesRegex(g.ThemeError, 'damaged'):
            g.archive(b'not a zip')


if __name__ == '__main__':
    unittest.main()
