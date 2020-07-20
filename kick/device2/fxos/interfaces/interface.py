import logging

from kick.device2.fxos.utils import create_dict

logger = logging.getLogger(__name__)


class Interface:
    hardware = None

    def __init__(self, handle):
        """
        Create a dictionary with all the required info of the interface that can be used by functions
        :param handle: ssh connection handle
        """
        self.handle = handle

    def enable(self):
        """
        enable interface
        """
        logger.info('Enabling Interface {}'.format(self.hardware))
        assert self.verify_interface_present(), 'Interface {} not present'.format(self.hardware)
        self.handle.execute(self.scope_command)
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
        logger.info('Disabling Interface {}'.format(self.hardware))
        assert self.verify_interface_present(), 'Interface {} not present'.format(self.hardware)
        self.handle.execute(self.scope_command)
        self.handle.execute('disable')
        self.handle.execute('commit-buffer')
        assert not self._check_interface_enabled(), 'Failed to disable interface {}'.format(self.hardware)
        logger.info('Successfully disabled interface {}'.format(self.hardware))

    def verify_interface_enabled(self):
        """
        verify interface is enabled
        :return: True if interface is Enabled
        """
        assert self.verify_interface_present(), 'Interface {} not present'.format(self.hardware)
        self.handle.execute(self.scope_command)
        return self._check_interface_enabled()

    def _check_interface_enabled(self):
        return True if create_dict(self.handle.execute('show detail'))['Admin State'] == 'Enabled' else False
