import logging

from ats import aetest

from kick.device2.general.actions.basic import NewSpawn
from kick.device2.ssp.actions import Ssp

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class FxosInstallTest(aetest.Testcase):
    @aetest.test
    def connect_to_dev(self):
        ssp = Ssp(hostname='dev',
                  login_username='user',
                  login_password='pass',
                  sudo_password='pass')
        spawn_id = NewSpawn('nc 127.0.0.1 12345')
        conn = ssp.line_class(spawn_id, ssp.sm, 'ssh', timeout=30)
        conn.upgrade_bundle_package('fxos-k9.2.6.1.156.SPA')


if __name__ == '__main__':
    # on the container you can do
    # nc -v -l 127.0.0.1 12345 & python kick/device2/ftd_sim/fxos_install_test.py & fg 1
    # in order to interact manually with the spawn
    aetest.main()
