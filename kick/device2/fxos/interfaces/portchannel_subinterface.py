import logging

from kick.device2.fxos.interfaces.portchannel_interface import PortChannelInterface
from kick.device2.fxos.interfaces.subinterface import SubInterface

logger = logging.getLogger(__name__)


class PortChannelSubInterface(SubInterface):
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
        self.physical_interface = PortChannelInterface(handle=handle, hardware=hardware)
