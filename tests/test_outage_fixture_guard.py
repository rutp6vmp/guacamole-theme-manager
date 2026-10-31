"""Lifecycle fault injection must never select an unrelated Docker container."""
import copy
import unittest

from outage_acceptance import require_fixture_service
from pam_acceptance import AcceptanceFailure


class OutageFixtureGuardTest(unittest.TestCase):
    project = 'gtm-pam-test-012345abcdef'

    def metadata(self, service='db'):
        return {'Id': 'a' * 64, 'Config': {'Labels': {
            'com.docker.compose.project': self.project,
            'com.docker.compose.service': service}}}

    def test_owned_db_and_guacd_are_accepted(self):
        for service in ['db', 'guacd']:
            self.assertEqual(require_fixture_service(self.metadata(service), self.project, service), 'a' * 64)

    def test_production_and_malformed_project_names_refused(self):
        for project in ['guacamole', 'gtm-pam-test-', self.project + '-extra', '--all']:
            info = self.metadata()
            info['Config']['Labels']['com.docker.compose.project'] = project
            with self.assertRaises(AcceptanceFailure):
                require_fixture_service(info, project, 'db')

    def test_web_ssh_and_arbitrary_services_refused(self):
        for service in ['web', 'ssh', 'postgres', '--all']:
            with self.assertRaises(AcceptanceFailure):
                require_fixture_service(self.metadata(service), self.project, service)

    def test_other_disposable_project_refused(self):
        with self.assertRaises(AcceptanceFailure):
            require_fixture_service(self.metadata(), 'gtm-pam-test-999999999999', 'db')

    def test_service_label_mismatch_refused(self):
        with self.assertRaises(AcceptanceFailure):
            require_fixture_service(self.metadata('guacd'), self.project, 'db')

    def test_missing_labels_and_untrusted_ids_refused(self):
        original = self.metadata()
        for info in [{}, {'Id': 'a' * 64, 'Config': None}, {'Id': 'a' * 64, 'Config': {'Labels': None}}]:
            with self.assertRaises(AcceptanceFailure):
                require_fixture_service(info, self.project, 'db')
        for identifier in ['', 'short', '--all', 'a' * 64 + '\n']:
            info = copy.deepcopy(original)
            info['Id'] = identifier
            with self.assertRaises(AcceptanceFailure):
                require_fixture_service(info, self.project, 'db')
