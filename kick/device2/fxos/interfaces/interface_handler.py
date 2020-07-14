import logging
import re

from kick.device2.fxos.interfaces.physical_interface import PhysicalInterface
from kick.device2.fxos.interfaces.portchannel_interface import PortChannelInterface
from kick.device2.fxos.interfaces.portchannel_subinterface import PortChannelSubInterface
from kick.device2.fxos.interfaces.subinterface import SubInterface
from kick.device2.fxos.utils import scope

logger = logging.getLogger(__name__)


class InterfaceHandler:

    def __init__(self, handle):
        """
        Create a dictionary with all the required info of the interface that can be used by functions
        :param handle: ssh connection handle
        """
        self.handle = handle

    def get_all_port_channel(self):
        """
        get all port channel interfaces
        """
        logger.info('Get all Port Channel Interface')
        scope(self.handle, 'eth-uplink/fabric')
        output = self.handle.execute('show port-channel').split('\r\n')
        portchannel = []
        for i in output:
            if re.match("^\s+\d+\s+(Port-channel\d+)", i):
                match = re.match("^\s+\d+\s+(Port-channel\d+)", i)
                portchannel.append(match.group(1))
        return portchannel

    def delete_all_port_channel(self):
        all_port_channel = self.get_all_port_channel()
        for name in all_port_channel:
            if name != 'Port-channel48':
                interface_obj = PortChannelInterface(self.handle, name)
                interface_obj.delete()

    def instantiate_interface_based_on_name(self, name):
        """
        Instantiates the interface of the correct type based on its name
        :param name: interface name
        """
        if re.match("^\w+\/\d+$", name):
            return PhysicalInterface(self.handle, name)
        elif re.match("^\w+\/\d+\.\d+$", name):
            match = re.match("^(\w+\/\d+)\.(\d+)$", name)
            return SubInterface(self.handle, match.group(1), match.group(2))
        elif re.match("^Port-channel\d+$", name):
            return PortChannelInterface(self.handle, name)
        elif re.match("^(Port-channel\d+)\.(\d+)$", name):
            match = re.match("^(Port-channel\d+)\.(\d+)$", name)
            return PortChannelSubInterface(self.handle, match.group(1), match.group(2))
        else:
            logger.error("Interface Name {} is not valid".format(name))
            raise Exception("Name is not valid")

    def get_all_physical_interfaces(self):
        """
        get all physical interfaces
        """
        logger.info('Get all Physical Interface')
        scope(self.handle, 'eth-uplink/fabric')
        output = self.handle.execute('show interface').split('\r\n')
        interfaces = []
        for i in output:
            if re.match("^\s+(\w+\/\d+)", i):
                match = re.match("^\s+(\w+\/\d+)", i)
                interfaces.append(match.group(1))
        return interfaces

    def reset_all_physical_interfaces(self):
        """
        get all physical interfaces
        """
        interfaces = self.get_all_physical_interfaces()
        for name in interfaces:
            interface_obj = PhysicalInterface(self.handle, name)
            interface_obj.reset()
            subinterfaces = interface_obj.get_subinterfaces()
            for sub_id in subinterfaces:
                subinterface_obj = SubInterface(self.handle, name, sub_id)
                subinterface_obj.delete()
