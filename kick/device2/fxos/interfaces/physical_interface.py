import logging
import re

from kick.device2.fxos.interfaces.interface import Interface
from kick.device2.fxos.utils import create_dict, scope

logger = logging.getLogger(__name__)


class PhysicalInterface(Interface):
    def __init__(self, handle, hardware):
        """
        Create a dictionary with all the required info of the interface that can be used by functions
        :param handle: ssh connection handle
        :param hardware: interface name; e.g. 'Ethernet1/1'

        """
        self.handle = handle
        self.hardware = hardware
        self.scope_command = 'scope interface {}'.format(self.hardware)

    def configure(self, port_type=None, enabled=None, commit=True):
        """
        Configure Interface
        :param port_type: port type; e.g. 'data', 'data-sharing', 'mgmt', 'firepower-eventing'
        :param enabled: admin state True=Enabled, False=Disabled; None - do nothing
        :param commit: commits buffer 'True|False'
        """
        logger.info('Configuring Interface {}'.format(self.hardware))
        self.handle.execute('top')
        assert self.verify_interface_present(), 'Interface {} not present'.format(self.hardware)
        self.handle.execute('scope interface {}'.format(self.hardware))

        if port_type:
            self.handle.execute('set port-type {}'.format(port_type))
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
                    "Failed while trying to configure physical interface {} with error: {}".format(self.hardware,
                                                                                                   output))
                raise Exception("Failed while trying to configure physical interface")
            output = create_dict(self.handle.execute('show detail'))
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
            if enabled is not None:
                assert output['Admin State'] == admin_state, \
                    "Mismatch in Admin State! Expected: '{}', Saw: '{}'".format(admin_state, output['Admin State'])
            logger.info('Successfully Configured Interface {}'.format(self.hardware))
        else:
            logger.info('No commit - Didn\'t configure Interface {}'.format(self.hardware))

    def reset(self):
        """
        Removes configurations.
        """
        return self.configure(port_type='Data', enabled=True, commit=True)

    def verify_interface_present(self):
        """
        Verify interface is present in show interface under scope eth-uplink/fabric
        :return: True/False
        """
        scope(self.handle, 'eth-uplink/fabric')
        return True if self.hardware.lower() in self.handle.execute('show interface').lower() else False

    def get_subinterfaces(self):
        """
        gets a list of subinterface names
        :return:
        """
        scope(self.handle, 'eth-uplink/fabric')
        self.handle.execute('scope interface {}'.format(self.hardware))
        output = self.handle.execute('show subinterface').split('\r\n')
        subinterfaces = []
        for i in output:
            if re.match("^\s+(\d+)\s*\w+\/\d+\.\d+", i):
                match = re.match("^\s+(\d+)\s*\w+\/\d+\.\d+", i)
                subinterfaces.append(match.group(1))
        return subinterfaces

    def get_details(self):
        """
        gets the attributes associated with the interface in a dict
        """
        self.handle.execute('top')
        assert self.verify_interface_present(), 'Interface {} not present'.format(self.hardware)
        self.handle.execute('scope interface {}'.format(self.hardware))
        output = create_dict(self.handle.execute('show detail'))
        return output
