import logging

from unicon.eal.dialogs import Dialog

logger = logging.getLogger(__name__)


class ClusterBootstrap:
    def __init__(self, handle, chassis_id=None, ccl_network=None, cluster_key=None, cluster_name=None,
                 site_id=None):
        """
        :param handle: SSH connection handle
        """
        self.handle = handle
        self.chassis_id = chassis_id
        self.ccl_network = ccl_network
        self.cluster_key = cluster_key
        self.cluster_name = cluster_name
        self.site_id = site_id


    def configure(self):
        logger.info('Configuring cluster mgmt details in cluster-bootstrap')
        self.handle.execute('enter cluster-bootstrap')
        if self.chassis_id is not None:
            self.handle.execute("set chassis-id {}".format(self.chassis_id))
        if self.ccl_network is not None:
            self.handle.execute("set cluster-control-link network {}".format(self.ccl_network))
        self.handle.execute("""set ipv4 gateway 0.0.0.0
                               set ipv4 pool 0.0.0.0 0.0.0.0
                               set ipv6 gateway ::
                               set ipv6 pool :: ::
                               set virtual ipv4 0.0.0.0 mask 0.0.0.0
                               set virtual ipv6 :: prefix-length ""
                               set mode spanned-etherchannel""")
        if self.cluster_name is not None:
            self.handle.execute("set name {}".format(self.cluster_name))
        if self.site_id is not None:
            self.handle.execute("set site-id {}".format(self.site_id))
        if self.cluster_key is not None:
            self._enter_key_value(self.cluster_key)
        self.handle.execute('exit')
        logger.info('Configured cluster-bootstrap details')



    def _enter_key_value(self,value):
        configuration_dialog = Dialog([
            ['Enter a key', 'sendline({})'.format(value), None, True, True],
            ['Confirm the key:', 'sendline({})'.format(value), None, False, False],
        ])
        target_state = self.handle.sm.current_state
        self.handle.run_cmd_dialog('set key', configuration_dialog, target_state=target_state)
