import logging
import subprocess

from unicon.eal.dialogs import Dialog
from unicon.utils import AttributeDict

try:
    import kick.graphite.graphite as graphite
except ImportError:
    import kick.metrics.metrics as graphite

from .patterns import EpPatterns
from .statemachine import EpStatemachine
from ...general.actions.basic import BasicDevice, BasicLine, NewSpawn

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10


class Ep(BasicDevice):
    def __init__(self, hostname='firepower',
                 login_username='admin',
                 login_password='Admin123',
                 sudo_password='Admin123',
                 *args,
                 **kwargs):
        """Constructor for Ep.

        :param hostname: host name in prompt e.g. FS2000-01
        :param login_username: user name for login
        :param login_password: password for login
        :param ep_root_password: root password for EP
        :return: None

        Add *args and **kwargs so that the initiator can be invoked with
        additional (unused) arguments.

        """
        graphite.publish_kick_metric('device.ep.init', 1)
        self.patterns = EpPatterns(
            hostname=hostname,
            login_username=login_username,
            login_password=login_password,
            sudo_password=sudo_password)
        self.sm = EpStatemachine(self.patterns)
        self.line_class = EpLine

        self.set_default_timeout(DEFAULT_TIMEOUT)

    def ssh_vty(self, ip, port, username='admin', password='Admin123',
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

        graphite.publish_kick_metric('device.basic.ssh_vty', 1)
        if not timeout:
            timeout = self.default_timeout

        if rsa_key:
            resp = subprocess.getoutput('chmod 400 {}'.format(rsa_key))
            if 'No such file or directory' in resp:
                raise RuntimeError('The identity file {} you provided does not exist'.format(rsa_key))
            spawn_id = NewSpawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                                '-i {} -l {} -p {} {} \n'.format(rsa_key, username, port, ip))
        else:
            spawn_id = NewSpawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                                '-l {} -p {} {} \n'.format(username, port, ip))

        ctx = AttributeDict({'password': password})
        d = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['(p|P)assword:', 'sendline_ctx(password)', None, True, False],
            ['Password OK', 'sendline()', None, False, False],
            ['[.*>#$]+.*\s', 'sendline()', None, False, False],
        ])
        d.process(spawn_id, context=ctx, timeout=timeout)

        ssh_line = self.line_class(spawn_id, self.sm, line_type, timeout)
        logger.debug('ssh_vty() finished successfully')

        return ssh_line


class EpLine(BasicLine):
    def __init__(self, spawn_id, sm, type, timeout):
        """ Constructor of EpLine

                :param spawn_id: spawn_id of the line
                :param sm: object of statemachine
                :param type: line type, e.g. 'ssh', 'telnet'
                :param timeout: in seconds

                :return: None

                """
        super().__init__(spawn_id=spawn_id, sm=sm, type=type, timeout=timeout)
        self.default_timeout = timeout

    def go_to(self, state, timeout=None):
        """Override parent go_to function to enable hop_wise flag."""

        if not timeout:
            timeout = self.default_timeout

        super().go_to(state, hop_wise=True, timeout=timeout)

    def sudo_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        self.go_to('sudo_state')
        return self.execute(cmd, timeout, exception_on_bad_command)

    def expert_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        self.go_to('admin_state')
        return self.execute(cmd, timeout, exception_on_bad_command)

    def replace_asa_image(self, source_location, pwd, timeout=300):
        """ Not implemented for EpLine class"""

        raise NotImplementedError
