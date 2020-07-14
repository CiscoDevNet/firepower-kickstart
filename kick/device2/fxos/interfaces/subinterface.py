import logging

from kick.device2.fxos.interfaces.interface import Interface
from kick.device2.fxos.interfaces.physical_interface import PhysicalInterface
from kick.device2.fxos.utils import create_dict

logger = logging.getLogger(__name__)


class SubInterface(Interface):
    def __init__(self, handle, hardware, sub_interface_id):
        """
        Create a dictionary with all the required info of the interface that can be used by functions
        :param handle: ssh connection handle
        :param hardware: interface name; e.g. 'Ethernet1/1'
        :param sub_interface_id: sub Interface Id
        """
        self.handle = handle
        self.hardware = '{}.{}'.format(hardware, sub_interface_id)
        self.sub_interface_id = sub_interface_id
        self.physical_interface = PhysicalInterface(handle=handle, hardware=hardware)

    def configure(self, vlan_id=None, enabled=None, commit=True, port_type=None):
        """
        Configure Interface
        :param vlan_id: vlan id
        :param enabled: admin state True=Enabled, False=Disabled
        :param commit: commits buffer 'True|False'
        :param port_type: port type; e.g. 'data', 'data-sharing', 'mgmt', 'firepower-eventing'
        """
        logger.info('Configuring SubInterface {}'.format(self.hardware))
        self.handle.execute('top')
        assert self.physical_interface.verify_interface_present(), 'Interface {} not present'.format(
            self.physical_interface.hardware)
        self.handle.execute(self.physical_interface.scope_command)
        self.handle.execute('enter subinterface {}'.format(self.sub_interface_id))

        if port_type:
            self.handle.execute('set port-type {}'.format(port_type))
        if vlan_id:
            self.handle.execute('set vlan {}'.format(vlan_id))
        if enabled is not None:
            if enabled:
                self.handle.execute('enable')
                admin_state = 'Enabled'
            else:
                self.handle.execute('disable')
                admin_state = 'Disabled'

        if commit:
            output = self.handle.execute('commit-buffer')
            if 'Error' in output:
                logger.info(
                    "Failed while trying to configure sub interface with error: {}".format(self.hardware, output))
                raise Exception("Failed while trying to configure sub interface")
            output = create_dict(self.handle.execute('show detail'))
            assert str(output['Sub-If Id']) == str(self.sub_interface_id), \
                "Mismatch in Sub-If Id! Expected: {}, Saw: {}".format(self.sub_interface_id, output['Sub-If Id'])
            if port_type:
                if port_type.lower() == 'firepower-eventing':
                    port_type = 'Firepower Eventing'
                elif port_type.lower() == 'data':
                    port_type = 'Data'
                elif port_type.lower() == 'cluster':
                    port_type = 'Cluster'
                elif port_type.lower() == 'mgmt':
                    port_type = 'Mgmt'
                elif port_type.lower() == 'data-sharing':
                    port_type = 'Data Sharing'
                assert output['Port Type'] == port_type, \
                    "Mismatch in Port Type! Expected: '{}', Saw: '{}'".format(port_type, output['Port Type'])
            if vlan_id:
                assert str(output['VLAN']) == str(vlan_id), \
                    "Mismatch in VLAN! Expected: {}, Saw: {}".format(vlan_id, output['VLAN'])
            if enabled is not None:
                assert output['Admin State'] == admin_state, \
                    "Mismatch in Admin State! Expected: {}, Saw: {}".format(admin_state, output['Admin State'])
            logger.info('Successfully Configured SubInterface {}'.format(self.hardware))
        else:
            logger.info('No commit - Didn\'t configure SubInterface {}'.format(self.hardware))

    def delete(self, commit=True):
        """
        Delete SubInterface
        :param commit: commits buffer 'True|False'
        :return:
        """
        logger.info('Deleting SubInterface {}'.format(self.hardware))
        if not self.verify_interface_present():
            logger.info('Interface {} not present; have nothing to delete'.format(self.hardware))
            return True
        self.handle.execute('delete subinterface {}'.format(self.sub_interface_id))
        if commit:
            output = self.handle.execute('commit-buffer')
            if 'Error' in output:
                logger.info("Failed while trying to delete subinterface with error: {}".format(output))
                raise Exception("Failed while trying to delete subinterface")
            assert not self.verify_interface_present(), 'Subinterface {} is present after delete'.format(self.hardware)
            logger.info('Successfully deleted SubInterface {}'.format(self.hardware))
        else:
            logger.info('No commit - Didn\'t configure SubInterface {}'.format(self.hardware))

    def verify_interface_present(self):
        if not self.physical_interface.verify_interface_present():
            logger.info('Physical interface {} not present'.format(self.physical_interface.hardware))
            return False
        self.handle.execute(self.physical_interface.scope_command)
        output = self.handle.execute('show subinterface')
        if ' {} '.format(self.hardware) in output:
            return True
        return False

    def enable(self):
        """
        enable interface
        """
        logger.info('Enabling Sub Interface {}'.format(self.hardware))
        assert self.verify_interface_present(), 'SubInterface {} not present'.format(self.hardware)
        self.handle.execute('enter subinterface {}'.format(self.sub_interface_id))
        self.handle.execute('enable')
        output = self.handle.execute('commit-buffer')
        if 'Error' in output:
            logger.info("Failed while trying to enable interface {} with error: {}".format(self.hardware, output))
            raise Exception("Failed while trying to enable interface")
        assert self._check_interface_enabled(), 'Failed to enable interface {}'.format(self.hardware)
        logger.info('Successfully enabled interface {}'.format(self.hardware))

    def disable(self):
        """
        disable interface
        """
        logger.info('Disabling Sub Interface {}'.format(self.hardware))
        assert self.verify_interface_present(), 'SubInterface {} not present'.format(self.hardware)
        self.handle.execute('enter subinterface {}'.format(self.sub_interface_id))
        self.handle.execute('disable')
        self.handle.execute('commit-buffer')
        assert not self._check_interface_enabled(), 'Failed to disable interface {}'.format(self.hardware)
        logger.info('Successfully disabled interface {}'.format(self.hardware))

    def verify_interface_enabled(self):
        """
        verify interface is enabled
        :return: True if interface is Enabled
        """
        assert self.verify_interface_present(), 'SubInterface {} not present'.format(self.hardware)
        self.handle.execute('enter subinterface {}'.format(self.sub_interface_id))
        return self._check_interface_enabled()

    def get_details(self):
        """
        gets the attributes associated with the interface in a dict
        """
        self.handle.execute('top')
        assert self.verify_interface_present(), 'SubInterface {} not present'.format(self.hardware)
        self.handle.execute('scope interface {}'.format(self.hardware))
        self.handle.execute('enter subinterface {}'.format(self.sub_interface_id))
        output = create_dict(self.handle.execute('show detail'))
        return output

    def reset(self):
        """
        Removes configurations.
        """
        return self.configure(port_type='Data', enabled=True, commit=True)
