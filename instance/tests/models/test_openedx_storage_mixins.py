# -*- coding: utf-8 -*-
#
# OpenCraft -- tools to aid developing and hosting free software projects
# Copyright (C) 2015-2016 OpenCraft <contact@opencraft.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""
OpenEdXInstance Storage Mixins - Tests
"""

# Imports #####################################################################

from unittest.mock import patch, call

import yaml
from django.conf import settings
from django.test.utils import override_settings

from instance.tests.base import TestCase
from instance.tests.models.factories.openedx_appserver import make_test_appserver
from instance.tests.models.factories.openedx_instance import OpenEdXInstanceFactory


# Tests #######################################################################

class OpenEdXStorageMixinTestCase(TestCase):
    """
    Tests for OpenEdXStorageMixin
    """
    def check_s3_vars(self, yaml_vars_string):
        """
        Check the the given yaml string includes the expected Open edX S3-related vars/values
        """
        parsed_vars = yaml.load(yaml_vars_string)
        self.assertEqual(parsed_vars['AWS_ACCESS_KEY_ID'], 'test-s3-access-key')
        self.assertEqual(parsed_vars['AWS_SECRET_ACCESS_KEY'], 'test-s3-secret-access-key')
        self.assertEqual(parsed_vars['EDXAPP_AUTH_EXTRA'], {'AWS_STORAGE_BUCKET_NAME': 'test-s3-bucket-name'})
        self.assertEqual(parsed_vars['EDXAPP_AWS_ACCESS_KEY_ID'], 'test-s3-access-key')
        self.assertEqual(parsed_vars['EDXAPP_AWS_SECRET_ACCESS_KEY'], 'test-s3-secret-access-key')
        self.assertEqual(parsed_vars['XQUEUE_AWS_ACCESS_KEY_ID'], 'test-s3-access-key')
        self.assertEqual(parsed_vars['XQUEUE_AWS_SECRET_ACCESS_KEY'], 'test-s3-secret-access-key')
        self.assertEqual(parsed_vars['XQUEUE_S3_BUCKET'], 'test-s3-bucket-name')

    def test_ansible_s3_settings(self):
        """
        Test that get_storage_settings() includes S3 vars, and that they get passed on to the
        AppServer
        """
        instance = OpenEdXInstanceFactory(
            s3_access_key='test-s3-access-key',
            s3_secret_access_key='test-s3-secret-access-key',
            s3_bucket_name='test-s3-bucket-name',
            use_ephemeral_databases=False,
        )
        self.check_s3_vars(instance.get_storage_settings())
        appserver = make_test_appserver(instance)
        self.check_s3_vars(appserver.configuration_settings)

    def test_ansible_s3_settings_ephemeral(self):
        """
        Test that get_storage_settings() does not include S3 vars when in ephemeral mode
        """
        instance = OpenEdXInstanceFactory(
            s3_access_key='test-s3-access-key',
            s3_secret_access_key='test-s3-secret-access-key',
            s3_bucket_name='test-s3-bucket-name',
            use_ephemeral_databases=True,
        )
        self.assertEqual(instance.get_storage_settings(), '')


class SwiftContainerInstanceTestCase(TestCase):
    """
    Tests for Swift container provisioning.
    """
    def check_swift(self, instance, create_swift_container):
        """
        Verify Swift settings on the instance and the number of calls to the Swift API.
        """
        self.assertIs(instance.swift_provisioned, True)
        self.assertEqual(instance.swift_openstack_user, settings.SWIFT_OPENSTACK_USER)
        self.assertEqual(instance.swift_openstack_password, settings.SWIFT_OPENSTACK_PASSWORD)
        self.assertEqual(instance.swift_openstack_tenant, settings.SWIFT_OPENSTACK_TENANT)
        self.assertEqual(instance.swift_openstack_auth_url, settings.SWIFT_OPENSTACK_AUTH_URL)
        self.assertEqual(instance.swift_openstack_region, settings.SWIFT_OPENSTACK_REGION)

        def make_call(container_name):
            """A helper method to prepare mock.call."""
            return call(
                container_name,
                user=instance.swift_openstack_user,
                password=instance.swift_openstack_password,
                tenant=instance.swift_openstack_tenant,
                auth_url=instance.swift_openstack_auth_url,
                region=instance.swift_openstack_region,
            )

        self.assertCountEqual(
            [make_call(container) for container in instance.swift_container_names],
            create_swift_container.call_args_list,
        )

    @patch('instance.openstack.create_swift_container')
    def test_provision_swift(self, create_swift_container):
        """
        Test provisioning Swift containers, and that they are provisioned only once.
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        instance.provision_swift()
        self.check_swift(instance, create_swift_container)

        # Provision again without resetting the mock.  The assertCountEqual assertion will verify
        # that the container isn't provisioned again.
        instance.provision_swift()
        self.check_swift(instance, create_swift_container)

    @patch('instance.openstack.create_swift_container')
    @override_settings(SWIFT_ENABLE=False)
    def test_swift_disabled(self, create_swift_container):
        """
        Verify disabling Swift provisioning works.
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        instance.provision_swift()
        self.assertIs(instance.swift_provisioned, False)
        self.assertFalse(create_swift_container.called)

    def check_ansible_settings(self, appserver, expected=True):
        """
        Verify the Ansible settings.
        """
        expected_settings = {
            'EDXAPP_SWIFT_USERNAME': 'swift_openstack_user',
            'EDXAPP_SWIFT_KEY': 'swift_openstack_password',
            'EDXAPP_SWIFT_TENANT_NAME': 'swift_openstack_tenant',
            'EDXAPP_SWIFT_AUTH_URL': 'swift_openstack_auth_url',
            'EDXAPP_SWIFT_REGION_NAME': 'swift_openstack_region',
        }
        ansible_vars = appserver.configuration_settings
        for ansible_var, attribute in expected_settings.items():
            if expected:
                self.assertIn('{}: {}'.format(ansible_var, getattr(appserver.instance, attribute)), ansible_vars)
            else:
                self.assertNotIn(ansible_var, ansible_vars)

    def test_ansible_settings_swift(self):
        """
        Verify Swift Ansible configuration when Swift is enabled.
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        appserver = make_test_appserver(instance)
        self.check_ansible_settings(appserver)

    @override_settings(SWIFT_ENABLE=False)
    def test_ansible_settings_swift_disabled(self):
        """
        Verify Swift Ansible configuration is not included when Swift is disabled.
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        appserver = make_test_appserver(instance)
        self.check_ansible_settings(appserver, expected=False)

    def test_ansible_settings_swift_ephemeral(self):
        """
        Verify Swift Ansible configuration is not included when using ephemeral databases.
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=True)
        appserver = make_test_appserver(instance)
        self.check_ansible_settings(appserver, expected=False)
