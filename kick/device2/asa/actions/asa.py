"""Copyright (c) 2017 Cisco Systems, Inc.
Name:
    asa.py
Usage:
    Library for legacy ASA command line.
Author:
    aitang/raywa
"""

import re
import time
import logging

from unicon.eal.dialogs import Dialog
from unicon.utils import AttributeDict


try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric

from .constants import AsaConfigConstants, AsaSmStates
from .patterns import AsaPatterns
from .statemachine import AsaStatemachine
from .dialogs import AsaDialog
from ...general.actions.basic import BasicDevice, BasicLine

LOGGER = logging.getLogger(__name__)

ASA_INIT_CMDS = """
    terminal width 511
    terminal pager 0
"""
DEFAULT_TIMEOUT = 10


class Asa(BasicDevice):
    """Class Asa.
    """

    def __init__(self, hostname='ciscoasa', enable_password=''):
        """Initializer of Asa instance.

        :param hostname: ASA hostname
        :param enable_password: ASA enable password
        :return: None

        """

        publish_kick_metric('device.asa.init', 1)
        self.patterns = AsaPatterns(hostname, enable_password)
        self.sm = AsaStatemachine(self.patterns)

        self.line_class = AsaLine
        super().__init__()

    def connect_from_ssp(self, ssp_line, slot, timeout=None, ld_name=''):
        """Connect through SSP telnet console

        :param ssp_line: SSP connection instance
        :param slot: module # that ASA is installed on
        :param timeout: timeout to wait for asa connection to be ready in seconds
        :param ld_name: logical device name for multi instance only
        :return: line object of ASA device

        To connect to ASA console from SSP MIO (BS-FPR9300/QP-FPR4100),
        following sequence of commands are needed:
         - connect module 1(2,3) console
           * we now enter Firepower mode, with prompts such as
             "Firepower-module1>","Firepower-module2>" or "Firepower-module3>"
         - connect asa
           * this brings us to asa mode with promps such as
             "ciscoasa>", "ciscoasa#" etc
             After this cli is entered, console messages from previous
             sessions will roll up. Sometimes these messages are not ended w/
             newline thus not able to bring up asa prompt.
             For this kind of scenarios, we need to send a newline to
             bring up asa prompt.
        """

        if not timeout:
            timeout = DEFAULT_TIMEOUT
        ssp_line.go_to('mio_state')

        # connect to module
        ssp_line.spawn_id.sendline('connect module {} console'.format(slot))
        time.sleep(0.5)
        ssp_line.spawn_id.sendline()
        ssp_line.spawn_id.sendline()

        # pylint: disable=anomalous-backslash-in-string
        asa_prompt = '[\r\n]({}|ciscoasa|asa)[/\w\(\)-]*[>#] '.format(self.patterns.hostname)
        dialog = Dialog([
            ['Firepower-module{}>'.format(slot),
             'sendline(connect asa {})'.format(ld_name), None, True, False],
            ['Connecting to ', 'sendline()', None, True, False],
            [asa_prompt, 'sendline()', None, False, False]
        ])
        dialog.process(ssp_line.spawn_id, timeout=timeout)

        asa_line = self.line_class(
            ssp_line.spawn_id, self.sm, 'telnet', carrier='ssp', timeout=timeout)
        return asa_line

    def connect_from_kp(self, kp_line, timeout=None):
        """Connect through SSP telnet console

        :param kp_line: KP connection instance
        :param timeout:
        :return: line object of ASA device

        """

        if not timeout:
            timeout = DEFAULT_TIMEOUT
        kp_line.go_to('fxos_state')

        # connect to asa
        kp_line.spawn_id.sendline('connect asa')

        asa_line = self.line_class(
            kp_line.spawn_id, self.sm, 'telnet', carrier='kp', timeout=timeout)
        return asa_line

    def connect_from_csp(self, csp_line, port, timeout=None):
        """

        :param csp_line:  CSP connection instance
        :param port: service port number
        :param timeout:
        :return:
        """
        csp_line.go_to('csp_enable_state')
        csp_line.spawn_id.sendline('telnet {port}'.format(port=port))
        csp_line.spawn_id.expect("Trying.*Connected to.*Escape character is '\^\]'\.", timeout)
        time.sleep(0.5)
        csp_line.spawn_id.sendline('')

        service_line = self.line_class(csp_line.spawn_id, self.sm, 'telnet', timeout=timeout)
        return service_line


class AsaLine(BasicLine):
    """ASA line class that provides connection interaction to the device
    """

    def __init__(self, spawn_id, sm, conn_type, carrier=None, timeout=None):
        """Initializer of AsaLine.

        :param spawn_id:
        :param sm: ASA statemachine
        :param conn_type: connection type (telnet or ssh)
        :return: None

        """

        super().__init__(spawn_id, sm, conn_type, timeout=timeout)
        self.carrier = carrier
        self.config(ASA_INIT_CMDS)

    def expect_prompt(self):
        """Expect current prompt
        """

        prompt = self.sm.get_state(self.sm.current_state).pattern
        self.spawn_id.sendline()
        return self.spawn_id.expect(prompt).last_match.string

    def change_hostname(self, new_hostname):
        """Change ASA hostname

        :param new_hostname: new hostname to be changed
        :return: None

        """

        patterns = self.sm.patterns
        patterns.change_hostname(new_hostname)
        self.sm.change_pattern(patterns)
        self.config('hostname %s' % new_hostname, exception_on_bad_config=True)

    def change_enable_password(self, new_password):
        """Change ASA enable password

        :param new_password: new enable password to be changed
        :return: None

        """

        patterns = self.sm.patterns
        patterns.change_enable_password(new_password)
        self.sm.change_pattern(patterns)
        self.config('enable password %s' % new_password, exception_on_bad_config=True)

    def delete(self, file_name, location=AsaConfigConstants.DISK0, flag=''):
        """Delete a file from asa

        Example:
            asa.delete('image.bin', 'disk0', '/noconfirm') will execute cmd:
            delete /noconfirm disk0: image.bin

        :param file_name: file to be deleted
        :param location: file location
        :param flag: flag to be used such as /noconfirm
        :return: None

        """

        if AsaConfigConstants.DELETE_NOCONFIRM in flag:
            self.enable_execute('delete %s %s:%s' % (flag, location, file_name))
        else:
            self.go_to(AsaSmStates.ENABLE_STATE.value)
            self.spawn_id.sendline('delete %s %s:%s' % (flag, location, file_name))
            self.spawn_id.expect('Delete filename')
            self.spawn_id.sendline()
            states = [state.name for state in self.sm.states]
            enable_prompt = self.sm.states[states.index(AsaSmStates.ENABLE_STATE.value)].pattern
            while True:
                output = self.spawn_id.read()
                if output:
                    if '[confirm]' in output:
                        self.spawn_id.sendline()
                    elif re.search(enable_prompt, output):
                        break
                time.sleep(0.5)

    def clear_config_all(self, timeout=60):
        """Clear all config in ASA

        :param timeout: timeout for prompt return
        :return: None

        """

        if 'telnet' in self.type:
            self.config('clear configure all', timeout)
            self.config(ASA_INIT_CMDS)
        elif 'ssh' in self.type:
            raise RuntimeError('Clear configure all under ssh will lose current connection to ASA')

    def reload(self, timeout=300, write_mem=True):
        """Reload ASA

        :param timeout: reload timeout for prompt return
        :return: None

        """

        # write memory before reload
        if write_mem:
            self.enable_execute('write memory', exception_on_bad_command=True)

        # reload ASA
        self.spawn_id.sendline('reload')
        # pylint: disable=anomalous-backslash-in-string
        self.spawn_id.expect('\[confirm\]')
        self.spawn_id.sendline()

        self._reload_expect_prompt(timeout=timeout)

        self.config(ASA_INIT_CMDS)

    def change_firewall_mode(self, fmode):
        """Change firewall mode between router and transparent

        :param fmode: firewall mode. tfw | rfw
        :return: None

        """

        # pylint: disable=anomalous-backslash-in-string
        show_mode = re.search('Firewall mode: (\w+)', self.enable_execute('show firewall'))
        if show_mode:
            current_mode = show_mode.group(1)
            if AsaConfigConstants.FIREWALL_MODE[fmode] != current_mode:
                cmd = 'firewall %s' % AsaConfigConstants.FIREWALL_MODE['tfw'].lower()
                if fmode == 'tfw':
                    self.config(cmd)
                elif fmode == 'rfw':
                    self.config('no ' + cmd)
                self.change_hostname(self.sm.patterns.hostname)
        else:
            raise RuntimeError('Unable to determine current firewall mode')

    def change_context_mode(self, cmode):
        """Change context mode between single and multi

        :param cmode: context mode. sfm | mfm
        :return: None

        """

        # pylint: disable=anomalous-backslash-in-string
        show_mode = re.search('Security context mode: (\w+)', self.enable_execute('show mode'))
        if show_mode:
            current_mode = show_mode.group(1)
        else:
            raise RuntimeError('Unable to determine current context mode')

        if current_mode == AsaConfigConstants.CONTEXT_MODE['mfm']:
            self.enable_execute('changeto system')

        if AsaConfigConstants.CONTEXT_MODE[cmode] != current_mode:
            self.go_to(AsaSmStates.CONFIG_STATE.value)
            self.spawn_id.sendline('mode %s' % AsaConfigConstants.CONTEXT_MODE[cmode])
            # pylint: disable=anomalous-backslash-in-string
            self.spawn_id.expect('change mode\? \[confirm\]')
            self.spawn_id.sendline()
            try:
                self.spawn_id.expect('system configuration\? \[confirm\]')
            except:
                pass
            else:
                self.spawn_id.sendline()

            self._reload_expect_prompt()

            self.config(ASA_INIT_CMDS)

    def download_image(
            self, protocol, server, image_path, dst,
            port=None, noconfirm=True, overwrite=True, usr=None, pwd=None, timeout=600):
        """Download a required image from the source to the destination

        :param protocol: protocol going to be used
        :param server: server address
        :param image_path: image path
        :param dst: destination path on ASA
        :param noconfirm: flag to skip download dialog
        :param usr: username
        :param pwd: password
        :return: None

        """
        cmd = 'copy '
        if noconfirm:
            cmd += '/noconfirm '

        cmd += '{protocol}://'.format(protocol=protocol)

        if usr:
            cmd += '{usr}:{pwd}@'.format(usr=usr, pwd=pwd)

        cmd += '{server}'.format(server=server)

        if port:
            cmd += ':{port}'.format(port=port)

        cmd += '/{image_path} {dst}'.format(image_path=image_path, dst=dst)

        if noconfirm:
            self.execute(cmd, timeout=timeout, exception_on_bad_command=True)
        else:
            overwrite = '' if overwrite is True else 'q'
            args = AttributeDict({'overwrite': overwrite})

            self.spawn_id.sendline(cmd)
            dialog = AsaDialog.download_dialog
            output = dialog.process(self.spawn_id, context=args, timeout=timeout)

            if 'Error' in output.last_match.string:
                raise RuntimeError('bad command: {cmd}'.format(cmd=cmd))

    def disconnect(self):
        """Disconnect the line.

        :return: None

        """

        if self.type == 'ssh':
            # send \n + ~.
            self.spawn_id.sendline('')
            self.spawn_id.send('~.')
            self.spawn_id.expect('Connection to .* closed.')
        elif self.type == 'telnet':
            if self.carrier in ('ssp', 'kp'):
                # pylint: disable=anomalous-backslash-in-string
                self.spawn_id.send('\001')
                self.spawn_id.send('d')
                if self.carrier == 'ssp':
                    self.spawn_id.expect('Firepower-module\d+>')
                    self.spawn_id.send('~')
                    self.spawn_id.expect('telnet>')
                    self.spawn_id.sendline('quit')
                    self.spawn_id.expect('Connection closed.')
            else:
                # send ctrl + ], then q
                self.spawn_id.send('\035')
                self.spawn_id.expect('telnet> ')
                self.spawn_id.sendline('q')
                self.spawn_id.expect('Connection closed.')

    def _reload_expect_prompt(self, timeout=300):
        """Wait for ASA to be back online after reload

        :param timeout: timeout for reload
        :return: None

        """

        if 'telnet' in self.type:
            disable_prompt = self.sm.patterns.prompt.disable_prompt

            dialog = Dialog([
                ['Process shutdown finished', None, None, True, False],
                ['The system is restarting', None, None, True, False],
                ['Configuring network interfaces... done', None, None, True, False],
                ['Compiled on', None, None, True, False],
                ['The digital signature of the running image verified successfully', \
                 None, None, True, False],
                ['Compiled on', None, None, True, False],
                ['Cisco Adaptive Security Appliance Software Version', None, None, True, False],
                [disable_prompt, 'sendline()', None, False, False],
            ])
            dialog.process(self.spawn_id, timeout=timeout)

            self.go_to('any')
        elif 'ssh' in self.type:
            pass

    def sudo_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """ Not implemented for AsaLine class"""

        raise NotImplementedError
