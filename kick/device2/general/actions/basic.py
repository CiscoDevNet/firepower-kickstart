import logging
import re
import subprocess
import time
import traceback

import datetime
from unicon.core.errors import StateMachineError
from unicon.eal.dialogs import Dialog
from unicon.eal.expect import TimeoutError as uniconTimeoutError
from unicon.statemachine import Path
from unicon.statemachine import State
from unicon.utils import AttributeDict

from kick.miscellaneous.credentials import *
from ..actions.access import clear_line

try:
    import kick.graphite.graphite as graphite
except ImportError:
    import kick.metrics.metrics as graphite

logger = logging.getLogger(__name__)

###################################################################################################
# The following overrides original unicon Spawn read function to ignore unicode decode failure    #
###################################################################################################
import os
from unicon.eal.backend import pty_backend

try:
    from kick.kick_constants import KickConsts
except ImportError:
    from kick.miscellaneous.credentials import KickConsts

from .constants import CONFIGURATION_DIALOG, TYPE_TO_STATE_MAP, DEVICE_LIST

DEFAULT_USERNAME = 'myusername'
DEFAULT_PASSWORD = 'mypassword'
DEFAULT_ENPASSWORD = 'myenpassword'


class NewSpawn(pty_backend.Spawn):
    """A new Spawn class that ignore non utf-8 decode error."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self, 'match_mode_detect'):
            self.match_mode_detect = False

    def read(self, size=None):
        """Override original read function to ignore non utf-8 decode error."""
        size = size or self.size
        if self.is_readable():
            byte_data = os.read(self.fd, size)
            # try:
            #     data = byte_data.decode('utf-8')
            # except:
            #     self.log.info("non_utf-8_character %s" % str(byte_data))
            #     data = str(byte_data)
            data = byte_data.decode('utf-8', 'ignore')
            return data
        else:
            return None


###################################################################################################
# End                                                                                             #
###################################################################################################

DEFAULT_TIMEOUT = 10
# timeout for configuration wizard to complete
DEFAULT_CONFIGURATION_TIMEOUT = 900


class BasicDevice:
    def __init__(self):
        """Constructor of device.

        :return: None

        """

        # set default timeout value for functions in this class,
        # such as ssh_console(), ssh_vty(), etc.

        self.set_default_timeout(DEFAULT_TIMEOUT)
        self.set_default_config_timeout(DEFAULT_CONFIGURATION_TIMEOUT)

    def set_default_timeout(self, timeout):
        """Set the default timeout value for this device.

        In the later function calls, such as ssh_console(), ssh_vty(), unless
        overwritten, this timeout value will be used.

        :param timeout: in seconds
        :return: None

        """

        logger.debug('setting device default timeout to {}'.format(timeout))
        self.default_timeout = timeout

    def set_default_config_timeout(self, timeout):
        """Set the default configuration timeout value for this device.

        In the later function call of ssh_vty(), unless overwritten,
        this timeout value will be used for processing the configuration wizard dialog.

        :param timeout: in seconds
        :return: None

        """

        logger.debug('setting device default configuration timeout to {}'.format(timeout))
        self.configuration_timeout = timeout

    def ssh_console(self, ip, port, username=DEFAULT_USERNAME, password=DEFAULT_PASSWORD,
                    timeout=None, en_password=DEFAULT_ENPASSWORD):
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

        if username == DEFAULT_USERNAME:
            username = get_username(username)
        if password == DEFAULT_PASSWORD:
            password = get_password(password)
        if en_password == DEFAULT_ENPASSWORD:
            en_password = get_en_password(en_password)

        graphite.publish_kick_metric('device.basic.ssh_console', 1)
        if not timeout:
            timeout = self.default_timeout

        spawn_id = NewSpawn(
            'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
            '-l {} -p {} {} \n'.format(username, port, ip))

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
            clear_line(ip, int(port) % 100, user=username, pwd=password,
                       prompt='#', access='ssh', en_password=en_password,
                       timeout=timeout)
            spawn_id = NewSpawn(
                'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                '-l {} -p {} {} \n'.format(username, port, ip))
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

    def telnet_console_no_credential(self, ip, port, timeout=None):
        """Set up an telnet console connection, no need to provide credential.

        This goes into device's console port, through a terminal server.

        :param ip: ip address of terminal server
        :param port: port of device on terminal server
        :param timeout: in seconds
        :return: a line object (where users can call execute(), for example)

        """

        graphite.publish_kick_metric(
            'device.basic.telnet_console_no_credential', 1)

        if not timeout:
            timeout = self.default_timeout

        spawn_id = NewSpawn('telnet {} {}'.format(ip, port))
        try:
            spawn_id.expect("Connected to.*Escape character is '\^\]'\.",
                            timeout)
        except OSError:
            spawn_id.close()
            clear_line(ip, int(port) % 100, prompt='#', access='telnet',
                       timeout=timeout)
            spawn_id = NewSpawn('telnet {} {}'.format(ip, port))
            try:
                spawn_id.expect("Connected to.*Escape character is '\^\]'\.",
                                timeout)
            except:
                spawn_id.close()
                raise
        time.sleep(0.5)
        spawn_id.sendline('')
        telnet_line = self.line_class(spawn_id, self.sm, 'telnet',
                                      timeout=timeout)
        logger.debug('telnet_console_no_credential() finished successfully')

        return telnet_line

    def telnet_console_with_credential(self, ip, port, username=DEFAULT_USERNAME,
                                       password=DEFAULT_PASSWORD, timeout=None,
                                       en_password=DEFAULT_ENPASSWORD):
        """Set up an telnet console connection, and needs to provide
        credential.

        This goes into device's console port, through a terminal server.

        :param ip: ip address of terminal server
        :param port: port of device on terminal server
        :param username: username
        :param password: password
        :param timeout: in seconds
        :param en_password: enable password to switch to line configuration mode
        :return: a line object (where users can call execute(), for example)

        """

        if username == DEFAULT_USERNAME:
            username = get_username(username)
        if password == DEFAULT_PASSWORD:
            password = get_password(password)
        if en_password == DEFAULT_ENPASSWORD:
            en_password = get_en_password(en_password)

        graphite.publish_kick_metric(
            'device.basic.telnet_console_with_credential', 1)

        if not timeout:
            timeout = self.default_timeout

        spawn_id = NewSpawn('telnet {} {}\n'.format(ip, port))
        try:
            spawn_id.expect(
                "Connected to.*Escape character is '\^\]'\..*Username: ",
                timeout)
        except OSError:
            spawn_id.close()
            clear_line(ip, int(port) % 100, user=username,
                       pwd=password, prompt='#', access='telnet',
                       en_password=en_password, timeout=timeout)
            spawn_id = NewSpawn('telnet {} {}\n'.format(ip, port))
            try:
                spawn_id.expect(
                    "Connected to.*Escape character is '\^\]'\..*Username: ",
                    timeout)
            except:
                spawn_id.close()
                raise
        spawn_id.sendline(username)
        spawn_id.expect("Password: ", timeout)
        spawn_id.sendline(password)
        try:
            spawn_id.expect("Password OK.*", timeout)
        except uniconTimeoutError:
            logger.debug("'Password OK' message did not appear ... continue")
        spawn_id.sendline('')
        telnet_line = self.line_class(spawn_id, self.sm, 'telnet',
                                      timeout=timeout)
        logger.debug('telnet_console_with_credential() finished successfully')

        return telnet_line

    def telnet_console(self, ip, port, username=DEFAULT_USERNAME, password=DEFAULT_PASSWORD,
                       en_password=DEFAULT_ENPASSWORD, timeout=None):
        """
        Set up an telnet console connection, and needs to provide credential.

        This goes into device's console port, through a terminal server.

        :param ip: ip address of terminal server
        :param port: port of device on terminal server
        :param username: username
        :param password: password
        :param en_password: enable password to switch to line configuration mode
        :param timeout: in seconds
        :return: a line object (where users can call execute(), for example)
        """

        if username == DEFAULT_USERNAME:
            username = get_username(username)
        if password == DEFAULT_PASSWORD:
            password = get_password(password)
        if en_password == DEFAULT_ENPASSWORD:
            en_password = get_en_password(en_password)

        # if username and password are empty strings, no credentials are required
        if not username and not password:
            telnet_line = self.telnet_console_no_credential(ip, port, timeout)
        else:
            # the user is not aware of how the port is configured with or w/o credentials
            try:
                telnet_line = self.telnet_console_with_credential(
                    ip, port, username, password, timeout, en_password)
            except:
                telnet_line = self.telnet_console_no_credential(ip, port, timeout)

        return telnet_line

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

        graphite.publish_kick_metric('device.basic.ssh_vty', 1)
        ssh_line = None

        if not timeout:
            timeout = self.default_timeout

        if rsa_key:
            resp = subprocess.getoutput('chmod 400 {}'.format(rsa_key))
            if 'No such file or directory' in resp:
                raise RuntimeError(
                    'The identity file {} you provided does not exist'.format(
                        rsa_key))
            spawn_id = NewSpawn(
                'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                '-i {} -l {} -p {} {} \n'.format(rsa_key, username, port, ip))
        else:
            spawn_id = NewSpawn(
                'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                '-l {} -p {} {} \n'.format(username, port, ip))

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

    def telnet_vty(self, ip, port, username, password, timeout):
        raise NotImplementedError

    def define_contexts(self, contexts=None):
        """
        Add the new states machine for contexts.
        Append the prompts, states and paths for the contexts

        :param contexts: a list with contexts name diffrent than  ['system', 'admin']
                eq. ['ctx1','ctx2']
                if not given, defaulted to ['system', 'admin']
        :return: None
        """

        # add system_state
        if 'system_state' not in [s.name for s in self.sm.states]:
            system_ctx_prompt = 'system_prompt'
            ctx_prompt_value = '[\r\n][\x07]?system>'
            self.sm.patterns.prompt.update(
                {system_ctx_prompt: ctx_prompt_value})
            system_ctx_state = State('system_state', ctx_prompt_value)
            self.sm.add_state(system_ctx_state)
        else:
            system_ctx_state = \
                [s for s in self.sm.states if s.name == 'system_state'][0]

        if not contexts:
            contexts = ['admin']
        else:
            contexts.append('admin')

        for ctx in contexts:
            context_prompt = '{}_ctx_prompt'.format(ctx)
            ctx_prompt_value = '[\r\n][\x07]?{}>'.format(ctx)
            self.sm.patterns.prompt.update({context_prompt: ctx_prompt_value})

            ctx_state = '{}_ctx_state'.format(ctx)
            context_ctx_state = State(ctx_state, ctx_prompt_value)
            self.sm.add_state(context_ctx_state)

            # Create paths
            system_to_ctx = Path(system_ctx_state, context_ctx_state,
                                 'changeto context {}'.format(ctx), None)
            ctx_to_system = Path(context_ctx_state, system_ctx_state, 'exit',
                                 None)

            # Add paths
            self.sm.add_path(system_to_ctx)
            self.sm.add_path(ctx_to_system)

    def wait_for_ssh(self, ip, port, username='admin', password=KickConsts.DEFAULT_PASSWORD,
                     timeout=10, line_type='ssh', rsa_key=None, wait_time=600):
        """Ping ssh connection every one minute

        :param ip: ip address of the machine
        :param port: ssh port
        :param username: usually 'admin'
        :param password: usually "Admin123"
        :param timeout: how long to wait for ssh connection within each loop, in seconds;
                        default value is 10s
        :param line_type: 'ssh' or 'ssh_vty'; defaulted to 'ssh'
                'ssh_vty' is used for connecting directly to the FTD of a SSP
        :param rsa_key: identity file (full path)
        :param wait_time: how long to wait for ssh connection to be available, in seconds;
                defaulted to 600s
        :return:
        """

        start_time = time.time()
        is_available = False
        logger.info('Waiting for ssh to be available')
        while start_time + wait_time > time.time():
            try:
                line = self.ssh_vty(ip=ip, port=port, rsa_key=rsa_key, line_type=line_type,
                                    timeout=timeout, username=username, password=password)
                if line:
                    is_available = True
                    line.disconnect()
                    break
            except Exception as e:
                current_time = time.time()
                logger.info('ssh not available after {}'.format(_time_message(start_time, current_time)))
                logger.info('Error message: {}'.format(str(e)))
                time.sleep(60)
        if is_available:
            logger.info('ssh connection available')
        else:
            end_time = time.time()
            logger.error('ssh not available after {} '.format(_time_message(start_time, end_time)))
            raise RuntimeError('ssh connection not available')
        return is_available

    def _accept_configuration_and_change_password(self, spawn_id, line_type, username, password, timeout):
        """ Confirm device properties and change password to a dummy one and then back to the one provided by
        the user
        :param spawn_id: NewSpawn object
        :param line_type: 'ssh' or 'ssh_vty'
        :param username: usually 'admin'
        :param password: password for ssh access
        :param timeout: timeout for ssh connection
        :return:
        """
        ssh_line = None
        d_change_password = Dialog([
            ['Too many logins for \'{}\''.format(username), None, None, False, False],
            ['Password OK', 'sendline()', None, False, False],
            ['[>#$] ', 'sendline()', None, False, False],
            ['Last login: ', None, None, False, False],
            ['Password:', 'sendline({})'.format(password), None, True, False],
            ['You are required to change your password immediately', None, None, True, False],
            ['\(current\) UNIX password', 'sendline({})'.format(password), None, True, False],
            ['New UNIX password', 'sendline({})'.format(KickConsts.DUMMY_PASSWORD), None, True, False],
            ['Retype new UNIX password', 'sendline({})'.format(KickConsts.DUMMY_PASSWORD), None, True, False],
            ['Password unchanged', None, None, False, False]
        ])

        response = d_change_password.process(spawn_id, timeout=150)
        logger.info("response of d_change_password is: {}".format(response.match_output))

        if response and 'Password unchanged' in response.match_output:
            logger.error('Changing password for {} user has failed'.format(username))
            spawn_id.close()
            raise Exception('Error while changing {} password to the temporary one'.format(username))

        if 'Too many logins for \'{}\''.format(username) in response.match_output:
            logger.info('Too many logins for \'{}\''.format(username) )
            spawn_id.close()
            raise Exception('Error while taking ssh connection for {} as the user has taken maximum connections'.format(username))

        try:
            config_dialog = CONFIGURATION_DIALOG.process(spawn_id, timeout=self.configuration_timeout)
        except uniconTimeoutError:
            spawn_id.close()
            raise
        # get hostname dynamically and reinitialize the state machines
        self.reinitialize_sm(spawn_id, config_dialog)

        if response and 'You are required to change your password immediately' in response.match_output:
            logger.info("Change back dummy password: '{}' to the one provided by the user.".
                        format(KickConsts.DUMMY_PASSWORD))
            ssh_line = self.line_class(spawn_id, self.sm, line_type, timeout=timeout)
            _set_password(ssh_line, username, password)

        return ssh_line

    def reinitialize_sm(self, spawn_id, response_dialog):
        if str(self.line_class) in DEVICE_LIST:
            logger.debug("Reinitialize state machines")
            self.sm.patterns.hostname = self._get_hostname(spawn_id) or self.sm.patterns.hostname
            self.sm.__init__(self.sm.patterns)
            if response_dialog and '> ' in response_dialog.match_output:
                spawn_id.sendline('exit')
        else:
            logger.debug("{} not qualified for reinitialize sm".format(self.line_class))

    def _get_hostname(self, spawn_id):
        """Get hostname dynamically"""

        # clear buffer first
        spawn_id.buffer = ''
        # send new line to get the prompt
        spawn_id.sendline()
        time.sleep(3)
        prompt = spawn_id.read()
        regex_pattern = "[\w-]*((?=\slogin:)|(?=[\s:]\/)|(?=[$#(])|(?=:~))"
        hostname = re.search(regex_pattern, prompt)

        if hostname:
            logger.info("Hostname: {}".format(hostname.group()))
            return hostname.group()

        return ''


class BasicLine:
    def __init__(self, spawn_id, sm, type, timeout=None):
        """Constructor of device.

        :return: None

        """
        self._reconnect_feature = {'enabled': False, 'max_retries': 0}
        self.spawn_id = spawn_id
        self.sm = sm
        self.type = type
        self.line_type = 'BasicLine'
        self.set_default_timeout(DEFAULT_TIMEOUT)
        self.spawn_command = self.spawn_id.spawn_command
        self.spawn_id.sendline()
        self.go_to('any', timeout=timeout)
        # set default timeout value for functions in this class,
        # such as ssh_console(), ssh_vty(), etc.

    @property
    def reconnect_feature(self):
        """
        Getter
        Property can be used to enable/disable the auto reconnect feature for
        cases when the device closes the ssh connection.
        :return: a dict with the current settings
            {
                'enabled': True, -> reconnect mechanism is enabled
                'max_retries': 3 -> max. number of retries to reconnect
            }
        """
        return self._reconnect_feature

    @reconnect_feature.setter
    def reconnect_feature(self, value):
        """
        Setter
        Property can be used to enable/disable the auto reconnect feature for
        cases when the device closes the shh connection.
        :param value: a dict providing the following settings
            {
                'enabled': True, -> reconnect mechanism is enabled
                'max_retries': 3 -> max. number of retries to reconnect
            }
        :return: None
        """
        if not isinstance(value, dict):
            raise RuntimeError('You have to provide a dictionary.')
        if not isinstance(value.get('enabled', None), bool):
            raise RuntimeError('Please read the setter documentation. You must provide a bool value for the enabled'
                               ' field.')
        if bool(value['enabled']):
            if not isinstance(value.get('max_retries', None), int):
                raise RuntimeError('Please read the setter documentation. You must provide an int value for the '
                                   'max_retries field.')
            logger.info('\n\n\nYou have enabled the reconnect feature. You have specified max_retries to be {}. This '
                        'may hide bugs. Use with caution.\n\n\n'.format(value['max_retries']))
        else:
            self._reconnect_feature.update({'enabled': False, 'max_retries': 0})
            logger.info('\n\n\nYou have disabled the reconnect feature.\n\n\n')
        self._reconnect_feature.update(value)

    def set_default_timeout(self, timeout):
        """Set the default timeout value for this line.

        In the later function calls of this class, such as execute(),
        execute_lines(), unless overwritten, this timeout value will be used.

        :param timeout: in seconds
        :return: None

        """

        logger.debug('setting line default timeout to {}'.format(timeout))
        self.default_timeout = timeout

    def go_to(self, state, **kwargs):
        """Go to specified state.

        :param state: name of state defined in state machine
        :return: None

        """
        if not kwargs.get('timeout', None):
            kwargs['timeout'] = 30
        try:
            self.sm.go_to(state, self.spawn_id, **kwargs)
        except StateMachineError as st_err:
            if st_err.__cause__:
                logger.error('Encountered state machine error with underlying '
                             'cause {}'.format(traceback.format_tb(
                    st_err.__cause__.__traceback__)))
                logger.error("If the cause of the exception seems to be an ssh "
                             "disconnect issue (like a network outage), you can "
                             "use the reconnect feature to handle it. Check out "
                             "the reconnect_feature property of this object.")
            self.do_reconnect(st_err, kwargs['timeout'])
            self.sm.go_to(state, self.spawn_id, **kwargs)

    def recreate_connection_spawn(self, timeout):
        logger.info('Recreating connection spawn ...')
        new_spawn_id = NewSpawn(self.spawn_command)

        ctx = AttributeDict(
            {'password': self.sm.patterns.login_password})
        d = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None,
             True,
             False],
            ['(p|P)assword:', 'sendline_ctx(password)', None, True,
             False],
            ['Password OK', 'sendline()', None, False, False],
            ['[.*>#$] ', 'sendline()', None, False, False],
        ])

        d.process(new_spawn_id, context=ctx, timeout=timeout)
        self.spawn_id.close()
        self.spawn_id = new_spawn_id

    def bring_device_to_previous_state(self, initial_state, timeout):
        logger.info('Device was previously disconnected in {} state. Taking device back to the state it was in when '
                    'the disconnect happened ...'.format(initial_state))
        self.sm.go_to('any', self.spawn_id)
        # at reconnection, reconfigure the terminal if needed
        self.reconfigure_terminal(timeout)
        self.sm.go_to(initial_state, self.spawn_id)

    def do_reconnect_(self, timeout):
        initial_state = self.sm.current_state
        self.recreate_connection_spawn(timeout)
        self.bring_device_to_previous_state(initial_state, timeout)

    def do_reconnect(self, error_reason=None, timeout=30):
        io_err = "Input/output error"
        # only reconnect for i/o errors direct exception or cause of exception
        should_handle = io_err in str(error_reason) or (
                error_reason.__cause__ and io_err in str(
            error_reason.__cause__))
        if not should_handle:
            raise error_reason

        # if feature is not enabled just fail
        if not self._reconnect_feature['enabled']:
            raise error_reason

        # show the disclaimer to the user to make them aware this
        # feature is activated and may hide bugs
        logger.warning('\n\n\nDISCLAIMER: YOU HAVE ENABLED THE SSH RECONNECT '
                    'FEATURE WHICH WILL TRY TO RECONNECT TO THE DEVICE '
                    'IN CASE SSH IS TIMED OUT OR SUDDENLY DROPS. THIS '
                    'MAY HIDE BUGS. USE WITH CAUTION AND AT YOUR OWN PERIL.'
                    '\n\n\n')

        logger.error('Line was disconnected, trying to reconnect...')
        logger.error('Disconnected due to {}'.format(traceback.format_tb(
            error_reason.__traceback__)))
        if error_reason.__cause__:
            # An exception was thrown and caught by code that throwed
            # another exception so printing also the cause if it is available
            logger.error(
                'Cause exception traceback: {}'.format(traceback.format_tb(
                    error_reason.__cause__.__traceback__)))

        retry = int(self._reconnect_feature['max_retries'])
        exception_raised = None
        while retry > 0:
            try:
                self.do_reconnect_(timeout)
                # mark successful reconnect
                exception_raised = None
                break
            except Exception as e:
                exception_raised = e
                retry -= 1
                logger.error('Connection could not be reestablished.')
                logger.error('Exception encountered: {}'.format(
                    traceback.format_tb(e.__traceback__)))
        # if reconnect was not successful (meaning exception_raised is not None)
        # and the number of max retries has been reached then we seem to not
        # be able to reconnect so throwing the exception and failing
        if exception_raised != None:
            raise exception_raised

    def execute(self, cmd, timeout=None, exception_on_bad_command=False,
                prompt=None):
        """Stay in current mode, run the command and return the output.

        :param cmd: a string, such as "show nameif"
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :param prompt: a string representing a pattern to match against the content of the buffer
                      if not given, the pattern of the current state will be used
        :return: output as string

        """

        if not timeout:
            timeout = self.default_timeout

        if not prompt:
            prompt = self.sm.get_state(self.sm.current_state).pattern

        try_reconnect = False
        reason_for_reconnect = None
        output = None
        try:
            output = self.execute_(cmd, timeout, exception_on_bad_command,
                                   prompt)
        except OSError as e:
            if self.type in ['ssh', 'ssh_vty']:
                try_reconnect = True
                reason_for_reconnect = e
            else:
                logger.error('Error while executing command: ', e)
                raise e

        if try_reconnect:
            self.do_reconnect(error_reason=reason_for_reconnect,
                              timeout=timeout)
            output = self.execute_(cmd, timeout, exception_on_bad_command,
                                   prompt)

        return self.remove_prompt_from_output(prompt, output)

    def execute_(self, cmd, timeout, exception_on_bad_command, prompt):
        """Stay in current mode, run the command and return the output.

        :param cmd: a string, such as "show nameif"
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :param prompt: a string representing a pattern to match against the content of the buffer
                      if not given, the pattern of the current state will be used
        :return: output as string

        """
        # clear buffer before running a command
        if self.spawn_id.read_update_buffer():
            self.spawn_id.buffer = ''
        ########Remove CSCvq65169 workaround ###
        self.spawn_id.sendline(cmd)

        # fmc/ftd inserts ' \r' for every 80 chars. sometimes for unknown
        # reason it gives prompt first, then output, then prompt again.
        # the typical pattern matching easily breaks here. we rely on the
        # fact of '\r\n' is always flanking the output.
        output = self.spawn_id.expect(prompt, timeout=timeout).last_match.string
        logger.debug("before trimming in execute(): {}".format(output))

        index = output.find('\r\n')
        output = output[index:]

        # handle bad command
        errors = ["% Invalid Command", "% Incomplete Command", "Error: ",
                  "ERROR: ", "Error ", "ERROR "]
        if any([error in output for error in errors]):
            if exception_on_bad_command:
                raise RuntimeError("bad command: {}".format(cmd))
            else:
                logger.debug("bad command: {}".format(cmd))

        return self.remove_prompt_from_output(prompt, output)

    def reconfigure_terminal(self, timeout):
        # in case of kp and wm, the reconnection is done directly to the ftd
        # so we have to go to 'fxos_state' to reconfigure the terminal
        if self.line_type in ['KpLine', 'WmLine'] and self.chassis_line:
            self.go_to('fxos_state')
        if self.line_type in TYPE_TO_STATE_MAP.keys() and self.sm.current_state is TYPE_TO_STATE_MAP[self.line_type]:
            current_prompt = self.sm.get_state(self.sm.current_state).pattern
            _terminal_settings(self.spawn_id, current_prompt, timeout)

    def remove_prompt_from_output(self, prompt, output):
        """ After getting the output (with prompt inside), remove prompt and
        whitespace to return the output only.

        :param prompt: string, such as '(warrior|firepower)([ /\\w\\-*()]+)?# '
        :param output: string, such as 'firepower-2110# '
        :return: the output, such as ''
        """

        # remove xterm ESC color sequences from the output
        ansi_colors_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
        ansi_title_esc = re.compile(r'\x1B\]0;')
        output = ansi_title_esc.sub('', ansi_colors_escape.sub('', output))
        r = re.findall(prompt, output)
        if len(r) == 0:
            # the entire output is returned, this will happen if executing on
            # non-ftd platforms such as endpoints
            logger.debug("no prompt found.")
            return_data = output.strip()
        elif len(r) == 1:
            # typical scenario: we see output followed by prompt
            # for example: '\r\n12:38:35.398 UTC Tue Jan 03 2012\r\n\rmadhuri(fxos)# '
            logger.debug("one prompt found.")
            m = re.search(prompt, output)
            end = m.span()[0]
            return_data = output[:end].strip()
        elif len(r) == 2:
            # somehow terminal server might insert a new line
            # for example: '\r\n\rmadhuri(fxos)# \r\n12:38:35.398 UTC Tue Jan
            #  03 2012\r\n\rmadhuri(fxos)# '
            logger.debug("two prompts found")

            m1 = re.search(prompt, output)
            end1 = m1.span()[0]
            return_data1 = output[:end1].strip()

            output2 = output[m1.span()[1]:]
            m2 = re.search(prompt, output2)
            end2 = m2.span()[0]
            return_data2 = output2[:end2].strip()
            # at lease one should be an empty string
            if return_data1 and return_data2:
                logger.debug("prompt seen 2 times, got two different lines!")
                return_data = output.strip()
            else:
                return_data = return_data1 or return_data2
        else:
            logger.debug("prompt seen {} times.".format(len(r)))
            return_data = output.strip()

        logger.debug("after trimming in execute(): {}".format(return_data))

        return return_data

    def execute_only(self, cmd, timeout=None):
        """Run a command, get the expected prompt.

        :param cmd: command to be executed
        :param timeout: timeout for the command to be executed,
                        defaulted to 10 seconds
        :return: output of the command executed

        """

        if not timeout:
            timeout = self.default_timeout

        current_state = self.sm.current_state
        prompt = self.sm.get_state(current_state).pattern
        # send cmd
        self.spawn_id.sendline(cmd)
        # expect current_prompt
        output = self.spawn_id.expect(prompt, timeout=timeout).last_match.string
        return output

    def execute_lines(self, cmd_lines, timeout=None,
                      exception_on_bad_command=False):
        r"""stay in the same state, run multiple lines of commands and return
        the output for all commands.

        cmd_lines needs to be a '\\n' delimited string.

        :param cmd_lines: a string, such as "show nameif\\nshow ip\\nshow clock"
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :return: output as string

        """

        if not timeout:
            timeout = self.default_timeout

        return_data = ""
        for cmd in cmd_lines.split('\n'):
            cmd = cmd.strip()
            if cmd == "":
                continue  # empty line
            time.sleep(0.1)
            return_data += self.execute(cmd, timeout, exception_on_bad_command)

        return return_data

    def enable_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """Go to enable mode, run the command and return the output.

        :param cmd: a string, such as "show nameif"
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :return: output as string

        """

        self.go_to('enable_state')
        return self.execute(cmd, timeout, exception_on_bad_command)

    def enable_execute_lines(self, cmd_lines, timeout=None,
                             exception_on_bad_command=False):
        r"""Go to enable mode, run multiple lines of commands and return the
        output for the last command.

        cmd_lines needs to be a '\\n' delimited string.

        :param cmd_lines: a string, such as "show nameif\\nshow ip\\nshow clock"
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :return: output as string

        """

        if not timeout:
            timeout = self.default_timeout

        self.go_to('enable_state')
        return self.execute_lines(cmd_lines, timeout, exception_on_bad_command)

    def config(self, cmd_lines, timeout=None, exception_on_bad_config=False):
        r"""Go to config mode, send multiple lines of configuration.

        cmd_lines needs to be a '\\n' delimited string.

        :param cmd_lines: a string, such as:
            "interface g0/0\\nip address 1.1.1.1 255.255.255.0\\nnameif outside"
        :param timeout: in seconds
        :param exception_on_bad_config: True/False - whether to raise an exception
            on a bad config
        :return: None

        """

        if not timeout:
            timeout = self.default_timeout

        logger.debug("config command: {}".format(cmd_lines))
        self.go_to('config_state')
        prompt = self.sm.get_state(self.sm.current_state).pattern

        for cmd in cmd_lines.split('\n'):
            cmd = cmd.strip()
            if cmd == "":
                continue  # empty line
            self.spawn_id.sendline(cmd)
            self.spawn_id.expect(re.escape(cmd))
            output = self.spawn_id.expect(prompt,
                                          timeout=timeout).last_match.string
            # handle bad command
            errors = ["% Invalid Command", "% Incomplete Command", "Error: ",
                      "ERROR: "]
            if any([error in output for error in errors]):
                if exception_on_bad_config:
                    raise RuntimeError("bad command: {}".format(cmd))
                else:
                    logger.debug("bad command: {}".format(cmd))

    def run_cmd_dialog(self, cmd, dialog, target_state=None, timeout=None):
        """run a command (based on user input as "cmd", and follow up on
        dialog.

        :param cmd: the command that will start the dialog, such as
                    "scp root@1.2.3.4://abc.log ."
        :param dialog: Unicon dialog for expect/send actions
        :param target_state: move to this state before issuing the command
        :param timeout: in seconds
        :return: None

        """

        if not timeout:
            timeout = self.default_timeout

        logger.debug("run command: {}".format(cmd))
        self.go_to(target_state)

        self.spawn_id.sendline(cmd)

        return dialog.process(self.spawn_id, timeout=timeout)

    def scp(self, cmd, pwd, target_state=None, timeout=None):
        """perform the scp action (based on user cmd), and follow up with all
        prompts in scp.

        :param cmd: scp command, such as "scp root@1.2.3.4://abc.log ."
        :param pwd: password for scp
        :param target_state: move to this state before issuing the command
        :param timeout: in seconds
        :return: None

        """

        if not target_state:
            target_state = 'sudo_state'

        if not timeout:
            timeout = self.default_timeout

        logger.debug("scp command: {}".format(cmd))

        d = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True,
             False],
            ['.*(P|p)assword:', 'sendline({})'.format(pwd), None, True, False],
            ['100%.*?' + self.sm.get_state('{}'.format(target_state)).pattern, None, None, False, False]
        ])
        self.run_cmd_dialog(cmd, d, target_state, timeout)

    def disconnect(self):
        """Disconnect the line.

        :return: None

        """
        if self.spawn_id is not None:
            if self.type in ['ssh', 'ssh_vty']:
                # send \n + ~.
                self.spawn_id.sendline('')
                self.spawn_id.send('~.')
                try:
                    self.spawn_id.expect('Connection to .* closed.')
                    logger.debug('ssh line disconnected successfully')
                except OSError as e:
                    logger.debug('Connection closed message did not appear: '
                                 'Encountered exception: {}.'.format(
                        traceback.format_tb(e.__traceback__)))
            elif self.type == 'telnet':
                # send ctrl + ], then q
                self.spawn_id.send('\035')
                self.spawn_id.expect('telnet> ')
                self.spawn_id.sendline('q')
                self.spawn_id.expect('Connection closed.')
                logger.debug('telnet line disconnected successfully')

            self.spawn_id.close()
        else:
            logger.info('You have already closed the connection to this device previously.')
        self.spawn_id = None

    def sendline(self, cmd):
        """Stay in current mode and run the command without expecting the prompt or returning the output

        :param cmd: a string, such as "show nameif"
        :return: output as string

        """

        self.spawn_id.sendline(cmd)

    def read_buffer(self):
        """Wrapper over read() method from unicon.
        Reads, cleans and returns buffer content if there's any or returns False if there's no content in buffer.

        :return: new content of the buffer or False if there isn't any new content

        """

        resp = self.spawn_id.read()
        if not resp:
            logger.info('there is no new information in buffer')
            return False
        return resp

    def changeto_context(self, ctx, timeout=60):
        """Multi-context support

        :param ctx: context name
        :param timeout: timeout to change context
        :return: None

        """

        context_state = '{}_ctx_state'.format(
            ctx) if ctx != 'system' else 'system_state'
        self.go_to(context_state, timeout=timeout)

    def sudo_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """Run a command as sudo and return its output

        :param cmd: command to be executed given as a string
        :param timeout: in seconds; how long to wait for command output
        :param exception_on_bad_command: True/False - whether to raise an exception
        :return: output as a string

        """
        if not timeout:
            timeout = self.default_timeout

        self.go_to('sudo_state')
        return self.execute(cmd, timeout, exception_on_bad_command)

    def replace_asa_image(self, source_location, password, port=22, timeout=300):
        """Replace asa image with a private one.
        This method is valid only for the FTDs.

        :param source_location: the private asa folder that user wants to patch the original one with
                e.g. user@1.2.3.4:/dev/my_asa
        :param password: password for accessing the scp server
        :param port: ssh port, defaulted to 22
        :param timeout: timeout for scp command
        :return:
        """

        self.go_to('sudo_state')
        up_flag = True

        # backup the original asa image to asa_backup_date folder
        date = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_dir = 'asa_backup_{}'.format(date)
        cmd_lines = 'cd /ngfw/usr/local\n ' \
                    'mv -v asa {}\n'.format(backup_dir)

        logger.info('Backup the original asa image to {}'.format(backup_dir))
        self.execute_lines(cmd_lines)

        # scp the private image into /ngfw/usr/local/asa
        scp_cmd = 'scp -P {} -r {}/. asa'.format(port, source_location)
        try:
            self.scp(scp_cmd, password, None, timeout)
        except:
            raise RuntimeError("scp has failed. Please check the logs "
                               "... process aborted")
        output = self.execute('find -maxdepth 1 -name asa')
        if not output:
            raise RuntimeError("asa directory was not created. Please check the logs "
                               "... process aborted")
        logger.info('Rebooting the device')
        self.spawn_id.sendline('reboot')
        # issue 'pwd' command in loop to check exactly when reboot process is starting
        logger.info('Check when connection is lost')
        while up_flag:
            try:
                self.execute('pwd')
            except (uniconTimeoutError, RuntimeError):
                logger.info('Connection lost. System is rebooting...')
                up_flag = False


def _time_message(start_time, end_time):
    """Method used to display the elapsed time between two given periods
    :param start_time: start time
    :param end_time: end time
    :return: elapsed time in hours minutes and seconds as a message
    """
    l_time = str(datetime.timedelta(seconds=round(end_time - start_time))).split(':')
    message = '{} {} {} '.format(l_time[0] + 'h ' if l_time[0] is not '0' else '',
                                 l_time[1] + 'm ' if l_time[1] is not '00' else '',
                                 l_time[2] + 's' if l_time[2] is not '00' else '')
    return message


def _terminal_settings(spawn, prompt, timeout):
    """Run commands for terminal settings
    :param spawn: a Spawn object
    :param prompt: a string representing a pattern to match against the content of the buffer
    :param timeout: in seconds
    :return:
    """

    initcommands = '''
        top
        terminal length 0
        terminal width 511
    '''

    for cmd in initcommands.split('\n'):
        cmd = cmd.strip()
        spawn.sendline(cmd)
        spawn.expect(prompt, timeout=timeout)


def _set_password(line, username, new_password):
    """
    Change password for user 'username'

    :param line: BasicLine object
    :param username: username for the password is changing
    :param new_password: new password to be set
    :return:
    """

    line.sendline('expert')
    line.sendline('sudo su')
    line.spawn_id.expect('[p|P]assword:')
    line.sendline('{}'.format(KickConsts.DUMMY_PASSWORD))
    logger.info('\nChanging back the password to {}'.format(new_password))
    line.sendline('passwd {}'.format(username))
    d_set_password = Dialog([
        ['[N|n]ew UNIX password', 'sendline({})'.format(new_password),
         None, True, False],
        ['Retype new UNIX password', 'sendline({})'.format(new_password),
         None, True, False],
        ['passwd: password updated successfully', None, None, False, False],
    ])
    try:
        d_set_password.process(line.spawn_id, timeout=120)
        line.sm.update_cur_state('sudo_state')
        logger.info('Changing password successfully')
    except uniconTimeoutError:
        logger.error('Changing password for {} user has failed'.format(username))
        line.spawn_id.close()
        raise Exception('Error while changing default password for {} user'.format(username))

