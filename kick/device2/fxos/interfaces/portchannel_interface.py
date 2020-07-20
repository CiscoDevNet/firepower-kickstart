import logging
import re

from kick.device2.fxos.interfaces.interface import Interface
from kick.device2.fxos.utils import create_dict, scope

logger = logging.getLogger(__name__)


class PortChannelInterface(Interface):
    def __init__(self, handle, hardware):
        """
        Create a dictionary with all the required info of the interface that can be used by functions
        :param handle: ssh connection handle
        :param hardware: interface name; e.g. 'Ethernet1/1'
        """
        self.handle = handle
        if 'Port-channel' in hardware:
            self.hardware = hardware
            match = re.match('Port-channel(\d+)', hardware)
            if match:
                self.port_channel_id = match.group(1)
            else:
                logger.info('Port-channel hardware name is not supported: {}'.format(hardware))
                raise Exception('Port-channel hardware name is not supported')
        else:
            self.hardware = 'Port-channel{}'.format(hardware)
            self.port_channel_id = hardware
        self.scope_command = 'scope port-channel {}'.format(self.port_channel_id)

    def configure(self, port_type=None, member_ports=None, enabled=None, commit=True):
        """
        Configure Port Channel
        :param port_type: port type; e.g. 'Data', 'Mgmt', 'firepower-eventing', 'Cluster'
        :param member_ports: list of member ports data structures
        :param enabled: admin state True=Enabled, False=Disabled
        :param commit: commits buffer 'True|False'
        """
        logger.info('Configuring Port-Channel {}'.format(self.hardware))
        if member_ports:
            for member_port_interface in member_ports:
                assert member_port_interface.verify_interface_present(), \
                    'Interface {} not present'.format(member_port_interface.hardware)

        scope(self.handle, 'eth-uplink/fabric')
        self.handle.execute('enter port-channel {}'.format(self.port_channel_id))
        if port_type:
            self.handle.execute('set port-type {}'.format(port_type))
        if member_ports:
            for member_port_interface in member_ports:
                output = self.handle.execute('create member-port {}'.format(member_port_interface.hardware))
                if 'Error' in output:
                    logger.info("Failed while trying to create member port with error: {}".format(output))
                    raise Exception("Failed while trying to create member port channel")
                self.handle.execute('up')
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
                logger.info("Failed while trying to create port channel with error: {}".format(output))
                raise Exception("Failed while trying to create port channel")
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
                    "Mismatch in Port Type! Expected: {}, Saw: {}".format(port_type, output['Port Type'])
            if enabled is not None:
                assert output['Admin State'] == admin_state, \
                    "Mismatch in Admin State! Expected: {}, Saw: {}".format(admin_state, output['Admin State'])
            if member_ports:
                output = self.handle.execute("show member-port")
                for member_port_interface in member_ports:
                    assert member_port_interface.hardware in output, "Could Not Find Member Port {}".format(
                        member_port_interface.hardware)
            logger.info('Successfully Configured Port-Channel {}'.format(self.hardware))
        else:
            logger.info('No commit - Didn\'t configure Interface {}'.format(self.hardware))

    def delete(self):
        """
        Removes portchannel interface.
        """
        logger.info('Deleting Port-Channel {}'.format(self.hardware))
        self.handle.execute('top')
        if not self.verify_interface_present():
            logger.info('Port-Channel {} not present'.format(self.hardware))
            return True
        self.handle.execute('delete port-channel {}'.format(self.port_channel_id))
        output = self.handle.execute('commit-buffer')
        if 'Error' in output:
            logger.info("Failed while trying to delete port channel with error: {}".format(output))
            raise Exception("Failed while trying to delete port channel")
        output = self.handle.execute('show interface')
        assert self.hardware not in output, "Found {} in output".format(self.hardware)
        logger.info('Successfully deleted Port-Channel {}'.format(self.hardware))

    def verify_interface_present(self):
        """
        Verify interface is present in show port-channel under scope eth-uplink/fabric
        :return: True/False
        """
        scope(self.handle, 'eth-uplink/fabric')
        return True if self.hardware.lower() in self.handle.execute('show port-channel').lower() else False

    def get_details(self):
        """
        gets the attributes associated with the interface in a dict
        """
        self.handle.execute('top')
        assert self.verify_interface_present(), 'Interface {} not present'.format(self.hardware)
        self.handle.execute('scope port-channel {}'.format(self.port_channel_id))
        output = create_dict(self.handle.execute('show detail'))
        return output

    def get_subinterfaces(self):
        """
        gets a list of subinterface names
        :return:
        """
        scope(self.handle, 'eth-uplink/fabric')
        self.handle.execute('scope port-channel {}'.format(self.port_channel_id))
        output = self.handle.execute('show subinterface').split('\r\n')
        subinterfaces = []
        for i in output:
            if re.match("^\s+(\d+)\s*\w+\-\w+\d+\.\d+", i):
                match = re.match("^\s+(\d+)\s*\w+\-\w+\d+\.\d+", i)
                subinterfaces.append(match.group(1))
        return subinterfaces

    def reset(self):
        """
        Removes configurations.
        """
        return self.configure(port_type='Data', enabled=True, commit=True)
