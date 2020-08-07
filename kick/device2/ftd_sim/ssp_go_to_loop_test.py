import logging
import os
import time

from ats import aetest

from kick.device2.ssp.actions import Ssp

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

logger = logging.getLogger('kick')
logger.setLevel(logging.DEBUG)

logger2 = logging.getLogger('unicon')
logger2.setLevel(logging.DEBUG)


class ChassisGoToLoopTest(aetest.Testcase):
    @aetest.test
    def connect_to_device(self):
        if os.path.exists('./disconnected.py'):
            os.remove('./disconnected.py')
        ssp = Ssp(hostname='ful01-n8-qp4110-1-A',
                  login_username='admin',
                  login_password='Admin123',
                  sudo_password='Admin123')
        conn = ssp.ssh_vty(ip='127.0.0.1', port='22')
        conn.reconnect_feature = {'enabled': True, 'max_retries': 3}
        conn.go_to('fireos_state')
        conn.go_to('expert_state')
        time.sleep(5)
        conn.execute('grep SWVERSION /etc/sf/ims.conf | cut -f2 -d"="')


if __name__ == '__main__':
    aetest.main()
