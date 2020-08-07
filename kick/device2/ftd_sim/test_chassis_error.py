import logging
from ats import aetest
from ats import topology

from kick.device2.chassis.actions import Chassis
from kick.device2.general.actions.basic import NewSpawn
from unicon.utils import AttributeDict
from unicon.eal.dialogs import Dialog
from unicon.core.errors import StateMachineError

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

logger = logging.getLogger('kick')
logger.setLevel(logging.DEBUG)

logger2 = logging.getLogger('unicon')
logger2.setLevel(logging.DEBUG)

logging.getLogger('chassis').setLevel(logging.DEBUG)

sim_script = 'python kick/device2/ftd_sim/sim_chassis_init.py'


def ssh_console(self, ip, port, username, password, timeout, en_password):
    """Set up an ssh console connection.

    This goes into device's console port, through a terminal server.

    :param ip: ip address of terminal server
    :param port: port of device on terminal server
    :param username: username
    :param password: password
    :param timeout: in seconds
    :param en_password: enable password to switch to line configuration mode
    :return: a line object (where users can call execute(), for example)

    """

    if not timeout:
        timeout = self.default_timeout

    spawn_id = NewSpawn(sim_script)

    ctx = AttributeDict({'password': password})
    d = Dialog([
        ['continue connecting (yes/no)?', 'sendline(yes)', None, True,
         False],
        ['(p|P)assword:', 'sendline_ctx(password)', None, False, False],
    ])
    try:
        d.process(spawn_id, context=ctx, timeout=timeout)
    except OSError:
        spawn_id.close()
        spawn_id = NewSpawn(sim_script)
        try:
            d.process(spawn_id, context=ctx, timeout=timeout)
        except:
            spawn_id.close()
            raise

    d1 = Dialog([
        ['Password OK', 'sendline()', None, False, False],
        ['[.*>#] ', 'sendline()', None, False, False],
    ])
    try:
        d1.process(spawn_id, timeout=timeout)
    except:
        spawn_id.sendline()
    logger.debug('ssh_console() finished successfully')

    try:
        ssh_line = self.line_class(spawn_id, self.sm, 'ssh',
                                   timeout=timeout)
    except:
        spawn_id.close()
        raise

    return ssh_line


class ChassisTest(aetest.Testcase):
    @aetest.test
    def connect_to_device(self):
        chassis_data = Chassis.extract_chassis_data_device_configuration(
            testbed.devices['chassis1'])
        Chassis.ssh_console = ssh_console
        chassis = Chassis(chassis_data)
        chassis_con = chassis.ssh_console(
            ip=chassis_data['connections'].console.ip,
            port=chassis_data['connections'].console.port,
            username=chassis_data['connections'].console.user,
            password=chassis_data['connections'].console.password,
            timeout=30,
            en_password='')
        chassis_con.set_current_slot('1')
        chassis_con.set_current_application('sensor1')
        try:
            chassis_con.go_to('fireos_state', timeout=10)
        except StateMachineError as e:
            chassis_con.spawn_id.read_update_buffer()
            logger.info('Encountered exception: {}'.format(str(e)))
            logger.info('spawn_id buffer is: {}'.format(chassis_con.spawn_id.buffer))
            # device might be in an error state so we clear the buffer and send a CTRL+U to clean the prompt
            chassis_con.spawn_id.buffer = ''
            chassis_con.spawn_id.sendline('\x15')
            chassis_con.go_to('any')
            chassis_con.go_to('mio_state')
            chassis_con.go_to('fireos_state', timeout=10)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="standalone parser")
    # Mandatory
    parser.add_argument('--testbed', dest='testbed')
    # Optional
    args, unknown = parser.parse_known_args()
    yamlfile = args.testbed
    logger.info('>>> Command line argument --testbed: ' + yamlfile)
    # Load yaml file to testbed object
    global testbed
    testbed = topology.loader.load(yamlfile)
    aetest.main()