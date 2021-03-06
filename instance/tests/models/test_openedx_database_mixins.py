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
OpenEdXInstance Database Mixins - Tests
"""

# Imports #####################################################################

import subprocess
from urllib.parse import urlparse

import pymongo
import yaml
from django.conf import settings
from django.test.utils import override_settings

from instance.tests.base import TestCase
from instance.tests.models.factories.openedx_appserver import make_test_appserver
from instance.tests.models.factories.openedx_instance import OpenEdXInstanceFactory
from instance.tests.utils import patch_services


# Tests #######################################################################

class MySQLInstanceTestCase(TestCase):
    """
    Test cases for MySQLInstanceMixin and OpenEdXDatabaseMixin
    """
    def setUp(self):
        super().setUp()
        self.instance = None

    def tearDown(self):
        if self.instance:
            self.instance.deprovision_mysql()
        super().tearDown()

    def _assert_privileges(self, database):
        """
        Assert that relevant users can access database
        """
        database_name = database["name"]
        user = database["user"]
        additional_users = [user["name"] for user in database.get("additional_users", [])]
        global_users = [self.instance.migrate_user, self.instance.read_only_user]
        users = [user] + additional_users + global_users
        for user in users:
            password = self.instance._get_mysql_pass(user)
            # Pass password using MYSQL_PWD environment variable rather than the --password
            # parameter so that mysql command doesn't print a security warning.
            env = {'MYSQL_PWD': password}
            mysql_cmd = "mysql -u {user} -e 'SHOW TABLES' {db_name}".format(user=user, db_name=database_name)
            tables = subprocess.call(mysql_cmd, shell=True, env=env)
            self.assertEqual(tables, 0)

    def check_mysql(self):
        """
        Check that the mysql databases and users have been created
        """
        self.assertIs(self.instance.mysql_provisioned, True)
        self.assertTrue(self.instance.mysql_user)
        self.assertTrue(self.instance.mysql_pass)
        databases = subprocess.check_output("mysql -u root -e 'SHOW DATABASES'", shell=True).decode()
        for database in self.instance.mysql_databases:
            # Check if database exists
            database_name = database["name"]
            self.assertIn(database_name, databases)
            # Check if relevant users can access it
            self._assert_privileges(database)

    def check_mysql_vars_not_set(self, instance):
        """
        Check that the given instance does not point to a mysql database
        """
        db_vars_str = instance.get_database_settings()
        for var in ('EDXAPP_MYSQL_USER',
                    'EDXAPP_MYSQL_PASSWORD',
                    'EDXAPP_MYSQL_HOST',
                    'EDXAPP_MYSQL_PORT',
                    'EDXAPP_MYSQL_DB_NAME',
                    'COMMON_MYSQL_MIGRATE_USER',
                    'COMMON_MYSQL_MIGRATE_PASS'):
            self.assertNotIn(var, db_vars_str)

    def check_common_users(self, instance, db_vars):
        """
        Check that instance settings contain correct information about common users.
        """
        self.assertEqual(db_vars['COMMON_MYSQL_MIGRATE_USER'], instance.migrate_user)
        self.assertEqual(db_vars['COMMON_MYSQL_MIGRATE_PASS'], instance._get_mysql_pass(instance.migrate_user))
        self.assertEqual(db_vars['COMMON_MYSQL_READ_ONLY_USER'], instance.read_only_user)
        self.assertEqual(db_vars['COMMON_MYSQL_READ_ONLY_PASS'], instance._get_mysql_pass(instance.read_only_user))
        self.assertEqual(db_vars['COMMON_MYSQL_ADMIN_USER'], instance.admin_user)
        self.assertEqual(db_vars['COMMON_MYSQL_ADMIN_PASS'], instance._get_mysql_pass(instance.admin_user))

    def check_vars(self, instance, db_vars, prefix, var_names=None, values=None):
        """
        Check that instance settings contain correct values for vars that start with prefix.
        """
        if var_names is None:
            var_names = ["DB_NAME", "USER", "PASSWORD", "HOST", "PORT"]
        instance_settings = zip(var_names, values)
        for var_name, value in instance_settings:
            var_name = prefix + var_name
            self.assertEqual(db_vars[var_name], value)

    def test__get_mysql_database_name(self):
        """
        Test that _get_mysql_database_name correctly builds database names.
        """
        self.instance = OpenEdXInstanceFactory()

        # Database name should be a combination of database_name and custom suffix
        suffix = "test"
        database_name = self.instance._get_mysql_database_name(suffix)
        expected_database_name = "{0}_{1}".format(self.instance.database_name, suffix)
        self.assertEqual(database_name, expected_database_name)

        # Using suffix that exceeds maximum length should raise an error
        suffix = "long-long-long-long-long-long-long-long-long-long-long-long-suffix"
        with self.assertRaises(AssertionError):
            self.instance._get_mysql_database_name(suffix)

    def test__get_mysql_user_name(self):
        """
        Test that _get_mysql_user_name correctly builds user names.
        """
        self.instance = OpenEdXInstanceFactory()

        # User name should be a combination of mysql_user and custom suffix
        suffix = "test"
        user_name = self.instance._get_mysql_user_name(suffix)
        expected_user_name = "{0}_{1}".format(self.instance.mysql_user, suffix)
        self.assertEqual(user_name, expected_user_name)

        # Using suffix that exceeds maximum length should raise an error
        suffix = "long-long-long-suffix"
        with self.assertRaises(AssertionError):
            self.instance._get_mysql_user_name(suffix)

    def test__get_mysql_pass(self):
        """
        Test behavior of _get_mysql_pass.

        It should:

        - generate passwords of appropriate length
        - generate different passwords for different users
        - behave deterministically, i.e., return the same password for a given user
          every time it is called with that user
        """
        self.instance = OpenEdXInstanceFactory()
        user1 = "user1"
        pass1 = self.instance._get_mysql_pass(user1)
        user2 = "user2"
        pass2 = self.instance._get_mysql_pass(user2)
        self.assertEqual(len(pass1), 64)
        self.assertEqual(len(pass2), 64)
        self.assertFalse(pass1 == pass2)
        self.assertEqual(pass1, self.instance._get_mysql_pass(user1))
        self.assertEqual(pass2, self.instance._get_mysql_pass(user2))

    def test__get_database_suffix(self):
        """
        Test that _get_database_suffix returns correct suffix for a given database.
        """
        self.instance = OpenEdXInstanceFactory()
        suffix = "test"
        database_name = self.instance._get_mysql_database_name(suffix)
        self.assertEqual(self.instance._get_database_suffix(database_name), suffix)

    def test__get_template_vars(self):
        """
        Test that _get_template_vars returns correct settings for a given database.
        """
        self.instance = OpenEdXInstanceFactory()
        suffix = "test-db"
        database = {
            "name": self.instance._get_mysql_database_name(suffix),
            "user": self.instance._get_mysql_user_name(suffix),
        }
        template_vars = self.instance._get_template_vars(database)
        expected_template_vars = {
            "{}_database".format(suffix): database["name"],
            "{}_user".format(suffix): database["user"],
            "{}_pass".format(suffix): self.instance._get_mysql_pass(database["user"])
        }
        self.assertEqual(template_vars, expected_template_vars)

    def test_provision_mysql(self):
        """
        Provision mysql database
        """
        self.instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        self.instance.provision_mysql()
        self.check_mysql()

    @override_settings(INSTANCE_MYSQL_URL_OBJ=None)
    def test_provision_mysql_no_url(self):
        """
        Don't provision a mysql database if INSTANCE_MYSQL_URL is not set
        """
        self.instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        self.instance.provision_mysql()
        databases = subprocess.check_output("mysql -u root -e 'SHOW DATABASES'", shell=True).decode()
        for database in self.instance.mysql_databases:
            self.assertNotIn(database["name"], databases)

    def test_provision_mysql_weird_domain(self):
        """
        Make sure that database names are escaped correctly
        """
        sub_domain = 'really.really.really.really.long.subdomain'
        base_domain = 'this-is-a-really-long-unusual-domain-แปลกมาก.com'
        internal_lms_domain = '{}.{}'.format(sub_domain, base_domain)
        self.instance = OpenEdXInstanceFactory(use_ephemeral_databases=False,
                                               internal_lms_domain=internal_lms_domain)
        self.instance.provision_mysql()
        self.check_mysql()

    def test_provision_mysql_again(self):
        """
        Only create the database once
        """
        self.instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        self.instance.provision_mysql()
        self.assertIs(self.instance.mysql_provisioned, True)

        mysql_user = self.instance.mysql_user
        mysql_pass = self.instance.mysql_pass
        self.instance.provision_mysql()
        self.assertEqual(self.instance.mysql_user, mysql_user)
        self.assertEqual(self.instance.mysql_pass, mysql_pass)
        self.check_mysql()

    @patch_services
    @override_settings(INSTANCE_MYSQL_URL_OBJ=urlparse('mysql://user:pass@mysql.opencraft.com'))
    def test_ansible_settings_mysql(self, mocks):
        """
        Test that get_database_settings produces correct settings for MySQL databases
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        expected_host = "mysql.opencraft.com"
        expected_port = 3306

        def make_flat_group_info(var_names=None, database=None, include_port=True):
            """ Return dict containing info for a flat group of variables """
            group_info = {}
            if var_names:
                group_info["vars"] = var_names
            # Compute and insert values
            name = instance._get_mysql_database_name(database["name"])
            user = instance._get_mysql_user_name(database["user"])
            password = instance._get_mysql_pass(user)
            values = [name, user, password, expected_host]
            if include_port:
                values.append(expected_port)
            group_info["values"] = values
            return group_info

        def make_nested_group_info(var_names, databases):
            """ Return dict containing info for a nested group of variables """
            group_info = {
                "vars": var_names
            }
            # Compute and insert values
            for database in databases:
                database["name"] = instance._get_mysql_database_name(database["name"])
                database["user"] = instance._get_mysql_user_name(database["user"])
                database["password"] = instance._get_mysql_pass(database["user"])
            values = [database["name"] for database in databases]
            values.append({
                database.get("id", "default"): dict(
                    ENGINE='django.db.backends.mysql',
                    NAME=database["name"],
                    USER=database["user"],
                    PASSWORD=database["password"],
                    HOST=expected_host,
                    PORT=expected_port,
                    **database.get("additional_settings", {}),
                )
                for database in databases
            })
            group_info["values"] = values
            return group_info

        # Load instance settings
        db_vars = yaml.load(instance.get_database_settings())

        # Check instance settings for common users
        self.check_common_users(instance, db_vars)

        # Check service-specific instance settings
        var_groups = {
            "EDXAPP_MYSQL_": make_flat_group_info(database={"name": "edxapp", "user": "edxapp"}),
            "XQUEUE_MYSQL_": make_flat_group_info(database={"name": "xqueue", "user": "xqueue"}),
            "EDXAPP_MYSQL_CSMH_": make_flat_group_info(database={"name": "edxapp_csmh", "user": "edxapp"}),
            "EDX_NOTES_API_MYSQL_": make_flat_group_info(
                var_names=["DB_NAME", "DB_USER", "DB_PASS", "HOST"],
                database={"name": "edx_notes_api", "user": "notes"},
                include_port=False
            ),
            "ECOMMERCE_": make_nested_group_info(
                ["DEFAULT_DB_NAME", "DATABASES"],
                [{"name": "ecommerce", "user": "ecommerce", "additional_settings": {
                    "ATOMIC_REQUESTS": True,
                    "CONN_MAX_AGE": 60,
                }}]
            ),
            "INSIGHTS_": make_nested_group_info(
                ["DATABASE_NAME", "DATABASES"],
                [{"name": "dashboard", "user": "dashboard"}]
            ),
            "ANALYTICS_API_": make_nested_group_info(
                ["DEFAULT_DB_NAME", "REPORTS_DB_NAME", "DATABASES"],
                [{"name": "analytics_api", "user": "api"}, {"id": "reports", "name": "reports", "user": "reports"}]
            ),
        }
        for group_prefix, group_info in var_groups.items():
            values = group_info["values"]
            if "vars" in group_info:
                self.check_vars(instance, db_vars, group_prefix, var_names=group_info["vars"], values=values)
            else:
                self.check_vars(instance, db_vars, group_prefix, values=values)

    @patch_services
    @override_settings(INSTANCE_MYSQL_URL_OBJ=None)
    def test_ansible_settings_mysql_not_set(self, mocks):
        """
        Don't add mysql ansible vars if INSTANCE_MYSQL_URL is not set
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        instance.provision_mysql()
        self.check_mysql_vars_not_set(instance)

    @patch_services
    @override_settings(INSTANCE_MYSQL_URL_OBJ=urlparse('mysql://user:pass@mysql.opencraft.com'))
    def test_ansible_settings_mysql_ephemeral(self, mocks):
        """
        Don't add mysql ansible vars for ephemeral databases
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=True)
        instance.provision_mysql()
        self.check_mysql_vars_not_set(instance)


class MongoDBInstanceTestCase(TestCase):
    """
    Test cases for MongoDBInstanceMixin and OpenEdXDatabaseMixin
    """
    def setUp(self):
        super().setUp()
        self.instance = None

    def tearDown(self):
        if self.instance:
            self.instance.deprovision_mongo()
        super().tearDown()

    def check_mongo(self):
        """
        Check that the instance mongo user has access to the external mongo database
        """
        mongo = pymongo.MongoClient(settings.INSTANCE_MONGO_URL)
        for database in self.instance.mongo_database_names:
            self.assertTrue(mongo[database].authenticate(self.instance.mongo_user, self.instance.mongo_pass))

    def check_mongo_vars_not_set(self, appserver):
        """
        Check that the given OpenEdXAppServer does not point to a mongo database
        """
        for var in ('EDXAPP_MONGO_USER',
                    'EDXAPP_MONGO_PASSWORD'
                    'EDXAPP_MONGO_HOSTS',
                    'EDXAPP_MONGO_PORT',
                    'EDXAPP_MONGO_DB_NAME',
                    'FORUM_MONGO_USER',
                    'FORUM_MONGO_PASSWORD',
                    'FORUM_MONGO_HOSTS',
                    'FORUM_MONGO_PORT',
                    'FORUM_MONGO_DATABASE'):
            self.assertNotIn(var, appserver.configuration_settings)

    def test_provision_mongo(self):
        """
        Provision mongo databases
        """
        self.instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        self.instance.provision_mongo()
        self.check_mongo()

    def test_provision_mongo_no_url(self):
        """
        Don't provision any mongo databases if INSTANCE_MONGO_URL is not set
        """
        mongo = pymongo.MongoClient(settings.INSTANCE_MONGO_URL)
        with override_settings(INSTANCE_MONGO_URL=None):
            self.instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
            self.instance.provision_mongo()
            databases = mongo.database_names()
            for database in self.instance.mongo_database_names:
                self.assertNotIn(database, databases)

    def test_provision_mongo_again(self):
        """
        Only create the databases once
        """
        self.instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        self.instance.provision_mongo()
        self.assertIs(self.instance.mongo_provisioned, True)

        mongo_user = self.instance.mongo_user
        mongo_pass = self.instance.mongo_pass
        self.instance.provision_mongo()
        self.assertEqual(self.instance.mongo_user, mongo_user)
        self.assertEqual(self.instance.mongo_pass, mongo_pass)
        self.check_mongo()

    @override_settings(INSTANCE_MONGO_URL_OBJ=urlparse('mongodb://user:pass@mongo.opencraft.com'))
    def test_ansible_settings_mongo(self):
        """
        Add mongo ansible vars if INSTANCE_MONGO_URL is set
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=False)
        appserver = make_test_appserver(instance)
        ansible_vars = appserver.configuration_settings
        self.assertIn('EDXAPP_MONGO_USER: {0}'.format(instance.mongo_user), ansible_vars)
        self.assertIn('EDXAPP_MONGO_PASSWORD: {0}'.format(instance.mongo_pass), ansible_vars)
        self.assertIn('EDXAPP_MONGO_HOSTS: [mongo.opencraft.com]', ansible_vars)
        self.assertIn('EDXAPP_MONGO_PORT: 27017', ansible_vars)
        self.assertIn('EDXAPP_MONGO_DB_NAME: {0}'.format(instance.mongo_database_name), ansible_vars)
        self.assertIn('FORUM_MONGO_USER: {0}'.format(instance.mongo_user), ansible_vars)
        self.assertIn('FORUM_MONGO_PASSWORD: {0}'.format(instance.mongo_pass), ansible_vars)
        self.assertIn('FORUM_MONGO_HOSTS: [mongo.opencraft.com]', ansible_vars)
        self.assertIn('FORUM_MONGO_PORT: 27017', ansible_vars)
        self.assertIn('FORUM_MONGO_DATABASE: {0}'.format(instance.forum_database_name), ansible_vars)

    @override_settings(INSTANCE_MONGO_URL_OBJ=None)
    def test_ansible_settings_mongo_not_set(self):
        """
        Don't add mongo ansible vars if INSTANCE_MONGO_URL is not set
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=True)
        appserver = make_test_appserver(instance)
        self.check_mongo_vars_not_set(appserver)

    @override_settings(INSTANCE_MONGO_URL_OBJ=urlparse('mongodb://user:pass@mongo.opencraft.com'))
    def test_ansible_settings_mongo_ephemeral(self):
        """
        Don't add mongo ansible vars if INSTANCE_MONGO_URL is not set
        """
        instance = OpenEdXInstanceFactory(use_ephemeral_databases=True)
        appserver = make_test_appserver(instance)
        self.check_mongo_vars_not_set(appserver)
