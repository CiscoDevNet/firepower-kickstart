import re
import logging

from kick.device2.fxos.logical_device_handler import LogicalDeviceUtils
from kick.device2.fxos.utils import scope, create_dict
from unicon.eal.dialogs import Dialog
logger = logging.getLogger(__name__)


class LogicalDevice:
    def __init__(self, handle, name, app, slot, type):
        """
        :param handle: SSH connection handle
        :param name: logical device name; e.g. 'ftd1'
        :param app: the app associated to the logical device
        :param slot: the slot id
        :param type: logical device type; e.g. 'standalone' or clustered
        """
        self.handle = handle
        self.name = name
        self.app = app
        self.slot = slot
        self.type = type

    def create(self, interfaces, mgmt_bootstrap, cluster_bootstrap=None):
        """
        Create Logical Device
        """
        logger.info('Configuring Logical Device {}'.format(self.name))

        logger.info('Configure interfaces for app')
        for interface in interfaces:
            self.create_external_port_link(interface, commit=False)

        self.scope_to_ld()
        if cluster_bootstrap is not None:
            cluster_bootstrap.configure()
        mgmt_bootstrap.configure(slot=self.slot, app_name=self.app.app_name)

        self.scope_to_ld()
        logger.info('LD Configuration before Commit')
        self.handle.execute('show configuration')
        output = self.handle.execute('commit-buffer')
        if 'Error' in output:
            logger.info("Failed while creating logical device with error: {}".format(output))
            raise Exception("Failed while creating logical device")
        self.verify_ld()
        self.handle.execute('discard-buffer')

    def scope_to_ld(self):
        """
        Scope into ld configuration
        """
        scope(self.handle, 'ssa')
        self.handle.execute(
            'enter logical-device {} {} {} {}'.format(self.name, self.app.app_name, self.slot, self.type))

    def create_external_port_link(self, interface, commit=True, move_to_scope=True):
        """
        create external port link for interface
        :param interface: interface
        :param commit: if True it will commit buffer
        :param move_to_scope: True if we need to move to scope
        """
        if move_to_scope:
            self.scope_to_ld()
        intf_name = self.generate_int_name(interface.hardware)
        logger.info(
            'Configuring External Port Link Interface:{}\tname:{}\tapp:{}\n'.format(interface.hardware, intf_name,
                                                                                    self.app.app_name))
        self.handle.execute(
            'enter external-port-link {} {} {}'.format(intf_name, interface.hardware, self.app.app_name))
        self.handle.execute('up')
        if commit:
            output = self.handle.execute('commit-buffer')
            if 'Error' in output:
                logger.info("Failed while adding interface with error: {}".format(output))
                raise Exception("Failed while adding interface")

    def generate_int_name(self, hardware):
        """
        Generate interface name for external port link configuration
        """
        port_name = 'pc-' if 'Port-channel' in hardware else 'eth'
        return re.sub('/', '-', re.sub('Ethernet|Port-channel', port_name, hardware))

    def remove_external_port_link(self, interface, commit=True):
        """
        create external port link for interface
        :param interface: interface
        :param commit: if True it will commit buffer
        """
        self.scope_to_ld()
        intf_name = self.get_interface_name(interface.hardware)
        logger.info('Removing External Port Link Interface:{}\tname:{}\n'.format(interface.hardware, intf_name))
        output = self.handle.execute('delete external-port-link {}'.format(intf_name))
        if 'Error' in output:
            logger.info("Failed while removing external-port-link with error: {}".format(output))
            raise Exception("Failed while removing interface")
        if commit:
            output = self.handle.execute('commit-buffer')
            if 'Error' in output:
                logger.info("Failed while removing interface with error: {}".format(output))
                raise Exception("Failed while removing interface")

    def get_interface_name(self, hardware):
        """
        Get the interface name for external port link configuration
        """
        output = self.handle.execute('show external-port-link')
        pattern = '(\S+)\s+{}\s+.*'.format(hardware)
        match = re.search(pattern, output)
        if match:
            return match.group(1)
        else:
            raise Exception("Cannot determine the external-port name")

    def verify_ld(self):
        """
        Verify Logical Device is online
        :param handle: SSP handle
        :param ld_name: logical device name
        :return:
        """
        logger.info('Verifying LD Status')
        self.scope_to_ld()
        retry = 5
        while retry > 0:
            retry = retry - 1
            try:
                output = self.handle.execute('show detail', timeout=30)
                assert 'Oper State: Ok' in output, 'LD Oper state is not Ok'
                assert 'Switch Configuration Status: Ok' in output, 'LD Switch Configuration Status is not Ok'
                return
            except:
                logger.info("Retrying the command")
                pass
        raise Exception("The Logical device is not created")

    def delete(self):
        """
        delete logical device
        """
        logical_device_handler = LogicalDeviceUtils(self.handle)
        logical_device_handler.delete_ld_by_name(self.name)

    def cleanup_ld(self):
        """
        delete logical device and application
        """
        self.delete()
        self.app.delete()

    def get_ld_detail(self, move_to_scope=True):
        """
        Get logical device detail
        """
        if move_to_scope:
            self.scope_to_ld()
        return create_dict(self.handle.execute('show detail', timeout=30))
