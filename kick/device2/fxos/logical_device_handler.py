import logging

from kick.device2.fxos.utils import create_dict, scope

logger = logging.getLogger(__name__)


class LogicalDeviceUtils:
    def __init__(self, handle):
        """
        Constructor of App Instance
        :param handle: SSH connection handle
        """
        self.handle = handle

    def get_all_ld(self):
        """
        Get all logical device details
        :return:
        """
        scope(self.handle, 'ssa')
        lds = []
        output = self.handle.execute('show logical-device detail', timeout=30)
        if "Logical Device" not in output:
            logger.info("Retrying command")
            output = self.handle.execute('show logical-device detail', timeout=30)
        if "Oper State" not in output:
            logger.info("Retrying command again")
            output = self.handle.execute('show logical-device detail', timeout=30)
        for i in list(
                map(lambda x: create_dict(x), output.split('\r\n\r\n'))):
            if hasattr(i, 'Name'):
                lds.append(i)

        return lds

    def delete_all_ld(self):
        """
        Delete all logical device
        :return:
        """
        all_devices = self.get_all_ld()
        for logical_device in all_devices:
            self.delete_ld_by_name(logical_device['Name'])

    def delete_ld_by_name(self, name):
        """
        delete logical device
        """
        logger.info('Deleting Logical-Device {}'.format(name))
        scope(self.handle, 'ssa')
        self.handle.execute('delete logical-device {}'.format(name))
        output = self.handle.execute('commit-buffer')
        if 'Error' in output:
            logger.info("Failed while deleting logical device with error: {}".format(output))
            raise Exception("Failed while deleting logical device")
        self.handle.execute('discard-buffer')
