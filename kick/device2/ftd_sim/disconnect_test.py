import logging

from ats import aetest

from kick.device2.ftd5500x.actions import Ftd5500x
from kick.device2.general.actions.basic import NewSpawn

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class ReconnectFeatureTests(aetest.Testcase):
    def connect_to_device(self, reconnect_feature_is_enabled,
                          device_disconnect_is_enabled):
        ftd = Ftd5500x(hostname='firepower', login_password='Admin123',
                       sudo_password='Admin123')
        if device_disconnect_is_enabled:
            spawn_id = NewSpawn('python3 ./ftd_sim.py --random_disconnect True')
        else:
            spawn_id = NewSpawn('python3 ./ftd_sim.py')
        conn = ftd.line_class(spawn_id, ftd.sm, 'ssh', timeout=30)
        if reconnect_feature_is_enabled:
            conn.reconnect_feature = {'enabled': True, 'max_retries': 2}
        return conn

    def reconnect_feature_test_execute(self, reconnect_feature_is_enabled,
                                       device_disconnect_is_enabled):
        conn = self.connect_to_device(reconnect_feature_is_enabled,
                                      device_disconnect_is_enabled)
        logger.info('\n\n\n\n\n\nExecute commands from fireos_state:')
        for i in range(20):
            conn.execute('dummy_command')

    def reconnect_feature_test_go_to(self, reconnect_feature_is_enabled,
                                     device_disconnect_is_enabled):
        conn = self.connect_to_device(reconnect_feature_is_enabled,
                                      device_disconnect_is_enabled)
        logger.info('\n\n\n\n\n\nExecute commands from fireos_state:')
        for i in range(20):
            logger.info('\n\n\nGoing to expert_state:\n\n\n')
            conn.go_to('expert_state')
            print()
            logger.info('\n\n\nGoing to sudo_state:\n\n\n')
            conn.go_to('sudo_state')
            print()
            logger.info('\n\n\nGoing to fireos_state:\n\n\n')
            conn.go_to('fireos_state')
            print()

    @aetest.test
    def ReconnectFeatureDisabled_DeviceDisconnectDisabled(self):
        self.reconnect_feature_test_execute(reconnect_feature_is_enabled=False,
                                            device_disconnect_is_enabled=False)
        self.reconnect_feature_test_go_to(reconnect_feature_is_enabled=False,
                                          device_disconnect_is_enabled=False)

    @aetest.test
    def ReconnectFeatureEnabled_DeviceDisconnectDisabled(self):
        self.reconnect_feature_test_execute(reconnect_feature_is_enabled=True,
                                            device_disconnect_is_enabled=False)
        self.reconnect_feature_test_go_to(reconnect_feature_is_enabled=True,
                                          device_disconnect_is_enabled=False)

    @aetest.test
    def ReconnectFeatureEnable_DeviceDisconnectEnabled(self):
        self.reconnect_feature_test_execute(reconnect_feature_is_enabled=True,
                                            device_disconnect_is_enabled=True)
        self.reconnect_feature_test_go_to(reconnect_feature_is_enabled=True,
                                          device_disconnect_is_enabled=True)

    @aetest.test
    def ReconnectFeatureDisabled_DeviceDisconnectEnabled_execute(self):
        try:
            self.reconnect_feature_test_execute(
                reconnect_feature_is_enabled=False,
                device_disconnect_is_enabled=True)
        except:
            logger.info("THIS IS EXPECTED TO FAIL.")
            raise

    @aetest.test
    def ReconnectFeatureDisabled_DeviceDisconnectEnabled_go_to(self):
        try:
            self.reconnect_feature_test_go_to(
                reconnect_feature_is_enabled=False,
                device_disconnect_is_enabled=True)
        except:
            logger.info("THIS IS EXPECTED TO FAIL.")
            raise


if __name__ == '__main__':
    aetest.main()
