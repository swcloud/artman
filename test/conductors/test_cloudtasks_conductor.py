# Copyright 2017 Google
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
import json
import os
import subprocess
import unittest
import uuid

from googleapiclient.http import HttpMockSequence
from googleapiclient.discovery import build_from_document
import mock

from artman.cli import main
from artman.conductors import cloudtasks_conductor


class ConductorTests(unittest.TestCase):

    _FAKE_PULL_TASKS_RESPONSE = json.dumps({
        'tasks': [
            {
                'name': 'projects/foo/locations/bar/queues/baz/tasks/fake',
                'pullTaskTarget': {
                    # Decoded string is "--api pubsub --lang python"
                    'payload': 'LS1hcGkgcHVic3ViIC0tbGFuZyBweXRob24='
                    },
                'taskStatus': {
                    'attemptDispatchCount': '0'
                    },
                'scheduleTime': '',
                'view': 'FULL'
            }
        ]
    })

    _FAKE_PULL_TASKS_RESPONSE_WITH_ATTEMPTS = json.dumps({
        'tasks': [
            {
                'name': 'projects/foo/locations/bar/queues/baz/tasks/fake',
                'pullTaskTarget': {
                    # Decoded string is "--api pubsub --lang python"
                    'payload': 'LS1hcGkgcHVic3ViIC0tbGFuZyBweXRob24='
                    },
                'taskStatus': {
                    'attemptDispatchCount': '4'
                    },
                'scheduleTime': '',
                'view': 'FULL'
            }
        ]
    })

    _FAKE_ACK_TASK_RESPONSE = json.dumps({})

    _FAKE_DELETE_TASK_RESPONSE = json.dumps({})

    _FAKE_CANCEL_TASK_LEASE_RESPONSE = json.dumps({
        'name': 'projects/foo/locations/bar/queues/baz/tasks/fake'
    })

    _FAKE_QUEUE_NAME = 'projects/foo/locations/bar/queues/baz'

    @mock.patch.object(cloudtasks_conductor, '_prepare_dir')
    @mock.patch.object(main, 'main')
    @mock.patch.object(cloudtasks_conductor, '_write_to_cloud_logging')
    @mock.patch.object(cloudtasks_conductor, '_cleanup')
    def test_execute_task_succeed(self, cleanup, write_to_cloud_logging,
                                  cli_main, prepare_dir):
        http = HttpMockSequence([
            ({'status': '200'}, self._FAKE_PULL_TASKS_RESPONSE),
            ({'status': '200'}, self._FAKE_ACK_TASK_RESPONSE),
        ])

        client = self._create_cloudtasks_client_testing(http=http)
        prepare_dir.return_value = (
            'task_id', '/tmp', '/tmp/artman-config.yaml', '/tmp/artman.log')
        write_to_cloud_logging.return_value = None
        cleanup.return_value = None

        cloudtasks_conductor._pull_and_execute_tasks(
            task_client=client,
            queue_name=self._FAKE_QUEUE_NAME)
        cli_main.assert_called_once_with(
            u'--api', u'pubsub', u'--lang', u'python', '--user-config',
            '/tmp/artman-config.yaml')
        # Make sure ack is called when the task execution succeeds.
        cleanup.assert_called_once()
        write_to_cloud_logging.assert_called_with('task_id', '/tmp/artman.log')

    @mock.patch.object(cloudtasks_conductor, '_prepare_dir')
    @mock.patch.object(cloudtasks_conductor, '_delete_task')
    @mock.patch.object(cloudtasks_conductor, '_write_to_cloud_logging')
    @mock.patch.object(cloudtasks_conductor, '_cleanup')
    def test_execute_task_exceeding_max_attmpts(self, cleanup,
                                                write_to_cloud_logging,
                                                delete_task, prepare_dir):
        http = HttpMockSequence([
            ({'status': '200'}, self._FAKE_PULL_TASKS_RESPONSE_WITH_ATTEMPTS),
            ({'status': '200'}, self._FAKE_DELETE_TASK_RESPONSE),
        ])
        client = self._create_cloudtasks_client_testing(http=http)
        prepare_dir.return_value = (
            'task_id', '/tmp', '/tmp/artman-config.yaml', '/tmp/artman.log')
        write_to_cloud_logging.return_value = None
        cleanup.return_value = None

        cloudtasks_conductor._pull_and_execute_tasks(
            task_client=client,
            queue_name=self._FAKE_QUEUE_NAME)
        delete_task.assert_called_once()
        cleanup.assert_called_once()
        write_to_cloud_logging.assert_called_with('task_id', '/tmp/artman.log')

    @mock.patch.object(cloudtasks_conductor, '_prepare_dir')
    @mock.patch.object(main, 'main')
    @mock.patch.object(cloudtasks_conductor, '_write_to_cloud_logging')
    @mock.patch.object(cloudtasks_conductor, '_cleanup')
    def test_execute_task_fail(self, cleanup, write_to_cloud_logging,
                               cli_main, prepare_dir):
        http = HttpMockSequence([
            ({'status': '200'}, self._FAKE_PULL_TASKS_RESPONSE),
            ({'status': '200'}, self._FAKE_CANCEL_TASK_LEASE_RESPONSE),
        ])
        client = self._create_cloudtasks_client_testing(http=http)
        prepare_dir.return_value = (
            'task_id', '/tmp', '/tmp/artman-config.yaml', '/tmp/artman.log')
        cli_main.side_effect = RuntimeError('abc')
        write_to_cloud_logging.return_value = None
        cleanup.return_value = None

        cloudtasks_conductor._pull_and_execute_tasks(
            task_client=client,
            queue_name=self._FAKE_QUEUE_NAME)
        cli_main.assert_called_once_with(
            u'--api', u'pubsub', u'--lang', u'python', '--user-config',
            '/tmp/artman-config.yaml')
        # Make sure cancel is called when the task execution fails.
        cleanup.assert_called_once()
        write_to_cloud_logging.assert_called_with('task_id', '/tmp/artman.log')

    @mock.patch.object(os, 'makedirs')
    @mock.patch.object(uuid, 'uuid4')
    @mock.patch.object(subprocess, 'check_output')
    def test_prepare_dir(self, check_output, uuid4, os_mkdir):
        uuid4.return_value = uuid.UUID('00000000-0000-0000-0000-000000000000')
        artman_user_config_mock = mock.mock_open()
        os_mkdir.return_value = None
        check_output.return_value = b'dummy output'
        with mock.patch('io.open', artman_user_config_mock, create=True):
            cloudtasks_conductor._prepare_dir()
            os_mkdir.assert_called_once_with(
                '/tmp/artman/00000000')
            handler = artman_user_config_mock()
            handler.write.assert_called()

    def _create_cloudtasks_client_testing(self, http):
        with open(
            os.path.join(os.path.dirname(__file__),
                         '../../artman/conductors/cloudtasks.json'), 'r') as f:
                return build_from_document(f.read(),  http=http)
