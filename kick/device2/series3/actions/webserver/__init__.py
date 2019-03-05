"""Library to access the webserver."""
import re
import time
import logging
logger = logging.getLogger(__name__)

from unicon.eal.expect import Spawn, TimeoutError
from unicon.utils import AttributeDict
from unicon.eal.dialogs import Dialog

MAX_RETRY_COUNT = 3


class Webserver:
    def __init__(self, hostname='AST-INSTALL', login_username='', login_password='',
                 sudo_password=''):
        """Constructor for Webserver.

        :param hostname: hostname for the device
        :param login_password: device login password for a user
        :param sudo_password: device sudo password for 'root'
        :return: None

        """

        # set hostname and enable_password
        from .constants import WebserverConstants
        WebserverConstants.hostname = hostname
        WebserverConstants.username = login_username
        WebserverConstants.login_password = login_password
        WebserverConstants.sudo_password = sudo_password

        # now that FtdConstants is initialized, create the state machine
        # that contains the proper variables

        from .statemachine import WebserverStatemachine
        self.sm = WebserverStatemachine()

    def ssh_vty(self, ip, port='22'):
        """Setup ssh connection to the server.

        :param ip: ssh host/ip
        :param port: ssh port
        :return: ssh_line

        """
        
        from .constants import WebserverConstants
        spawn = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                      '-l {} -p {} {} \n'.format(WebserverConstants.username, port, ip))
        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['(p|P)assword:', 'sendline({})'.format(WebserverConstants.login_password),
             None, False, False],
        ])
        try:
            d1.process(spawn, timeout=60)
            spawn.sendline()
        except TimeoutError:
            pass

        ssh_line = WebserverLine(spawn, self.sm, 'ssh_ftd')
        return ssh_line


class WebserverLine:

    def __init__(self, spawn, sm, type):
        """Constructor for ssh line. Attributes that are None will be set in
        rommon_to_new_image()

        :param spawn: spawn of the line
        :param sm: object of statemachine
        :param type: line type, e.g. 'ssh_vty'
        :return: object of the line

        """

        self.spawn = spawn
        self.sm = sm
        self.type = type
        sm.go_to('any', spawn)

    def go_to(self, state):
        """Go to specified state.

        :param state: string of the state to go to
        :return: None

        """

        self.sm.go_to(state, self.spawn)

    def execute(self, cmd, timeout=10):
        """Run a command, get the console output. Then exclude the command
        echo, and the new prompt to return the content in between.

        :param cmd: command to be executed
        :param timeout: timeout for the command to be executed, defaulted to 10 seconds
        :return: output of the command executed

        """

        current_state = self.sm.current_state
        current_prompt = self.sm.get_state(current_state).pattern

        self.spawn.sendline(cmd)
        # expect and trim cmd
        # commented for long command
        # output_cmd = self.spawn.expect(cmd, timeout=timeout).last_match.string
        # expect and trim current_prompt
        output = self.spawn.expect(current_prompt,
                                   timeout=timeout).last_match.string

        logger.debug("before trimming in execute(): {}".format(output))

        r = re.search(current_prompt, output)
        end = r.span()[0]

        return_data = output[:end].strip()

        return return_data

    def execute_lines(self, cmd_lines, timeout=10):
        """When given a string of multiple lines, run them one by one and
        return the result for the last line.

        :param cmd_lines: commands to be executed line by line
        :param timeout: timeout for individual command to be executed,
                        defaulted to 10 seconds
        :return: output of the last command executed

        """

        for cmd in cmd_lines.split('\n'):
            cmd = cmd.strip()
            if cmd == "":
                continue # empty line
            return_data = self.execute(cmd, timeout=timeout)

        return return_data

    def disconnect(self):
        """Disconnect the session.

        :return: None

        """

        if self.type == 'ssh_vty':
            self.sm.go_to('user_state', self.spawn)
            self.spawn.sendline('exit')
            self.spawn.expect('closed.')
            logger.info('ssh to ftd connection disconnected')

