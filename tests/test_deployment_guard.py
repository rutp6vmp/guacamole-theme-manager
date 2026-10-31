"""G04: real Manager transactions with a synthetic Docker command boundary."""
import argparse
from unittest.mock import patch
from test_manager import ManagerFixture, g


class DeploymentGuardTest(ManagerFixture):
    def protect(self, **changes):
        values = dict(compose_file=None, require_feature=['totp'], protect_extension=None)
        values.update(changes)
        self.m.protect_deployment(argparse.Namespace(**values))

    def test_adopt_overlay_while_active_and_keep_security_through_restore(self):
        self.m.change('librenms', self.args)
        backup = self.m.backup(self.m.config())
        active = (self.ext / g.MANAGED).read_bytes()
        overlay = self.base / 'security.json'; overlay.write_text('{}')
        self.m.runtime_files = [str(self.compose), str(overlay)]
        self.m.web_env = {'TOTP_ENABLED': 'true', 'RECORDING_ENABLED': 'true'}
        before = len(self.m.calls)
        self.protect(compose_file=self.m.runtime_files, require_feature=['totp', 'recording'], protect_extension=['jdbc.jar'])
        self.assertFalse(any('up' in x for x in self.m.calls[before:]))
        self.assertEqual((self.ext / g.MANAGED).read_bytes(), active)
        for name in ['dark', 'default']:
            self.m.change(name, self.args)
        self.m.change(None, self.args, restore=backup)
        self.assertEqual(self.m.state()['id'], 'librenms')
        for command in self.m.calls[before:]:
            if command[:2] == ['docker', 'compose']:
                self.assertIn(str(overlay), command)
        self.assertEqual(self.m.config()['deploymentGuard']['features'], ['recording', 'totp'])
        self.assert_preserved()

    def test_missing_live_overlay_refuses_before_theme_mutation(self):
        self.m.runtime_files = [str(self.compose), '/not-loaded-security.yaml']
        before = self.m.config_file.read_bytes()
        with self.assertRaisesRegex(g.ThemeError, 'Runtime Compose file list differs'):
            self.m.change('librenms', self.args)
        self.assertEqual(self.m.config_file.read_bytes(), before)
        self.assertFalse((self.ext / g.MANAGED).exists())
        self.assertFalse(any('up' in c for c in self.m.calls))

    def test_disabled_security_refuses_reset_before_mutation(self):
        self.m.web_env = {'TOTP_ENABLED': 'true'}; self.protect()
        self.m.change('librenms', self.args)
        before = (self.ext / g.MANAGED).read_bytes()
        for environment in [{}, {'TOTP_ENABLED': 'false'}, {'TOTP_ENABLED': 'TRUE'}]:
            self.m.web_env = environment
            with self.assertRaisesRegex(g.ThemeError, 'Required security feature'):
                self.m.change('default', self.args)
            self.assertEqual((self.ext / g.MANAGED).read_bytes(), before)

    def test_runtime_security_must_also_match(self):
        self.m.web_env = {'TOTP_ENABLED': 'true'}
        self.m.runtime_env = {'TOTP_ENABLED': 'false'}
        before = self.m.config_file.read_bytes()
        with self.assertRaisesRegex(g.ThemeError, 'Required security feature'):
            self.protect()
        self.assertEqual(self.m.config_file.read_bytes(), before)

    def test_guard_cannot_be_weakened_by_adoption_or_configure(self):
        self.m.web_env = {'TOTP_ENABLED': 'true'}; self.protect()
        self.protect(require_feature=[])
        self.assertEqual(self.m.config()['deploymentGuard']['features'], ['totp'])
        with self.assertRaisesRegex(g.ThemeError, 'Protected deployment'):
            self.m.configure(argparse.Namespace())

    def test_security_jar_pin_detects_change_or_removal(self):
        self.protect(require_feature=[], protect_extension=['jdbc.jar'])
        for changed in [b'modified', None]:
            if changed is None:
                self.auth.unlink()
            else:
                self.auth.write_bytes(changed)
            with self.assertRaisesRegex(g.ThemeError, 'missing/modified'):
                self.m.change('librenms', self.args)
        self.assertFalse((self.ext / g.MANAGED).exists())

    def test_restart_rechecks_security(self):
        self.m.web_env = {'TOTP_ENABLED': 'true'}; self.protect()
        c = self.m.config(); self.m.preflight(c)
        self.m.web_env = {'TOTP_ENABLED': 'false'}
        with self.assertRaisesRegex(g.ThemeError, 'Required security feature'):
            self.m.restart(c)
        self.assertFalse(any('up' in x for x in self.m.calls))

    def test_pending_rejects_security_adoption(self):
        g.write_json(self.m.pending, {})
        with self.assertRaisesRegex(g.ThemeError, 'Recover'):
            self.protect()

    def test_requirements_do_not_store_environment_secrets(self):
        self.m.web_env = {'TOTP_ENABLED': 'true', 'POSTGRESQL_PASSWORD': 'synthetic-do-not-copy'}
        self.protect()
        self.assertNotIn('synthetic-do-not-copy', self.m.config_file.read_text())
        self.assertEqual(set(self.m.config()['deploymentGuard']), {'schemaVersion', 'features', 'extensions'})

    def test_failed_load_verification_keeps_previous_manifest(self):
        self.m.web_env = {'TOTP_ENABLED': 'true'}
        before = self.m.config_file.read_bytes()
        with patch.object(self.m, 'verify', side_effect=g.ThemeError('Web/theme load verification timed out')):
            with self.assertRaises(g.ThemeError):
                self.protect()
        self.assertEqual(self.m.config_file.read_bytes(), before)
        self.assertFalse(any('up' in x for x in self.m.calls))
