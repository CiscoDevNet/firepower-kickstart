import logging
import subprocess

from ats import aetest

from kick.device2.general.actions.basic import NewSpawn
from kick.device2.ssp.actions import Ssp, SspLine
from kick.miscellaneous.credentials import KickConsts
from unicon.utils import AttributeDict
from unicon.eal.dialogs import Dialog

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

logger = logging.getLogger('kick')
logger.setLevel(logging.DEBUG)

logger2 = logging.getLogger('unicon')
logger2.setLevel(logging.DEBUG)

# sim_script = 'python kick/device2/ftd_sim/sim_olivia_loop_with_bell.py'
sim_script = 'python kick/device2/ftd_sim/sim_olivia_loop_without_bell.py'

def ssh_vty(self, ip, port, username='admin', password=KickConsts.DEFAULT_PASSWORD,
            timeout=None, line_type='ssh', rsa_key=None):
    """Set up an ssh connection to device's interface.

    This goes into device's ip address, not console.

    :param ip: ip address of terminal server
    :param port: port of device on terminal server
    :param username: usually "admin"
    :param password: usually "Admin123"
    :param line_type: ssh line type
    :param timeout: in seconds
    :param rsa_key: identity file (full path)
    :return: a line object (where users can call execute(), for example)

    """
    ssh_line = None

    if not timeout:
        timeout = self.default_timeout

    if rsa_key:
        resp = subprocess.getoutput('chmod 400 {}'.format(rsa_key))
        if 'No such file or directory' in resp:
            raise RuntimeError(
                'The identity file {} you provided does not exist'.format(
                    rsa_key))
        spawn_id = NewSpawn(sim_script)
    else:
        spawn_id = NewSpawn(sim_script)

    ctx = AttributeDict({'password': password})
    d = Dialog([
        ['continue connecting (yes/no)?', 'sendline(yes)', None, True,
         False],
        ['(p|P)assword:', 'sendline_ctx(password)', None, False, False],
        ['[>#$] ', 'sendline()', None, False, False]
    ])

    output = d.process(spawn_id, context=ctx, timeout=timeout)
    logger.info('Output from login dialog is: {}'.format(output.match_output.replace(
        '\n', '[LF]').replace('\r', '[CR]')))
    try:
        ssh_line = self._accept_configuration_and_change_password(spawn_id, line_type, username, password, timeout)
    except TimeoutError:
        logger.info("Device initialization has failed")
        logger.info('Spawn_id.buffer content is: {}'.format(spawn_id.buffer))
        raise
    except OSError:
        logger.info(
            "Failed to login with user provided details: user: {}, password: {}".format(
                username, password))
        raise

    logger.debug('ssh_vty() finished successfully')

    if not ssh_line:
        ssh_line = self.line_class(spawn_id, self.sm, line_type, timeout=timeout)

    return ssh_line


class SspTest(aetest.Testcase):
    @aetest.test
    def connect_to_device(self):
        Ssp.ssh_vty = ssh_vty
        ssp = Ssp(hostname='ful01-n8-qp4110-2-A',
            login_username='admin',
            login_password='Admin123',
            sudo_password='Admin123',
            slot_id=1,
            deploy_type='native',
            app_identifier='ftd1',
            app_hostname='ful01-n8-qp4110-1')
        conn = ssp.ssh_vty(ip='10.89.16.212', port=22, username='admin', password='Admin123')
        conn.go_to('fireos_state')


if __name__ == '__main__':
    aetest.main()