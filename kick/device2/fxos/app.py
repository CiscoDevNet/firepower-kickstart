import logging

import time

from kick.device2.fxos.app_handler import AppInstanceUtils
from kick.device2.fxos.utils import create_dict, scope, poll

logger = logging.getLogger(__name__)


class AppInstance:
    slot_handler = None
    mi_supported = False

    def __init__(self, handle, app_name, slot, identifier=""):
        """
        Constructor of App Instance
        :param handle: SSH connection handle
        :param app_name: application instance name; e.g. 'ftd'
        :param slot: slot id; e.g. '1', '2'
        :param identifier: identifier or logical device name; e.g. 'ftd1'
        """
        self.handle = handle
        self.app_name = app_name
        self.slot = str(slot)
        self.identifier = identifier
        if self.slot == "":
            raise ValueError('Slot is mandatory and was sent as empty string')
        self.is_mi_supported()

    def get_slot_handler(self):
        if not self.slot_handler:
            self.slot_handler = AppInstanceUtils(handle=self.handle, slot=self.slot)
        return self.slot_handler

    def create(self, deploy_type="native", version=None, resource_profile=None, hw_crypto_state=None):
        """
        Create app instance
        :param deploy_type: deploy type; e.g. 'native', 'container'
        :param version: version; e.g. '6.3.0.10396'
        :param resource_profile: the resource profile name
        :return:
        """
        self.handle.execute("top")
        self.handle.execute("discard-buffer")

        logger.info("Enable license for CSP")
        self.handle.execute("top")
        self.handle.execute("scope ssa")
        self.handle.execute("scope app ftd {}".format(version))
        self.handle.execute("accept-license-agreement", timeout=60)
        output = self.handle.execute("commit-buffer")
        if 'Error' in output:
            raise Exception("Failed to enable FTD license")
        output = self.handle.execute("show detail", timeout=60)
        if 'Has License Agreement: Yes' not in output or 'License Agreement has been Accepted: Yes' not in output:
            raise Exception("Failed to enable FTD license")

        self.handle.execute("scope ssa")
        self.handle.execute("scope slot " + self.slot)

        if self.mi_supported:
            if self.identifier == "":
                raise Exception('Identifier not provided, which is mandatory in the new MI builds even for native apps')

            output = self.handle.execute("create app-instance " + self.app_name + " " + self.identifier)
            if 'Error' in output:
                logger.info("Failed while creating app instance with error: {}".format(output))
                raise Exception("Failed while creating app instance")
            self.handle.execute("set deploy-type " + deploy_type)
        else:
            self.handle.execute("create app-instance " + self.app_name)

        if version:
            output = self.handle.execute('set startup-version ' + version)
            if 'Error' in output or 'Warning' in output:
                logger.info(
                    "Failed while adding startup-version to application instance with error: {}".format(
                        output))
                raise Exception("Failed while creating app instance")
        if resource_profile:
            output = self.handle.execute('set resource-profile-name ' + resource_profile)
            if 'Error' in output or 'Warning' in output:
                logger.info(
                    "Failed while adding resource profile to application instance with error: {}".format(output))
                raise Exception("Failed while creating app instance")
        if hw_crypto_state:
            output = self.handle.execute('create hw-crypto')
            if 'Error' in output or 'Warning' in output:
                logger.info(
                    "Failed while setting hw crypto to application instance with error: {}".format(output))
                raise Exception("Failed while creating app instance")
            self.handle.execute("set admin-state "+ hw_crypto_state)
            self.handle.execute('exit')
        output = self.handle.execute("commit-buffer")
        if 'Error' in output:
            logger.info("Failed while creating app instance with error: {}".format(output))
            raise Exception("Failed while creating app instance")
        self.handle.execute("discard-buffer")

    def disable(self):
        """
        Disable Application Instance
        :return:
        """
        if self.get_app_instance_detail():
            scope(self.handle, 'app-instance {} {}'.format(self.app_name, self.identifier))
            self.handle.execute('disable')
            output = self.handle.execute("commit")
            if 'Error' in output:
                logger.info("Failed while trying to {} instance with error: {}".format('disable', output))
                raise Exception("Failed while enabling or disabling the app instance")
            self.handle.execute("discard-buffer")
            assert poll(self.handle, command='sh detail',
                        expect='Admin State: Disabled +Oper State: Offline',
                        max_retry=50,
                        interval=15), "App Instance Not Online"
        else:
            raise Exception("The app is not present. Cannot disable it!")

    def enable(self):
        """
        Enable Application Instance
        :return:
        """
        if self.get_app_instance_detail():
            scope(self.handle, 'app-instance {} {}'.format(self.app_name, self.identifier))
            self.handle.execute('enable')
            self.handle.execute("commit")
            self.handle.execute("discard-buffer")
            step = 0
            while step < 50:
                logger.info('Checking if enable - {} try'.format(step))
                if self.check_status(move_to_scope=False):
                    return True
                time.sleep(15)
                step += 1
            raise Exception("The app is not enabled!")
        else:
            raise Exception("The app is not present. Cannot enable it!")

    def check_status(self, move_to_scope=True):
        """
        Check status
        :return:
        """
        if move_to_scope:
            scope(self.handle, 'ssa/slot {}'.format(self.slot))
            scope(self.handle, 'app-instance {} {}'.format(self.app_name, self.identifier))
        output = self.handle.execute('sh detail')
        if 'Admin State: Enabled' in output and 'Oper State: Online' in output:
            return True
        if 'Oper State: Start Failed' in output or 'Oper State: Not Available' in output:
            raise Exception('Failed to enable app!')
        return False

    def check_status_in_loop(self, step_no=50, step_wait=30, move_to_scope=True):
        """
        Check status
        :return:
        """
        if self.get_app_instance_detail():
            if move_to_scope:
                scope(self.handle, 'ssa/slot {}'.format(self.slot))
                scope(self.handle, 'app-instance {} {}'.format(self.app_name, self.identifier))
            step = 0
            while step < step_no:
                logger.info('Checking if app is enabled and online - {} try'.format(step))
                if self.check_status(move_to_scope=False):
                    return True
                time.sleep(step_wait)
                step += 1
            raise Exception("The app is not in the correct state!")
        else:
            raise Exception("The app is not present!")

    def delete(self):
        """
        Delete Application Instance
        :return:
        """
        self.handle.execute("top")
        self.handle.execute("discard-buffer")
        self.handle.execute("scope ssa")
        self.handle.execute("scope slot " + self.slot)

        if self.mi_supported:
            if self.identifier == "":
                raise Exception("Identifier is mandatory for MI supported")
            output = self.handle.execute("delete app-instance " + self.app_name + " " + self.identifier)
        else:
            output = self.handle.execute("delete app-instance " + self.app_name)
        if 'Error' in output:
            logger.info("Failed while trying to delete app instance {} with error: {}".format(self.app_name, output))
            raise Exception("Failed while trying to delete app instance")

        self.handle.execute("commit-buffer")
        self.handle.execute("discard-buffer")

    def get_app_instance_detail(self):
        """
        Verify if app instance is present and get app details
        :return: None or Dictionary structure
        """
        self.get_slot_handler()
        for a in self.slot_handler.get_app_instances_in_slot():
            if a['App Name'] == self.app_name and a['Identifier'] == self.identifier:
                return a
        return None

    def get_app_instance_resources(self):
        """
        Gets resources allocated to app-instance
        :param slot: slot id
        :param app: app name
        :param identifier: identifier or logical device name
        :return: resources
        """
        if self.get_app_instance_detail():
            scope(self.handle, 'app-instance {} {}'.format(self.app_name, self.identifier))
            resources = create_dict(self.handle.execute('show resource detail'))
            resources['cpu'] = resources.pop('Allocated Core NR')
            resources['ram'] = resources.pop('Allocated RAM (MB)')
            resources['data_disk'] = resources.pop('Allocated Data Disk (MB)')
            resources['binary_disk'] = resources.pop('Allocated Binary Disk (MB)')
            resources['secondary_disk'] = resources.pop('Allocated Secondary Disk (MB)')
            return resources
        else:
            raise Exception("The app is not present. Cannot get resource profile information!")

    def assign_resource_profile(self, resource_profile_name):
        """
        Assigns Resource Profile
        :param resource_profile_name: resource profile name
        :return:
        """
        if self.get_app_instance_detail():
            scope(self.handle, 'app-instance {} {}'.format(self.app_name, self.identifier))
            self.handle.execute("set resource-profile-name {}".format(resource_profile_name))
            output = self.handle.execute("commit")
            if 'Error' in output:
                logger.info("Failed while trying to assign resource profile with error: {}".format(output))
                raise Exception("Failed while trying to assign resource profile")
            self.handle.execute("discard-buffer")
            output = create_dict(self.handle.execute("show detail"))
            assert output[
                       'Profile Name'] == resource_profile_name, "Mismatch in Profile Name! Expected: {}, Saw: {}".format(
                resource_profile_name, output['Profile Name'])
        else:
            raise Exception("The app is not present. Cannot add resource profile!")

    def is_mi_supported(self):
        """
        receives the self and tests if Multi instance is supported
        ways to check
        "create app-instance" and see if it takes an additional parameter

        scope app asa x.x.x.x and do "show app-info", that command is not supported in the past

        see if scope ssa, "show app" has a column with "Supported Deploy Types"
        """
        self.handle.execute("scope ssa")
        self.handle.execute("scope slot {}".format(self.slot))
        try:
            self.handle.execute("create app-instance ftd testmi")
            self.handle.execute("end")
            self.handle.execute("discard-buffer")
            logger.info("We were able to create app-instance in new format, multi instance is supported")
            self.mi_supported = True
        except Exception:
            raise Exception("MI is not supported")
