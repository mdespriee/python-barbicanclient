# Copyright (c) 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys

import six
import testtools
import httpretty
import uuid
import json

from barbicanclient.test import keystone_client_fixtures
from barbicanclient.test import test_client
import barbicanclient.barbican


class WhenTestingBarbicanCLI(test_client.BaseEntityResource):

    def setUp(self):
        self._setUp('barbican')
        self.global_file = six.StringIO()

    def barbican(self, argstr):
        """Source: Keystone client's shell method in test_shell.py"""
        clean_env = {}
        _old_env, os.environ = os.environ, clean_env.copy()
        exit_code = 1
        try:
            stdout = self.global_file
            _barbican = barbicanclient.barbican.Barbican(stdout=stdout,
                                                         stderr=stdout)
            exit_code = _barbican.run(argv=argstr.split())
        except Exception as exception:
            exit_message = exception.message
        finally:
            out = stdout.getvalue()
            os.environ = _old_env
        return exit_code, out

    def test_should_show_usage_error_with_no_args(self):
        args = ""
        exit_code, out = self.barbican(args)
        self.assertEqual(1, exit_code)
        self.assertIn('usage:', out)

    def test_should_show_usage_with_help_flag(self):
        args = "-h"
        exit_code, out = self.barbican(args)
        self.assertEqual(0, exit_code)
        self.assertIn('usage: ', out)

    def test_should_error_if_noauth_and_authurl_both_specified(self):
        args = "--no-auth --os-auth-url http://localhost:5000/v3"
        exit_code, out = self.barbican(args)
        self.assertEqual(1, exit_code)
        self.assertIn(
            'ERROR: argument --os-auth-url/-A: not allowed with '
            'argument --no-auth/-N', out)

    def _expect_error_with_invalid_noauth_args(self, args):
        exit_code, out = self.barbican(args)
        self.assertEqual(1, exit_code)
        expected_err_msg = 'ERROR: please specify --endpoint '\
                           'and --os-project-id(or --os-tenant-id)\n'
        self.assertIn(expected_err_msg, out)

    def test_should_error_if_noauth_and_missing_endpoint_tenantid_args(self):
        self._expect_error_with_invalid_noauth_args("--no-auth secret list")
        self._expect_error_with_invalid_noauth_args(
            "--no-auth --endpoint http://xyz secret list")
        self._expect_error_with_invalid_noauth_args(
            "--no-auth --os-tenant-id 123 secret list")
        self._expect_error_with_invalid_noauth_args(
            "--no-auth --os-project-id 123 secret list")

    def _expect_success_code(self, args):
        exit_code, out = self.barbican(args)
        self.assertEqual(0, exit_code)

    def _expect_failure_code(self, args, code=1):
        exit_code, out = self.barbican(args)
        self.assertEqual(code, exit_code)

    def _assert_status_code_and_msg(self, args, expected_msg, code=1):
        exit_code, out = self.barbican(args)
        self.assertEqual(code, exit_code)
        self.assertIn(expected_msg, out)

    @httpretty.activate
    def test_should_succeed_if_noauth_with_valid_args_specified(self):
        list_secrets_content = '{"secrets": [], "total": 0}'
        list_secrets_url = '%s%s/secrets' % (
            self.endpoint, self.tenant_id)
        httpretty.register_uri(
            httpretty.GET, list_secrets_url,
            body=list_secrets_content)
        self._expect_success_code(
            "--no-auth --endpoint %s --os-tenant-id %s secret list"
            % (self.endpoint, self.tenant_id))

    def test_should_error_if_required_keystone_auth_arguments_are_missing(
            self):
        expected_error_msg = 'ERROR: please specify authentication credentials'
        self._assert_status_code_and_msg(
            '--os-auth-url http://localhost:35357/v2.0 secret list',
            expected_error_msg)
        self._assert_status_code_and_msg('--os-auth-url '
                                         'http://localhost:35357/v2.0 '
                                         '--os-username barbican '
                                         '--os-password barbican '
                                         'secret list', expected_error_msg)


class TestBarbicanWithKeystoneClient(testtools.TestCase):

    def setUp(self):
        super(TestBarbicanWithKeystoneClient, self).setUp()
        self.kwargs = {'auth_url': keystone_client_fixtures.V3_URL}
        for arg in ['username', 'password', 'project_name',
                    'user_domain_name', 'project_domain_name']:
            self.kwargs[arg] = uuid.uuid4().hex
        self.barbican = barbicanclient.barbican.Barbican()

    def _to_argv(self, **kwargs):
        """Format Keystone client arguments into command line argv."""
        argv = []
        for k, v in six.iteritems(kwargs):
            argv.append('--os-' + k.replace('_', '-'))
            argv.append(v)
        return argv

    @httpretty.activate
    def test_v2_auth(self):
        self.kwargs['auth_url'] = keystone_client_fixtures.V2_URL
        argv = self._to_argv(**self.kwargs)
        argv.append('secret')
        argv.append('list')
        argv.append('-h')
        argv.append('mysecretid')
        # emulate Keystone version discovery
        httpretty.register_uri(httpretty.GET,
                               self.kwargs['auth_url'],
                               body=keystone_client_fixtures.V2_VERSION_ENTRY)
        # emulate Keystone v2 token request
        v2_token = keystone_client_fixtures.generate_v2_project_scoped_token()
        httpretty.register_uri(httpretty.POST,
                               '%s/tokens' % (self.kwargs['auth_url']),
                               body=json.dumps(v2_token))
        # emulate get secrets
        barbican_url = keystone_client_fixtures.BARBICAN_ENDPOINT
        httpretty.register_uri(
            httpretty.DELETE,
            '%s/%s/secrets/mysecretid' % (
                barbican_url,
                v2_token['access']['token']['tenant']['id']),
            status=200)
        self.barbican.run(argv=argv)

    @httpretty.activate
    def test_v3_auth(self):
        argv = self._to_argv(**self.kwargs)
        argv.append('secret')
        argv.append('list')
        argv.append('-h')
        argv.append('mysecretid')
        # emulate Keystone version discovery
        httpretty.register_uri(httpretty.GET,
                               self.kwargs['auth_url'],
                               body=keystone_client_fixtures.V3_VERSION_ENTRY)
        # emulate Keystone v3 token request
        id, v3_token = \
            keystone_client_fixtures.generate_v3_project_scoped_token()
        httpretty.register_uri(httpretty.POST,
                               '%s/auth/tokens' % (self.kwargs['auth_url']),
                               body=json.dumps(v3_token))
        # emulate delete secret
        barbican_url = keystone_client_fixtures.BARBICAN_ENDPOINT
        httpretty.register_uri(
            httpretty.DELETE,
            '%s/%s/secrets/mysecretid' % (
                barbican_url,
                v3_token['token']['project']['id']),
            status=200)
        self.barbican.run(argv=argv)
