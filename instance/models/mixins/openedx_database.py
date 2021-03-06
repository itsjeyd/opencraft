# -*- coding: utf-8 -*-
#
# OpenCraft -- tools to aid developing and hosting free software projects
# Copyright (C) 2015-2016 OpenCraft <xavier@opencraft.com>
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
Open edX instance database mixin
"""
import hashlib
import hmac
import string

from django.conf import settings
from django.template import loader
from django.utils.crypto import get_random_string

from .database import MySQLInstanceMixin, MongoDBInstanceMixin


# Classes #####################################################################

class OpenEdXDatabaseMixin(MySQLInstanceMixin, MongoDBInstanceMixin):
    """
    Mixin that provides functionality required for the database backends that an
    OpenEdX Instance uses (when not using ephemeral databases)

    TODO: ElasticSearch?
    """
    class Meta:
        abstract = True

    @property
    def mysql_database_name(self):
        """
        The mysql database name for this instance
        """
        return self.database_name

    @property
    def mysql_databases(self):
        """
        List of mysql databases
        """
        return [
            {
                "name": self._get_mysql_database_name("ecommerce"),
                "user": self._get_mysql_user_name("ecommerce"),
            },
            {
                "name": self._get_mysql_database_name("dashboard"),
                "user": self._get_mysql_user_name("dashboard"),
            },
            {
                "name": self._get_mysql_database_name("xqueue"),
                "user": self._get_mysql_user_name("xqueue"),
            },
            {
                "name": self._get_mysql_database_name("edxapp"),
                "user": self._get_mysql_user_name("edxapp"),
            },
            {
                "name": self._get_mysql_database_name("edxapp_csmh"),
                "user": self._get_mysql_user_name("edxapp"),
            },
            {
                "name": self._get_mysql_database_name("edx_notes_api"),
                "user": self._get_mysql_user_name("notes"),
                "priv": "SELECT,INSERT,UPDATE,DELETE",
            },
            {
                "name": self._get_mysql_database_name("analytics_api"),
                "user": self._get_mysql_user_name("api"),
            },
            {
                "name": self._get_mysql_database_name("reports"),
                "user": self._get_mysql_user_name("reports"),
                "priv": "SELECT",
                "additional_users": [
                    {
                        "name": self._get_mysql_user_name("api"),
                        "priv": "SELECT",
                    }
                ],
            },
        ]

    @property
    def mongo_database_name(self):
        """
        The name of the main external mongo database
        """
        return self.database_name

    @property
    def forum_database_name(self):
        """
        The name of the external database used for forums
        """
        return '{0}_forum'.format(self.database_name)

    @property
    def mongo_database_names(self):
        """
        List of mongo database names
        """
        return [self.mongo_database_name, self.forum_database_name]

    @property
    def migrate_user(self):
        """
        Name of migration user
        """
        return self._get_mysql_user_name("migrate")

    @property
    def read_only_user(self):
        """
        Name of read_only user
        """
        return self._get_mysql_user_name("read_only")

    @property
    def admin_user(self):
        """
        Name of admin user
        """
        return self._get_mysql_user_name("admin")

    @property
    def global_users(self):
        """
        List of MySQL users with global privileges (i.e., privileges spanning multiple databases)
        """
        return self.migrate_user, self.read_only_user, self.admin_user

    def _get_mysql_database_name(self, suffix):
        """
        Build unique name for MySQL database using suffix.

        To generate a unique name, this method adds an underscore and the specified suffix
        to the database_name of this instance.

        database_name can be up to 50 characters long.
        The maximum length for the name of a MySQL database is 64 characters.
        To ensure that the generated name does not exceed that length,
        suffix should not consist of more than 13 characters.
        """
        mysql_database_name = "{0}_{1}".format(self.mysql_database_name, suffix)
        assert len(mysql_database_name) <= 64
        return mysql_database_name

    def _get_mysql_user_name(self, suffix):
        """
        Build unique name for MySQL user using suffix.

        To generate a unique name, this method adds an underscore and the specified suffix
        to the mysql_user of this instance.

        mysql_user is 6 characters long.
        The maximum length of usernames in MySQL is 16 characters.
        To ensure that the generated name does not exceed that length,
        suffix must not consist of more than 9 characters.
        """
        mysql_user_name = "{0}_{1}".format(self.mysql_user, suffix)
        assert len(mysql_user_name) <= 16
        return mysql_user_name

    def _get_mysql_pass(self, user):
        """
        Build unique password for user, derived from MySQL password for this instance and user.
        """
        encoding = "utf-8"
        key = bytes(source=self.mysql_pass, encoding=encoding)
        msg = bytes(source=user, encoding=encoding)
        return hmac.new(key, msg=msg, digestmod=hashlib.sha256).hexdigest()

    def _get_database_suffix(self, name):
        """
        Return suffix that differentiates database identified by name from databases for other services.
        """
        prefix = "{prefix}_".format(prefix=self.mysql_database_name)
        return name[len(prefix):]

    def _get_template_vars(self, database):
        """
        Return dict mapping template variables to appropriate values for database.
        """
        database_name = database["name"]
        user = database["user"]

        def generate_var_name(var):
            """
            Generate appropriate name for template variable using suffix of database_name.
            """
            database_suffix = self._get_database_suffix(database_name)
            return "{database_suffix}_{var}".format(database_suffix=database_suffix, var=var)

        return {
            generate_var_name("database"): database_name,
            generate_var_name("user"): user,
            generate_var_name("pass"): self._get_mysql_pass(user),
        }

    def set_field_defaults(self):
        """
        Set default values for mysql and mongo credentials.

        Don't change existing values on subsequent calls.

        Credentials are only used for persistent databases (cf. get_database_settings).
        We generate them for all instances to ensure that app servers can be spawned successfully
        even if an instance is edited to change 'use_ephemeral_databases' from True to False.

        Note that the maximum length for the name of a MySQL user is 16 characters.
        But since we add suffixes to mysql_user to generate unique user names
        for different services (e.g. xqueue) we don't want to use the maximum length here.
        """
        if not self.mysql_user:
            self.mysql_user = get_random_string(length=6, allowed_chars=string.ascii_lowercase)
            self.mysql_pass = get_random_string(length=32)
        if not self.mongo_user:
            self.mongo_user = get_random_string(length=16, allowed_chars=string.ascii_lowercase)
            self.mongo_pass = get_random_string(length=32)

    def get_database_settings(self):
        """
        Get configuration_database_settings to pass to a new AppServer

        Only needed when not using ephemeral databases
        """
        if self.use_ephemeral_databases:
            return ''

        new_settings = ''

        # MySQL:
        if settings.INSTANCE_MYSQL_URL_OBJ:
            template = loader.get_template('instance/ansible/mysql.yml')
            context = {
                # General settings
                'host': settings.INSTANCE_MYSQL_URL_OBJ.hostname,
                'port': settings.INSTANCE_MYSQL_URL_OBJ.port or 3306,
                # Common users
                'migrate_user': self.migrate_user,
                'migrate_pass': self._get_mysql_pass(self.migrate_user),
                'read_only_user': self.read_only_user,
                'read_only_pass': self._get_mysql_pass(self.read_only_user),
                'admin_user': self.admin_user,
                'admin_pass': self._get_mysql_pass(self.admin_user),
            }
            for database in self.mysql_databases:
                context.update(self._get_template_vars(database))
            new_settings += template.render(context)

        # MongoDB:
        if settings.INSTANCE_MONGO_URL_OBJ:
            template = loader.get_template('instance/ansible/mongo.yml')
            new_settings += template.render({
                'user': self.mongo_user,
                'pass': self.mongo_pass,
                'host': settings.INSTANCE_MONGO_URL_OBJ.hostname,
                'port': settings.INSTANCE_MONGO_URL_OBJ.port or 27017,
                'database': self.mongo_database_name,
                'forum_database': self.forum_database_name
            })

        return new_settings
