import collections
import datetime
import logging
import os
import subprocess
import re
import time

from unicon.core.errors import StateMachineError
from unicon.core.errors import TimeoutError
from unicon.eal.dialogs import Dialog

try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric
from .constants import SspConstants
from .patterns import SspPatterns
from .statemachine import SspStateMachine
from ...general.actions.basic import BasicDevice, BasicLine
from ...general.actions.power_bar import power_cycle_all_ports

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True
    pass

logger = logging.getLogger(__name__)

SspInitCmds = '''
    top
    terminal length 0
    terminal width 511
'''
MAX_RETRY_COUNT = 10


class Ssp(BasicDevice):
    def __init__(self, hostname, login_username='admin',
                 login_password='cisco123', sudo_password="cisco123",
                 power_bar_server='', power_bar_port='', slot_id=1,
                 power_bar_user='admn', power_bar_pwd='admn',
                 deploy_type='native', app_identifier='',
                 app_hostname='firepower'):
        """Constructor of Ssp.

        :param hostname: host name in prompt
            e.g. FP9300-2-A
        :param login_username: user name for login
        :param login_password: password for login
        :param sudo_password: root password for FTD
        :param power_bar_server: IP address of the PDU
        :param power_bar_port: port for device on the PDU
        :param slot_id: module number you want to connect to
        :param power_bar_user: user of PDU
        :param power_bar_pwd: password of PDU
        :param deploy_type: deploy type for app. can be 'container' or 'native'
        :param app_identifier: for 'container' deploy, the app identifier
        :param app_hostname: hostname of the logical device; has to be different than the hostname of the
                            chassis;
                            if not given, default is set to 'firepower'
        :return: None

        """

        publish_kick_metric('device.ssp.init', 1)

        deploy_type = deploy_type.lower()
        app_identifier = app_identifier.lower()
        if deploy_type == 'native':
            app_identifier = ''
        elif deploy_type == 'container':
            if app_identifier == '':
                raise RuntimeError('For container deploy type a non-empty app '
                                   'identifier must be provided.')
        else:
            raise RuntimeError('deploy_type must be either "native" or '
                               '"container"')

        # set login_username and login_password
        hostname = "({}|firepower)".format(hostname)
        self.patterns = SspPatterns(hostname, login_username, login_password,
                                    sudo_password, slot_id, app_hostname, deploy_type, app_identifier)

        # create the state machine that contains the proper attributes.

        self.sm = SspStateMachine(self.patterns)

        SspConstants.power_bar_server = power_bar_server
        SspConstants.power_bar_port = power_bar_port
        SspConstants.power_bar_user = power_bar_user
        SspConstants.power_bar_pwd = power_bar_pwd

        # line_class has to be also initialized
        self.line_class = SspLine
        logger.info("Done: Ssp instance created")
        super().__init__()

    def log_checks(self, ssp_line, list_files=['/var/log/boot_*'],
                   search_strings=['fatal', 'error'], exclude_strings=[], device_list='1', device_type='ftd'):
        """ Wrapper function to :
            1. Get logs from all the modules in device_list.
            2. Handle state changes dynamically for different modules.
        :param ssp_line: Instance of ssp line used to connect to device
                e.g. ssp_line = ssp.console_tenet('172.28.41.142','2007')
        :param exclude_strings: List of keywords to be excluded in the logs
        :param search_strings: List of keywords to be searched in the logs
        :param list_files: List of file paths for files to search in
        :param device_list: a string consisting of module numbers (FTD or ASA)
        :param device_type: 'ftd' or 'asa'
        e.g list_files = ['/var/log/boot_1341232','/var/log/boot_*']
            search_strings = ['fatal','error', 'crash']
            exclude_strings = ['ssl_flow_errors', 'firstboot.S09']

        """

        from .dialogs import SspDialogs
        from unicon.statemachine import Path
        for device_module in device_list.split(","):
            if device_type.lower() == 'ftd':
                self.sm.remove_path(self.sm.get_state('mio_state'),
                                    self.sm.get_state('fpr_module_state'))
                new_scope_to_fpr_path = Path(self.sm.get_state('mio_state'),
                                             self.sm.get_state('fpr_module_state'),
                                             "connect module {} console".format(
                                                 device_module),
                                             SspDialogs(self.patterns).d_mio_to_fpr_module)
                self.sm.add_path(new_scope_to_fpr_path)
                current_state = self.sm.current_state
                logger.info('In log_checks() 1, current state is {}'.format(current_state))
                try:
                    self.sm.go_to('sudo_state', ssp_line.spawn_id, timeout=90, hop_wise=True)
                except:
                    # Handle 'ftd not installed'
                    logger.info('ftd module {} not installed, exit ...'.format(device_module))
                    self.sm.go_to('mio_state', ssp_line.spawn_id)
                    continue
                log_output = self.get_logs(ssp_line=ssp_line, list_files=list_files,
                                           search_strings=search_strings, exclude_strings=exclude_strings)
                logger.info("""
                ***********************************************************
                Logs for the requested files in FTD Module {} are : -
                {}
                ***********************************************************
                """.format(device_module, log_output))
                self.sm.go_to('mio_state', ssp_line.spawn_id)

            elif device_type.lower() == 'asa':
                raise NotImplementedError('Log checks not implemanted for asa')

    def get_logs(self, ssp_line, list_files=['/var/log/'],
                 search_strings=['fatal', 'error'], exclude_strings=[]):
        """ Switch to root on the connected FTD and then return a list of
        unique errors from a given list of files. Switch back to scope.

        :param ssp_line: Instance of ssp line used to connect to FTD
                e.g. ssp_line = ssp.console_tenet('172.28.41.142','2007')
        :param list_files: List of file paths for files to search in
        :param search_strings: List of keywords to be searched in the logs
        :param exclude_strings: List of keywords to be excluded in the logs
                e.g list_files = ['/var/log/boot_1341232','/var/log/boot_*']
            search_strings = ['fatal','error', 'crash']
            exclude_strings = ['ssl_flow_errors', 'firstboot.S09']

        """

        self.sm.go_to('sudo_state', ssp_line.spawn_id, timeout=30)
        grep_command_list = []
        exclude_line = ''
        if exclude_strings:
            exclude_cmd = ['| grep -v {}'.format(string) for string in exclude_strings]
            exclude_line = ''.join(exclude_cmd)
        if list_files and search_strings:
            for file in list_files:
                for string in search_strings:
                    grep_command = "grep -Ii {} {} | sort -u {}".format(string, file, exclude_line)
                    grep_command_list.append(grep_command)
        output_log = ssp_line.execute_lines("\n".join(grep_command_list))
        # if ssp_line.chassis_line:
        #     self.sm.go_to('mio_state', ssp_line.spawn_id)
        # else:
        #     self.sm.go_to('ftd_state', ssp_line.spawn_id)
        return output_log

    def ssh_vty(self, ip, port, username='admin', password='Admin123',
                timeout=None, line_type='ssh', rsa_key=None):
        return super().ssh_vty(ip, port, username=username, password=password,
                               timeout=timeout, line_type='ssh_vty')


class SspLine(BasicLine):
    def __init__(self, spawn, sm, type, timeout=None):
        """Constructor of SspLine.

        :param spawn: spawn connection instance
        :param sm: state machine instance
        :param type: type of connection, e.g. 'telnet', 'ssh'
        :return: None

        """

        super().__init__(spawn, sm, type, timeout)
        self.line_type = 'SspLine'

        try:
            if type is 'ssh':
                logger.info('Connected to chassis through console')
                self.init_terminal()
            else:
                current_state = self.sm.current_state
                if current_state == 'mio_state':
                    logger.info('Connected to chassis')
                    self.execute_lines(SspInitCmds)
                elif current_state == 'fpr_module_state':
                    self.go_to('fireos_state', timeout=60)
                    logger.info('Connected to FTD')
                elif current_state == 'fireos_state':
                    logger.info('Connected directly to FTD')
        except StateMachineError as exc:
            logger.error('Unable to log into SSP: {}'.format(str(exc)), exc_info=True)

        # self.chassis_line = chassis_line

        # if self.chassis_line:
        #     self.sm.go_to('fpr_module_state', self.spawn_id)
        #     # no idea what this does
        #     # self.execute_lines(SspInitCmds)

        # Set default power bar info
        self.power_bar_server = SspConstants.power_bar_server
        self.power_bar_port = SspConstants.power_bar_port
        self.power_bar_user = SspConstants.power_bar_user
        self.power_bar_pwd = SspConstants.power_bar_pwd

    def bring_device_to_previous_state(self, initial_state, timeout):
        logger.info('Device was previously disconnected in {} state. Taking device back to the state it was in when'
                    'the disconnect happened ...'.format(initial_state))
        self.sm.go_to('any', self.spawn_id)
        super().reconfigure_terminal(timeout)
        # at reconnection, reconfigure the terminal if needed
        self.sm.go_to('fpr_module_state', self.spawn_id)
        self.sm.go_to(initial_state, self.spawn_id)

    def go_to(self, state, timeout=30):
        """
            Override parent go_to function to enable hop_wise flag.
        """
        try:
            super().go_to(state, hop_wise=True, timeout=timeout)
        except StateMachineError as e:
            # trying to handle session disconnect situations
            # see more details in the member function documentation
            self.__handle_session_disconnect_for_ftd_states(
                destination_state=state, state_machine_exception=e,
                timeout=timeout)

    def __handle_session_disconnect_for_ftd_states(self,
                                                   destination_state,
                                                   state_machine_exception,
                                                   timeout=10):
        """
            The following implementation tries to bring back the user to the
            state he was in on the ftd hosted over the chassis if the chassis
            fxos disconnects the current session.

            Example: The user goes in a specific ftd state (let's say expert)
            and does work there in his test script. Maybe after this he does
            some other work and as time passes at some point (depending on the
            chassis fxos default-auth settings) the chassis detects that the
            session timeout has expired and disconnects the user from the
            current session and takes him to the login screen. The user then
            wants to do some work on the ftd again and expects that he is
            in the last state that he was in before. And surprise, he was
            disconnected in the mean time. We thus try to relogin and take
            him back to the prevoius state he was in. This is valid only for
            ftd application states and only valid for ftds running on top of
            chassis hardware.

            :param destination_state: the state the user wants to go to
            :param state_machine_exception: the exception that helps us
            determine what happened (if a session disconnect happened)
            :param timeout: the timeout from the parent function used for
            state transitions

            If we are in any other state machine error that is caused by
            another reason different from a session disconnect the function
            does not handle it and throws the original error to the user.

            The function determines the states that are taken into account
            for this session disconnect behavior by interrogating the state
            machine ftd_states member defined in the ssp state machine.
        """
        if re.match('Failed.*bring.*to.*state.*', str(state_machine_exception)):
            if self.sm.ftd_states and self.sm.current_state not in \
                    self.sm.ftd_states:
                raise state_machine_exception
            i = 0
            # see if logout occurred and bring login prompt to focus
            while i < 3:
                try:
                    self.spawn_id.sendline()
                    if self.spawn_id.expect('[l|L]ogin: $', timeout=5):
                        break
                except:
                    pass
                i += 1
            if i >= 3:
                # something other than a logout occurred. check first if it has recovered
                if not self.sm.current_state == 'fpr_module_state':
                    raise state_machine_exception
                return
            self.sm.update_cur_state('prelogin_state')
            try:
                super().go_to('fpr_module_state', hop_wise=True,
                              timeout=timeout)
            except:
                pass
            super().go_to('any', hop_wise=True, timeout=timeout)
            super().go_to(destination_state, hop_wise=True, timeout=timeout)
        else:
            raise state_machine_exception

    def init_terminal(self):
        """Initialize terminal size."""
        try:
            self.go_to('any')
            self.go_to('mio_state', timeout=60)
        except StateMachineError as exc:
            logger.error('Cannot initialize MIO terminal in SSP: {}'.format(str(exc)), exc_info=True)
            return

        self.execute_lines(SspInitCmds)

    # TODO
    # check with owners
    def wait_until_device_on(self, timeout=600):
        """Waits until device is on

        :param timeout: wait time for the device to boot up
        :return None

        """

        # The system will reboot, wait for the following prompts
        d1 = Dialog([
            ['vdc 1 has come online', None, None, False, False],
            ['SW-DRBG health test passed', None, None, False, False],
        ])
        d1.process(self.spawn_id, timeout=timeout)

        # sleep 120 seconds to avoid errors like:
        # FPR4120-1-A# scope system
        # Software Error: Exception during execution:
        # [Error: Timed out communicating with DME]
        # after chasis is upgraded, device is rebooted
        time.sleep(120)
        self.init_terminal()

    def set_power_bar(self, power_bar_server, power_bar_port, power_bar_user='admn', power_bar_pwd='admn'):
        """Set the power bar info for this device.

        :param power_bar_server: comma-separated string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string of power ports on the PDU's
        :param power_bar_user: comma-separated string of usernames for the PDU's
        :param power_bar_pwd: comma-separated string of passwords for the PDU's
        :return: None
        """
        self.power_bar_server = power_bar_server
        self.power_bar_port = power_bar_port
        self.power_bar_user = power_bar_user
        self.power_bar_pwd = power_bar_pwd

    # TODO
    # check with owners
    def power_cycle(self, power_bar_server=None, power_bar_port=None,
                    wait_until_device_is_on=True, timeout=600,
                    power_bar_user='admn', power_bar_pwd='admn'):
        """Reboots a device from a Power Data Unit equipment.
        Use power_cycle(power_bar_server=None, power_bar_port=None, ...) to use already-set PDU info.

        :param power_bar_server: comma-separated string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string of power ports on the PDU's
        :param wait_until_device_is_on: True if wait for the device to boot up, False else
        :param timeout: wait time for the device to boot up
        :param power_bar_user: comma-separated string of usernames for the PDU's
        :param power_bar_pwd: comma-separated string of passwords for the PDU's
        :return: status of power cycle result, True or False
        """
        # If the existing server/port is not valid and the server/port argument is not valid, return None
        if (not self.power_bar_server and not power_bar_server) or power_bar_server == "" or \
                (not self.power_bar_port and not power_bar_port) or power_bar_port == "":
            logger.error('Invalid server/port')
            return None

        # If new server and port are provided, replace the existing power bar
        if power_bar_server or power_bar_port:
            self.set_power_bar(power_bar_server, power_bar_port, power_bar_user, power_bar_pwd)

        result = power_cycle_all_ports(self.power_bar_server, self.power_bar_port, self.power_bar_user,
                                       self.power_bar_pwd)

        logger.info('Wait for device to be up running ...')
        if wait_until_device_is_on:
            self.wait_until_device_on(timeout=timeout)
        return result

    def _get_download_status(self, image_name):
        """Gets the status of download

        :param image_name: the name of the image. it should look like:
        fxos-k9.2.0.1.68.SPA
        :return: status as 'Downloaded' or 'Downloading'

        """

        output = self.execute('show download-task {} detail | grep State'
                              ''.format(image_name))

        r = re.search('State: (\w+)', output)

        status = 'Unknown'
        if r:
            status = r.group(1)
            logger.info("download status: {}".format(status))
        return status

    def _wait_till_download_complete(self, file_url, wait_upto=1800):
        """Waits until download completes

        :param file_url: should look like one of the following:
            scp://root@10.30.5.104:/auto/stg/automation/ci/ssp/branch/
            abbey_road/sthangad/qpb/sr2/fxos-k9.2.0.1.68.SPA
            tftp://172.23.47.63/cisco-ftd.6.2.0.296.SPA.csp
        :param wait_upto: how long to wait for download to complete in seconds
        :return: None

        """

        if file_url.startswith("scp"):
            try:
                r = re.search('(\w+)://(\w+)@[\w.\-]+:([\w\-./]+):([\w\-./]+)', file_url)
                assert r, "unknown file_url: {}".format(file_url)
                full_path = r.group(4)
            except:
                r = re.search('(\w+)://(\w+)@[\w.\-]+:([\w\-./]+)', file_url)
                assert r, "unknown file_url: {}".format(file_url)
                full_path = r.group(3)
        elif file_url.startswith("tftp"):
            r = re.search('(\w+)://[\w.\-]+/([\w\-./]+)', file_url)
            assert r, "unknown file_url: {}".format(file_url)
            full_path = r.group(2)
        elif file_url.startswith("http"):
            r = re.search('(\w+)://[\w.\-]+/([\w\-./]+)', file_url)
            assert r, "unknown file_url: {}".format(file_url)
            full_path = r.group(2)
        else:
            raise RuntimeError("Incorrect file url download protocol")

        image_name = os.path.basename(full_path)
        start_time = datetime.datetime.now()
        elapsed_time = 0
        download_status = ""
        while elapsed_time < wait_upto:
            logger.info("sleep 10 seconds for download to complete")
            time.sleep(10)
            download_status = self._get_download_status(image_name)
            if download_status == 'Downloaded':
                logger.info("download completed for {}".format(image_name))
                return download_status
            elif download_status == "Downloading":
                logger.info("downloading is in progress for {}".format(image_name))
            elif download_status == "Failed":
                return download_status
            now = datetime.datetime.now()
            elapsed_time = (now - start_time).total_seconds()
        raise RuntimeError("download took too long: {}".format(image_name))

    def is_bundle_on_chassis(self, fxos_url):
        """Checks to see if the update bundle is already on the chasis.

        :param fxos_url: address of fxos package
        :return: None

        """

        self.go_to('mio_state')
        existing_packages = self.get_fxos_packages()
        image_name = os.path.basename(fxos_url)
        if image_name in [package.name for package in existing_packages]:
            return True
        return False

    def get_fxos_packages(self):
        """Get packages currently downloaded on the box."""

        self.go_to('mio_state')
        self.execute_lines('top\nscope firmware')

        output = self.execute('show package')
        find_hyphens = [m.end() for m in re.finditer('-{2,}', output)]

        start = find_hyphens[-1] if find_hyphens else 0
        output = output[start:].strip()

        package_list = []
        Package = collections.namedtuple('Package', ['name', 'version'])
        if output:
            for line in output.split('\n'):
                package_name, package_version = line.split()
                package_list.append(Package(name=package_name, version=package_version))
        return package_list

    def download_fxos(self, fxos_url, file_server_password="", http_url=""):
        """Download image of FXOS.

        :param fxos_url: fxos url to download the image, you can also use your own container instead (see example)
            e.g. scp://pxe@172.23.47.63:/tftpboot/fxos-k9.2.1.1.64.SPA
            e.g. scp://root@container_ip:container_port:/tmp/fxos-k9.2.1.1.64.SPA
        :param file_server_password: sftp server password
        :param http_url: Url with the destination of the fxos file. In case such is provided, it will first download it
                         to the container, then continue normally with the scp download

        """

        bundle_package_name = fxos_url.split("/")[-1].strip()
        version = self.get_bundle_package_version(bundle_package_name)
        if self.is_firmware_monitor_ready(version):
            # the bundle package has already been installed
            logger.info("fxos bundle package {} has been installed, " \
                        "nothing to do".format(bundle_package_name))
            return

        if self.is_bundle_on_chassis(fxos_url):
            return

        retry_count = MAX_RETRY_COUNT
        while retry_count > 0:

            if "http://" in http_url:
                try:
                    subprocess.call("wget {} -P {}".format(http_url, "/tmp/"), shell=True)
                    logger.info("Download on container complete. Starting SCP to chassis.")
                except:
                    raise logger.error("Issue downloading the fxos file to the container.")

            d1 = Dialog([
                ['{} login: '.format(self.sm.patterns.dev_hostname), 'sendline({})'.format(self.sm.patterns.login_username),
                 None, True, False],
                ['Password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
                ['.*Successful login attempts for user.*', None, None, False, False],
            ])

            server_timeout = True
            try:
                d1.process(self.spawn_id)
            except:
                server_timeout = False

            if server_timeout:
                logger.info("Download took to long and you were disconnected from the device. Reconnecting.")
                self.spawn_id.sendline("scope firmware")

            self.spawn_id.sendline('download image {}'.format(fxos_url))
            time.sleep(5)

            d1 = Dialog([
                ['Invalid Value', None, None, False, False],
                ['Download failure - No such file', None, None, False, False],
                ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
                ['Password:', 'sendline({})'.format(file_server_password),
                 None, True, False],
                [self.sm.get_state('mio_state').pattern, None, None, False, False],
            ])
            response = d1.process(self.spawn_id)
            if response and 'Invalid Value' in response.match_output:
                raise RuntimeError("Download Failed - unsupported download protocol")

            if response and 'Download failure - No such file' in response.match_output:
                raise RuntimeError("Download Failed - File not found on the server")

            status = self._wait_till_download_complete(fxos_url)

            if status == "Failed":
                retry_count -= 1
                if retry_count == 0:
                    raise RuntimeError(
                        "Download failed after {} tries. Please check details again: {}".format(MAX_RETRY_COUNT,
                                                                                                fxos_url))
                logger.info("Download failed. Trying to download {} more times after a 30 sec sleep".format(
                    retry_count))
                time.sleep(30)
            elif status == "Downloaded":
                logger.info("Download on chassis complete!")
                return

    def download_csp(self, csp_url, file_server_password=""):
        """Download image of application for QP and BS.

        :param csp_url: csp url to download the image
            e.g. scp://pxe@172.23.47.63:/tftpboot/cisco-ftd.6.2.0.297.SPA.csp
        :param file_server_password: sftp server password

        """
        self.go_to('mio_state')
        image_name = os.path.basename(csp_url)
        app_version = re.search(r'\d+\.\d+\.\d+\.\d+', image_name).group(0)
        apps = self.execute_lines('top\nscope ssa\nshow app')
        found_entry = re.search(r'\s+.*?\s*%s\s+' % re.escape(app_version),
                                apps)
        if found_entry:
            logger.info('Found CSP application already registered and '
                        'downloaded on the device.')
            return

        self.execute_lines('top\nscope ssa\nscope app-software')

        retry_count = MAX_RETRY_COUNT

        while retry_count > 0:

            self.spawn_id.sendline('download image {}'.format(csp_url))

            d1 = Dialog([
                ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
                ['Password:', 'sendline({})'.format(file_server_password),
                 None, True, False],
                [self.sm.get_state('mio_state').pattern, None, None, False, False],
            ])
            d1.process(self.spawn_id)

            status = self._wait_till_download_complete(csp_url)

            if status == "Failed":
                retry_count -= 1
                if retry_count == 0:
                    raise RuntimeError(
                        "Download failed after {} tries. Please check details again: {}".format(MAX_RETRY_COUNT,
                                                                                                csp_url))
                logger.info("Download failed. Trying to download {} more times".format(retry_count))
            elif status == "Downloaded":
                return

    def parse_firmware_monitor(self):
        """"show firmware Monitor" gives something like this:
          FPRM:
            Package-Vers: 1.1(4.95)
            Upgrade-Status: Ready.

          Fabric Interconnect A:
            Package-Vers: 2.0(1.68)
            Upgrade-Status: Upgrading

          Chassis 1:
            Server 1:
                Package-Vers: 2.0(1.68)
                Upgrade-Status: Upgrading

        :return: namedtuple

        """

        cmd_lines = """
            top
            scope system
            show firmware monitor
        """

        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)
        fprm = output.find('FPRM:')
        fabric = output.find('Fabric Interconnect A:')
        chassis = output.find('Chassis 1:')

        fprm_section = output[fprm:fabric]
        fprm = self._parse_firmware_monitor_version_status(fprm_section)
        fabric_section = output[fabric:chassis]
        fabric = self._parse_firmware_monitor_version_status(fabric_section)
        chassis_section = output[chassis:]
        chassis = self._parse_firmware_monitor_version_status(chassis_section)

        logger.debug('fprm={}, fabric={}, chassis={}'.format(fprm, fabric, chassis))
        FirmwareMonitor = collections.namedtuple('FirmwareMonitor',
                                                 ['fprm', 'fabric', 'chassis'])
        firmware_monitor = FirmwareMonitor(fprm=fprm, fabric=fabric, chassis=chassis)

        return firmware_monitor

    def _parse_firmware_monitor_version_status(self, output):
        """
        :param output: should look like:
          FPRM:
            Package-Vers: 1.1(4.95)
            Upgrade-Status: Ready
        :return: version_status

        """

        VersionStatus = collections.namedtuple('VersionStatus', ['version',
                                                                 'status'])
        r = re.search("Package-Vers: ([^\r\n]+)", output)
        if not r:
            version_status = VersionStatus(version='Unknown', status='Unknown')
            return version_status
        v = r.group(1)
        r = re.search("Upgrade-Status: ([^\r\n]+)", output)
        s = r.group(1)
        version_status = VersionStatus(version=v, status=s)
        return version_status

    def get_port_channel_list(self):
        """
        Get port channel list from eth-up/fabric a
        Sample output:

        Port Channel:
            Port Channel Id Name             Port Type          Admin State Oper State       State Reason
            --------------- ---------------- ------------------ ----------- ---------------- ------------
            48              Port-channel48   Cluster            Disabled    Admin Down       Administratively down

        Returns:
            port_channel_list element with named tuple
        """
        cmd_lines = '''
            top
            scope eth-up
            scope fabric a
            show port-channel
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)
        prompt = self.sm.get_state(self.sm.current_state).pattern
        match = re.search(prompt, output)
        if match:
            end = match.span()[0]
            output = output[:end].strip()

        PortChannel = collections.namedtuple('PortChannel', [
            'id', 'name', 'port_type', 'admin_state', 'operational_state'])
        port_channels_list = []
        if output:
            start = [m.end() for m in re.finditer('-{2,}', output)][-1]
            output = output[start:].strip()
            for line in output.split('\n'):
                line = re.split(r'\s{2,}', line.strip())
                pc_id = line[0]
                pc_name = line[1]
                port_type = line[2]
                admin_state = line[3]
                oper_state = line[4]
                port_channels_list.append(PortChannel(id=pc_id, name=pc_name,
                                                      port_type=port_type, admin_state=admin_state,
                                                      operational_state=oper_state))
                # logger.info('Port-channel %s name: %s, port_type: %s, admin state: %s, oper state: %s' %
                #     (pc_id, pc_name, port_type, admin_state, oper_state))

        return port_channels_list

    def get_port_channel_member(self, pc_id):
        """
        Get port channel memeber ports given port channel id
        Sample output:

        Member Port:
            Port Name       Membership         Oper State       State Reason
            --------------- ------------------ ---------------- ------------
            Ethernet1/1     Down               Admin Down       Administratively down
            Ethernet1/2     Down               Admin Down       Administratively down
            Ethernet1/3     Down               Admin Down       Administratively down
            Ethernet1/4     Down               Admin Down       Administratively down
            Ethernet1/5     Down               Admin Down       Administratively down
            Ethernet1/6     Down               Admin Down       Administratively down
            Ethernet1/7     Down               Admin Down       Administratively down
            Ethernet1/8     Down               Admin Down       Administratively down

        Returns:
            member_ports_list element with named tuple
        """
        self.go_to('mio_state')
        cmd_lines = '''
            top
            scope eth-up
            scope fabric a
            scope port-channel %s
            show member-port
        ''' % pc_id
        output = self.execute_lines(cmd_lines)
        prompt = self.sm.get_state(self.sm.current_state).pattern
        match = re.search(prompt, output)
        if match:
            end = match.span()[0]
            output = output[:end].strip()

        MemberPort = collections.namedtuple('MemberPort', [
            'name', 'membership', 'operational_state'])
        member_ports_list = []
        if output:
            start = [m.end() for m in re.finditer('-{2,}', output)][-1]
            output = output[start:].strip()
            for line in output.split('\n'):
                line = re.split(r'\s{2,}', line.strip())
                name = line[0]
                membership = line[1]
                oper_state = line[2]
                member_ports_list.append(MemberPort(name=name,
                                                    membership=membership, operational_state=oper_state))
                # logger.info('Member port name: %s, membership: %s, oper state: %s' %
                #     (name, membership, oper_state))

        return member_ports_list

    def get_logical_device_list(self):
        """Get the list of logical device objects Scope: ssa; Command: show
        logical-device detail.

        # output should look like this:
        # Logical Device:
              Name: 9300-1-cluster
              Description:
              Slot ID: 1,2,3
              Mode: Clustered
              Oper State: Ok
              Template Name: ftd
              Error Msg:
              Switch Configuration Status: Ok
              Resource Profile Name:
              Resource Profile DN:
        :return: logical_device_list

        """

        cmd_lines = '''
            top
            scope ssa
            show logical-device detail
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)

        LogicalDevice = collections.namedtuple('LogicalDevice', [
            'name', 'slot_id', 'mode', 'operational_state', 'template_name', 'error_msg'])
        logical_device_list = []

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Name':
                vname = a_value
                continue
            if a_name == 'Slot ID':
                vslot = a_value
                continue
            if a_name == 'Mode':
                vmode = a_value
                continue
            if a_name.find('Oper') is not -1:
                # Capture 'Operational' and 'Oper'
                if a_name.find('State') is not -1:
                    voper = a_value
                    continue
            if a_name == 'Template Name':
                vtemp = a_value
                continue
            if a_name == "Error Msg":
                verr_msg = a_value
                logical_device = LogicalDevice(name=vname,
                                               slot_id=vslot,
                                               mode=vmode,
                                               operational_state=voper,
                                               template_name=vtemp,
                                               error_msg=verr_msg)
                logical_device_list.append(logical_device)
                logger.info(str(logical_device_list))
                continue

        return logical_device_list

    def get_app_instance_list(self):
        """
        Get the list of application instance objects
        Scope: ssa; Command: show app-instance detail
        FP9300-2-A /ssa # show app-instance detail
        App Name: ftd
        Slot ID: 1
        Admin State: Enabled
        Oper State: Online
        Running Version: 6.2.0.362
        Startup Version: 6.2.0.362
        Cluster State: In Cluster
        Cluster Role: Slave
        Current Job Type: Start
        Current Job Progress: 100
        Current Job State: Succeeded
        Clear Log Data: Available
        Error Msg:
        Hotfixes:
        Externally Upgraded: No
        ...

        :return app_instance_list

        """

        cmd_lines = '''
            top
            scope ssa
            show app-instance detail
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        AppInstance = collections.namedtuple('AppInstance', [
            'application_name', 'identifier', 'deploy_type', 'slot_id', 'admin_state',
            'operational_state', 'running_version', 'startup_version', 'cluster_oper_state'])
        app_instance_list = []

        identifier = ''
        deploy_type = ''
        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name.startswith('App'):
                # Capture both App Name for new version and Application Name for older version
                vname = a_value
                continue
            if a_name == 'Identifier':
                identifier = a_value
            if a_name == 'Deploy Type':
                deploy_type = a_value
            if a_name == 'Slot ID':
                vslot = a_value
                continue
            if a_name == 'Admin State':
                vadmin = a_value
                continue
            if a_name.startswith('Oper'):
                # Capture 'Operational' and 'Oper'
                if a_name.find('State') is not -1:
                    voper = a_value
                    continue
            if a_name == 'Running Version':
                vrunning = a_value
                continue
            if a_name == 'Startup Version':
                vstartup = a_value
                continue
            if a_name == 'Cluster State':
                # Frangelico and afterwards
                vcluster_s = a_value
                continue
            if a_name == 'Cluster Role':
                # Frangelico and afterwards
                vcluster_r = a_value
                app_instance = AppInstance(application_name=vname,
                                           identifier=identifier,
                                           deploy_type=deploy_type,
                                           slot_id=vslot,
                                           admin_state=vadmin,
                                           operational_state=voper,
                                           running_version=vrunning,
                                           startup_version=vstartup,
                                           cluster_oper_state='{} {}'.format(vcluster_s, vcluster_r))
                app_instance_list.append(app_instance)
                logger.info(str(app_instance_list))
                continue
            if a_name == 'Cluster Oper State':
                # Everclear
                vcluster_oper_s = a_value
                app_instance = AppInstance(application_name=vname,
                                           identifier=identifier,
                                           deploy_type=deploy_type,
                                           slot_id=vslot,
                                           admin_state=vadmin,
                                           operational_state=voper,
                                           running_version=vrunning,
                                           startup_version=vstartup,
                                           cluster_oper_state=vcluster_oper_s)
                app_instance_list.append(app_instance)
                logger.info(str(app_instance_list))
                continue

        return app_instance_list

    def get_equipped_slot_list(self):
        """Get the list of equipped slot list

        Scope: top
        Command: show server status detail

        # output should look like this:
        # show server status detail
        Server 1/1:
            Slot Status: Equipped
            Equipped Conn Path: A
            Equipped Conn Status: A
            Equipped Managing Instance: A
            Availability: Unavailable
            Admin State: In Service
            Overall Status: Ok
            Oper Qualifier: N/A
            Discovery: Complete
            Current Task:
            Check Point: Discovered

        Server 1/2:
            Slot Status: Equipped
            Equipped Conn Path: A
            Equipped Conn Status: A
            Equipped Managing Instance: A
            Availability: Unavailable
            Admin State: In Service
            Overall Status: Ok
            Oper Qualifier: N/A
            Discovery: Complete
            Current Task:
            Check Point: Discovered

        Server 1/3:
            Slot Status: Empty
            Equipped Conn Path: Unknown
            Equipped Conn Status: Unknown
            Equipped Managing Instance:
            Availability:
            Admin State:
            Overall Status:
            Oper Qualifier:
            Discovery:
            Current Task:
            Check Point:
        :return: slot_list

        """

        cmd_lines = '''
            top
            show server status detail
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        slot_list = []

        slot_id = 1
        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Slot Status':
                if a_value == 'Equipped':
                    slot_list.append('{}'.format(slot_id))
                slot_id += 1
        logger.info('======= equipped slot list is {}'.format(str(slot_list)))
        return slot_list

    def get_app_list(self):
        """Get the list of application objects Scope: ssa; Command: show app.

        # output should look like this:
        # Application:
        # Name       Version    Description Author     Deploy Type CSP Type    Is Default App
        # ---------- ---------- ----------- ---------- ----------- ----------- --------------
        # asa        9.6.1      N/A         cisco      Native      Application No
        # asa        9.6.1.109  N/A         cisco      Native      Application Yes
        # ftd        6.0.1.1213 N/A         cisco      Native      Application Yes

        :return: app_list

        """

        cmd_lines = '''
            top
            scope ssa
            show app
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        # consume the lines before the dashed lines:
        r = re.search('\s+Is Default App', output)
        if not r:
            return []  # nothing found
        output = output[r.span()[1]:].strip()
        r = re.search('(\-+ ){5,}\-+', output)
        if not r:
            return []
        output = output[r.span()[1]:].strip()

        App = collections.namedtuple('App', ['name', 'version', 'description',
                                             'author', 'deploy_type',
                                             'csp_type', 'is_default_app'])
        app_list = []

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            r = re.search('^(\w+)\s+([\d\.]+)\s+([\w/]+)?\s+(\w+)\s+([\w,]+)\s+'
                          '(\w+)\s+(\w+)', line)
            if not r:
                continue
            app = App(name=r.group(1),
                      version=r.group(2),
                      description=r.group(3),
                      author=r.group(4),
                      deploy_type=r.group(5),
                      csp_type=r.group(6),
                      is_default_app=r.group(7),
                      )
            app_list.append(app)

        return app_list

    def wait_till(self, stop_func, stop_func_args, wait_upto=600):
        """Wait till stop_func returns True.

        :param wait_upto: in seconds
        :param stop_func: when stop_func(stop_func_args) returns True,
            break out.
        :param stop_func_args: see above.
        :param sleep_step: sleeps this long (in seconds between each call to
            stop_func(stop_func_args).
        :return

        """

        start_time = datetime.datetime.now()
        elapsed_time = 0

        while elapsed_time < wait_upto:
            result = stop_func(*stop_func_args)
            logger.debug('wait_till result is:')
            logger.debug(result)
            logger.debug('elapsed_time={}'.format(elapsed_time))
            if result:
                return
            else:
                logger.debug("sleep 10 seconds and test again")
                time.sleep(10)
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
        raise RuntimeError("{}({}) took too long to return True" \
                           "".format(stop_func, stop_func_args))

    def get_slot_operational_state(self, slot_id):
        """Get operational state for slot_id, e.g. Online.

        :return: operational state

        """

        cmd_lines = """
            top
            scope ssa
            scope slot {}
            show detail | grep Oper
            """.format(slot_id)
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        r = re.search("Oper(.*) State: ([\w ]+)", output)

        return r.group(2)

    def is_slot_online(self, slot_id):
        """Check if the slot of slot_id is online.

        :param slot_id: module slot ID
        :return: True if operational state is Online, False otherwise

        """

        return self.get_slot_operational_state(slot_id) == 'Online'

    def wait_till_slot_online(self, slot_id, wait_upto=300):
        """Wait till module of slot_id is Online.

        :param slot_id: module slot ID
        :param wait_upto: wait time in seconds
        :return: None

        """

        self.wait_till(self.is_slot_online, (slot_id,))

    def is_app_instance_ready(self, app_instance_name, slot_id, in_cluster_mode=False):
        """Check whether the application instance is Enabled and Online.

        :param app_instance_name: application instance name
        :param slot_id: module slot id
        :param in_cluster_mode: True if configure application in Cluster Mode
                                False if configure application in Standalone Mode
        :return: True if application instance is Enabled and Online.
                      In Cluster Mode, each slot is Master or Slave

        """

        logger.info("=========== Wait for app_instance: {} at slot: {} to be "
                    "Enabled and Online ===========".format(app_instance_name, slot_id))
        logger.info("Is in cluster mode: {}".format(str(in_cluster_mode)))
        app_instance_list = self.get_app_instance_list()
        if app_instance_list == None or len(app_instance_list) == 0:
            logger.info('return False in is_app_instance_ready when '
                        'app_instance_list is empty')
            return False
        app_instance = [a for a in app_instance_list if
                        (a.identifier == app_instance_name or a.application_name == app_instance_name) and
                        int(a.slot_id) == int(slot_id)]
        assert len(app_instance) == 1, "Found {} app instances for app {} in " \
                                       "slot {}".format(len(app_instance),
                                                        app_instance_name, slot_id)
        app_instance = app_instance[0]
        if app_instance.admin_state == 'Enabled' and \
                app_instance.operational_state == 'Online':
            if not in_cluster_mode:
                return True
            state = app_instance.cluster_oper_state
            # Handle 'Not In Cluster' as well
            if state.startswith('In Cluster'):
                # Everclear doesn't have 'Master' or 'Slave' role
                if state == 'In Cluster':
                    return True
                # Frangelico has the role
                if 'Master' in state or 'Slave' in state:
                    return True
        logger.info('return False in is_app_instance_ready when admin_state '
                    'is not Enabled or operational_state is not Online')
        if app_instance.operational_state == "Install Failed":
            raise RuntimeError('Install Failed.')
        return False

    def delete_all_logical_devices(self):
        """Delete all logical devices.

        :return: None

        """

        alist = self.get_logical_device_list()
        if alist == None or len(alist) == 0:
            logger.debug('no logical device found, nothing to do.')
        for a in alist:
            cmd_lines = """
                  top
                  scope ssa
                  delete logical-device {}
                  commit-buffer
            """.format(a.name)
            logger.info('logical device {} is to be deleted ...'.format(a.name))

            self.go_to('mio_state')
            self.execute_lines(cmd_lines)

            logger.info('logical-device {} deleted'.format(a.name))

        alist = self.get_logical_device_list()
        assert (alist == None or len(alist) == 0), \
            "Cannot delete all logical-device"

    def delete_all_app_instances(self):
        """Delete all application instances.

        :return: None

        """

        app_instance_list = self.get_app_instance_list()
        if app_instance_list == None or len(app_instance_list) == 0:
            logger.info('no app-instance found, nothing to do.')

        for a in app_instance_list:
            cmd_lines = """
                  top
                  scope ssa
                  scope slot {}
                  delete app-instance {} {}
                  commit-buffer
            """.format(a.slot_id, a.application_name, a.identifier)
            self.go_to('mio_state')
            self.execute_lines(cmd_lines)

            logger.info('Slot {}: app-instance {} {} deleted'.format(a.slot_id, a.application_name, a.identifier))

        app_instance_list = self.get_app_instance_list()
        assert (app_instance_list == None or
                len(app_instance_list) == 0), "Cannot delete all app-instance"

    def get_bundle_package_version(self, bundle_package_name):
        """Get bundle package version from the bundle package name.

        :param bundle_package_name: bundle package name, e.g. fxos-k9.2.1.1.64.SPA
        :return: bundle package version: e.g. 2.1(1.64)

        """

        cmd_lines = """
            top
            scope firmware
            show package | grep {}
        """.format(bundle_package_name)
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        r = re.search("{}\s+(([\w.()-]+))".format(bundle_package_name), output)
        # Check whether the package exists in show package
        # If not extract the version from bundle_package_name
        if not r:
            l = bundle_package_name.split('.')
            version = '{}.{}({}.{})'.format(l[1], l[2], l[3], l[4])
            return version

        return r.group(1)

    def wait_till_app_instance_ready(self, app_instance_name, slot_id,
                                     in_cluster_mode=False,
                                     wait_upto=300):
        """Wait till the app_instance's 'Admin State' is 'Enabled', and
        'Oper[ational] State' is 'Online'.

        :param app_instance_name:
        :param slot_id:
        :param in_cluster_mode:
        :param wait_upto: in seconds
        :return: None

        """

        self.wait_till(self.is_app_instance_ready,
                       (app_instance_name, slot_id, in_cluster_mode), wait_upto=wait_upto)

    def create_app_instance(self, cmd_lines, wait_upto=300):
        """Creates an instance of application

        :param cmd_lines: multi-line commands to create the app instance.
          It should look like this:
              top
              scope ssa
              scope slot 1
              create app-instance asa
              set startup-version 9.6.1.11
              commit-buffer
              scope ssa
              create logical-device asa1 asa 1 standalone
              commit-buffer
              create external-port-link l1 Ethernet1/1 asa
              commit-buffer
        :param wait_upto: in seconds
        :return: None

        """

        r = re.search("scope slot (\d+)", cmd_lines)
        slot_id = r.group(1)
        r = re.search("create app-instance (\w+)", cmd_lines)
        app_instance_name = r.group(1)

        # Secret bootstrap keys don't work with execute_lines, so find and extract them first
        manual_cmd_list = re.split(r'(create bootstrap-key-secret .*?exit\s)', cmd_lines,
                                   flags=re.MULTILINE + re.DOTALL)

        # Run cmd_lines to create the app-instance and logical-device
        # Set longer timeout value for "accept_license_agreement" to finish
        response_cmd = ''
        self.go_to('mio_state')

        if len(manual_cmd_list) != 1:
            for cmd_block in manual_cmd_list:
                if 'create bootstrap-key-secret' in cmd_block:
                    block_lines = cmd_block.split('\n')
                    for block_line in block_lines:
                        # Set the prompt to "Value:" after sending "set value" so that the value isn't skipped
                        response_cmd += self.execute(block_line, prompt='Value:', timeout=2) \
                            if 'set value' in block_line else self.execute_lines(block_line, timeout=2)
                else:
                    response_cmd += self.execute_lines(cmd_block, timeout=60)
        else:
            # There are no secret bootstrap keys in cmd_lines
            response_cmd = self.execute_lines(cmd_lines, timeout=60)

        if response_cmd.rfind('Error: Update failed') != -1:
            raise RuntimeError('Error: Update failed. App instance is not supported by current FXOS')

        # check that it is created
        app_instance_list = self.get_app_instance_list()
        if app_instance_list is not None and len(app_instance_list) > 0:
            app_instance = [a for a in app_instance_list if
                            int(a.slot_id) == int(slot_id) and
                            (a.identifier == app_instance_name or a.application_name == app_instance_name)]
            assert len(app_instance) == 1, "app_instance {} not created in slot " \
                                           "{}".format(app_instance_name, slot_id)

        self.wait_for_app_creation(slot_id, app_instance_name, wait_upto)

    def wait_for_app_creation(self, slot_id, app_instance_name, wait_upto):
        # wait till app is online
        self.wait_till_slot_online(slot_id)
        self.wait_till_app_instance_ready(app_instance_name, slot_id,
                                          in_cluster_mode=False,
                                          wait_upto=wait_upto)
        if 'ftd' in app_instance_name:
            logger.info('Connecting to FTD from slot {} and changing password '.format(slot_id))
            # wait up to 10 minutes for the ftd to be initialized
            self.go_to('fireos_state', timeout=600)
            logger.info('Password changed on FTD from slot {}'.format(slot_id))
            self.go_to('mio_state')

    def bounce_app_instance(self, slot_num, app_instance_name):
        """
        When user create an app instance, sometimes they need to bounce it,
        meaning to disable it, then enable it. It cannot be done right away,
        and needs to handle a wait.

        For example, the following will be seen:

        FPR4120-6-Rack10-A /ssa/slot/app-instance* # disable
        FPR4120-6-Rack10-A /ssa/slot/app-instance* # commit-buffer
        FPR4120-6-Rack10-A /ssa/slot/app-instance # enable
        FPR4120-6-Rack10-A /ssa/slot/app-instance* # commit-buffer
        Error: Update failed: [Logical Device is being provisioned. Please
             wait for the application instance to be started.]
        <after a few minutes>
        FPR4120-6-Rack10-A /ssa/slot/app-instance* # commit-buffer
        FPR4120-6-Rack10-A /ssa/slot/app-instance #

        :param slot_num:
        :param app_instance_name:

        :return: None
        """

        disable_cmds = """
            top
            scope ssa
            scope slot {}
            enter app-instance {}
            disable
            commit-buffer
        """.format(slot_num, app_instance_name)
        self.execute_lines(disable_cmds, timeout=60)

        enable_cmds = """
            top
            scope ssa
            scope slot {}
            enter app-instance {}
            enable
            commit-buffer
        """.format(slot_num, app_instance_name)

        # try every 10 seconds, up to 10 min
        for _ in range(60):
            r = self.execute_lines(enable_cmds)
            if 'Please wait for the application instance to be started.' in r:
                logger.debug('app is busy, can not enable')
                time.sleep(10)
                continue
            else:
                logger.debug('app is enabled')
                break
        else:
            raise RuntimeError('Can not enable app after 10 min')

    def create_app_instance_in_cluster(self, cmd_lines,
                                       app_instance_name,
                                       slot_list_str,
                                       wait_upto=300):
        """Accept license agreement Set default ftd app Create app-instance for
        each slot.

        :param cmd_lines: multi-line commands to create the app instance.
           cmd_lines like this:
           scope app ftd 6.2.0.291
               accept-license-agreement
               set-default
           exit
        :param app_instance_name: the app instance name for each slot, e.g. 'ftd'
        :param slot_list_str: the slot list for the cluster, e.g. '1,2,3'
        :param wait_upto: the wait time for the modules to reboot and up online
        :return: None

        """

        # validate params
        if app_instance_name is None:
            raise RuntimeError("Please set parameter to app_instance_name, e.g. 'ftd'")
        if slot_list_str is None:
            raise RuntimeError("Please set parameter to slot_list_str, e.g. '1,2,3'")
        slot_list = slot_list_str.split(',')
        slot_list = self.get_equipped_slot_list()

        # run cmd_lines to create it.
        # set longer timeout value for "accept_license_agreement" to finish
        self.go_to('mio_state')
        # self.execute_lines(cmd_lines, timeout=60)

        # check that app-instance is created
        app_instance_list = self.get_app_instance_list()
        if app_instance_list != None and len(app_instance_list) > 0:
            for slot_id in slot_list:
                # Wait for each slot to be Enabled and Online
                app_instance = [a for a in app_instance_list if
                                int(a.slot_id) == int(slot_id) and
                                a.application_name == app_instance_name]
                assert len(app_instance) == 1, "app_instance {} not created in slot " \
                                               "{}".format(app_instance_name, slot_id)
            for slot_id in slot_list:
                # wait till each slot is online
                self.wait_till_slot_online(slot_id)
                self.wait_till_app_instance_ready(app_instance_name,
                                                  slot_id,
                                                  in_cluster_mode=True,
                                                  wait_upto=wait_upto)
        for slot_id in slot_list:
            logger.info('Connecting to FTD from slot {} and changing password '.format(slot_id))
            p = SspPatterns(hostname=self.sm.patterns.dev_hostname,
                            login_username=self.sm.patterns.login_username,
                            login_password=self.sm.patterns.login_password,
                            sudo_password=self.sm.patterns.sudo_password,
                            slot_id=slot_id,
                            app_hostname='firepower',
                            deploy_type=self.sm.patterns.deploy_type,
                            app_identifier=app_instance_name)
            new_sm = SspStateMachine(p)
            self.sm = new_sm
            self.spawn_id.sendline()
            self.go_to('any')
            self.go_to('fireos_state', timeout=600)
            logger.info('Password changed on FTD from slot {}'.format(slot_id))
            self.go_to('mio_state')

    def delete_app_instance(self, cmd_lines):
        """Deletes application instance

        :param cmd_lines: multi-line commands to delete the app instance.
          It should look like this:
                  top
                  scope ssa
                  delete logical-device asa1
                  commit-buffer
                  scope slot 1
                  delete app-instance asa
                  commit-buffer
        :return: None

        """

        r = re.search("scope slot (\d+)", cmd_lines)
        slot_id = r.group(1)
        r = re.search("delete app-instance (\w+)", cmd_lines)
        app_instance_name = r.group(1)

        # run cmd_lines to delete it.
        self.go_to('mio_state')
        self.execute_lines(cmd_lines)

        # check that it is deleted
        app_instance_list = self.get_app_instance_list()
        app_instance = [a for a in app_instance_list if
                        int(a.slot_id) == int(slot_id) and
                        a.application_name == app_instance_name]
        assert len(app_instance) == 0, "app_instance {} not deleted in slot " \
                                       "{}".format(app_instance_name, slot_id)

    def delete_logical_device_and_app_instance(self, slot_id):
        """Deletes logical device and app instance by slot_id for standalone mode

        :param slot_id: slot_id for SSP; QP: 1; BS: 1, 2, or 3
        :return: None

        """

        logical_devices = self.get_logical_device_list()
        if logical_devices is None or len(logical_devices) == 0:
            logger.info('No logical device found, nothing to delete')

        for a in logical_devices:
            if a.mode == "Clustered":
                self.delete_all_logical_devices()
                self.delete_all_app_instances()
                self.assign_all_interfaces_to_data_type()
                return
            if int(a.slot_id) == int(slot_id):
                cmd_lines = """
                      top
                      scope ssa
                      delete logical-device {}
                      commit-buffer
                """.format(a.name)
                logger.info('logical device {} is to be deleted ...'.format(a.name))

                self.go_to('mio_state')
                self.execute_lines(cmd_lines)

                logger.info('logical-device {} deleted'.format(a.name))
        self.get_logical_device_list()

        app_instance_list = self.get_app_instance_list()
        if app_instance_list is None or len(app_instance_list) == 0:
            logger.info('No app-instance found, nothing to delete')

        for a in app_instance_list:
            cmd_lines = """
                  top
                  scope ssa
                  scope slot {}
                  delete app-instance {} {}
                  commit-buffer
            """.format(a.slot_id, a.application_name, a.identifier)
            if int(a.slot_id) == int(slot_id):
                self.go_to('mio_state')
                self.execute_lines(cmd_lines)

                logger.info('Slot {}: app-instance {} {} deleted'.format(a.slot_id, a.application_name, a.identifier))
        self.get_app_instance_list()

    def delete_app_instance_by_slot(self, logical_device, slot_id, app_instance):
        """
        :param logical_device: logical device name, e.g. FTD-1
        :param slot_id: slot id, e.g. 1, 2, or 3
        :param app_instance: app instance name, e.g. ftd or asa
        :return: None

        """

        cmd_lines = """
            top
            scope ssa
            delete logical-device {}
            commit-buffer
        """.format(logical_device)

        cmd_lines2 = """
            scope slot {}
            delete app-instance {}
            commit-buffer
        """.format(slot_id, app_instance)

        # run cmd_lines to delete logical device
        logger.info('Delete logical device {}'.format(logical_device))
        try:
            self.go_to('mio_state')
            self.execute_lines(cmd_lines)
        except:
            # Handle Error: Managed object doesn't exist
            pass

        # run cmd_lines to delete app instance
        logger.info('Delete app instance {}'.format(slot_id))
        try:
            self.execute_lines(cmd_lines2)
        except:
            # Handle Error: Managed object doesn't exist
            pass

        # check that it is deleted
        app_instance_list = self.get_app_instance_list()
        app_instance = [a for a in app_instance_list if
                        int(a.slot_id) == int(slot_id) and
                        a.application_name == app_instance]
        assert len(app_instance) == 0, "app_instance {} not deleted in slot " \
                                       "{}".format(app_instance, slot_id)

    def assign_all_interfaces_to_data_type(self):
        """Assign port-type to data for all interfaces

        :return: None

        """

        cmd_lines = """
            top
            scope eth-uplink
            scope fabric a
            show interface detail
        """
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Port Name':
                hardware = a_value
                cmd_lines2 = """
                    scope interface {}
                    set port-type data
                    ex
                """.format(hardware)
                self.execute_lines(cmd_lines2, exception_on_bad_command=True)
        self.execute('commit-buffer')
        output = self.execute_lines(cmd_lines)

    def is_firmware_monitor_ready(self, version):
        """Check whether the bundle package is installed successfully.

        :param version: version string of the bundle package
                        e.g. 2.1(1.64)
        :return: True if fprm, fabric, chassis are in Ready status

        """

        firmware_monitor = self.parse_firmware_monitor()

        fprm = firmware_monitor.fprm
        if fprm.version != version or fprm.status != 'Ready':
            return False

        fabric = firmware_monitor.fabric
        if fabric.version != version or fabric.status != 'Ready':
            return False

        chassis = firmware_monitor.chassis
        # Handle chassis.version contains multiple versions properly
        # The first version should match argument version
        version_list = chassis.version.split(',')
        if version not in version_list or chassis.status != 'Ready':
            return False

        return True

    def wait_till_firmware_monitor_ready(self, version, timeout=1500):
        """Waits utnil the bundle package is installed successfully.

        :param version: version string of the bundle package
                        e.g. 2.1(1.64)
        :param timeout: timeout for wait_till()
        :return: None

        """

        # set terminal width bigger
        self.init_terminal()
        self.wait_till(self.is_firmware_monitor_ready, (version,),
                       wait_upto=timeout)

    def upgrade_bundle_package(self, bundle_package_name):
        """Upgrade bundle package.
        :param bundle_package_name: e.g. fxos-k9.2.1.1.64.SPA
        :return: None
        """
        version = self.get_bundle_package_version(bundle_package_name)
        if self.is_firmware_monitor_ready(version):
            # the bundle package has already been installed
            logger.info("fxos bundle package {} has been installed, " \
                        "nothing to do".format(bundle_package_name))
            return False

        cmd_lines = """
            top
            scope firmware
            scope auto-install
        """
        ########### Remove workaround (CSCvq65169) ######
        self.execute_lines(cmd_lines)
        ########## end of removal ################

        try:
            self.spawn_id.sendline("install platform platform-vers {}".format(version))

        except:
            logger.error("Invalid FXOS platform software package {}".format(version))
            return False

        # handle reboot question and check whether system will reboot; the below regex consumes all the output
        # that comes from the device after the above command is sent this may include the skip for reboot
        # message (INFO: There is no service impact to install this FXOS platform software 2.6(1.156)) or not
        # which is processed below
        will_system_reboot = True
        d2 = Dialog([
            ['.*Do you want to proceed', 'sendline(yes)', None, False, False],
        ])
        # check if the device said it will not reboot
        d2_result = d2.process(self.spawn_id, timeout=30)
        if 'no service impact to install this FXOS' in d2_result.match_output:
            will_system_reboot = False
        d1 = Dialog([
            [r'.*Do you want to.*', 'sendline(yes)', None, False, False],
        ])
        try:
            # Some fxos versions have an additional dialog
            d1.process(self.spawn_id, timeout=30)
        except:
            pass
        if will_system_reboot:
            logger.info('\nSystem will reboot ...')
        else:
            logger.info('\nSystem will not reboot ...')

        # If system will reboot, will wait for the following prompts
        if will_system_reboot:
            # Handle older fxos image with rebooting info printed to the console
            logger.info('==== Waiting for messages in rebooting ...')

            d1 = Dialog([
                ['{} login: '.format(self.sm.patterns.dev_hostname), 'sendline({})'.format(self.sm.patterns.login_username),
                 None, True, False],
                ['Password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
                ['.*Successful login attempts for user.*', None, None, True, False],
                ['Sending all processes the KILL signal', None, None, True, False],
                ['Please stand by while rebooting the system', None, None, True,
                 False],
                ['Use SPACE to begin boot immediately', 'send(" ")', None, True,
                 False],
                ['Manager image digital signature verification successful', None,
                 None, True, False],
                ['System is coming up', None, None, True, False],
                ['Finished bcm_attach...', None, None, True, False],
                ['vdc 1 has come online', None, None, False, False],
                [r'Connection to .* closed.', None, None, False, False],
            ])
            d1.process(self.spawn_id, timeout=3600)

            logger.info('==== Reconnect after reboot...')
            # Wait for reboot to finish and reconnect
            time.sleep(480)

        self.monitor_installation(version=version, timeout=2400)
        return True

    def monitor_installation(self, version, timeout=1500):
        """ Check if installation is finished and if the version is correct

        :param version: version string of the bundle package
                        e.g. 2.1(1.64)
        :param timeout: Timeout in case the installation takes too long
        :return: None

        """

        # Go to mio_state
        self.spawn_id.sendline()
        self.go_to('any')
        self.go_to('mio_state')

        # Wait for upgrade of fxos to finish
        logger.info('==== Check installation progress..')
        self.wait_till_firmware_monitor_ready(version, timeout=timeout)

    def is_slot_reinitialized(self, slot_id):
        show_slot_detail_cmd = """
            top
            scope ssa
            show slot {} detail
        """.format(slot_id)
        slot_status = self.execute_lines(show_slot_detail_cmd)
        return ('Oper State: Online' in slot_status and
                'Disk Format Status: 100%' in slot_status)

    def reinitialize_slot(self, slot_id, wait_upto=900):
        reinitialize_slot_cmd = """
            top
            scope ssa
            scope slot {}
            reinitialize
            commit-buffer
        """.format(slot_id)
        self.execute_lines(reinitialize_slot_cmd)
        time.sleep(10)
        self.wait_till(self.is_slot_reinitialized, slot_id, wait_upto)

    def check_all_logical_devices_configuration(self):
        """
        Method checks if one of the logical devices is configured improperly
        """
        logger.info('Checking logical device for reported configuration errors...')
        # wait for logical device to report any errors
        time.sleep(10)
        for ld in self.get_logical_device_list():
            if 'incomplete' in ld.operational_state.lower():
                raise RuntimeError('Incomplete configuration of logical device: {}. Error Msg: {}'.format(
                    ld.name, ld.error_msg))

    def set_default_auth_timeouts(self):
        """
            Set default value to disable logout from the chassis. Timeouts
            are set to zero for disable. The session must be exited and
            re-logged in for the changes to be applied.
        """
        commands = """
            top
            scope security
            scope default-auth
            set absolute-session-timeout 0
            set con-absolute-session-timeout 0
            set con-session-timeout 0
            commit-buffer
            show detail
            top
            exit
        """
        try:
            self.execute_lines(commands, timeout=30)
        except TimeoutError as e:
            pass
        self.sm.update_cur_state('prelogin_state')
        self.go_to('mio_state')

    def baseline_fxos_and_app_standalone_ftd(self,
                                             cmd_lines_setup_chassis_mgmt_network,
                                             fxos_url,
                                             csp_url,
                                             logical_device_name,
                                             slot_id,
                                             cmd_lines_assign_ftd_interfaces,
                                             cmd_lines_create_logical_device_app_instance,
                                             scp_password="",
                                             http_url="",
                                             wait_upto=1800,
                                             power_cycle_flag=False,
                                             reinitialize_slot=True,
                                             delete_ld_and_app_instances=True,
                                             **kwargs):
        """Baseline function for fxos and application installation.

        :param cmd_lines_setup_chassis_mgmt_network: command lines to
            setup out-of-band interface for the chassis
        :param fxos_url: fxos url
            e.g. scp://pxe@172.23.47.63:/tftpboot/fxos-k9.2.1.1.64.SPA
        :param csp_url: application csp url
            e.g. scp://pxe@172.23.47.63:/tftpboot/cisco-ftd.6.2.0.296.SPA.csp
        :param logical_device_name: logical device name
        :param slot_id: module slot id, e.g. 1, 2, or 3
        :param cmd_lines_assign_ftd_interfaces: command lines to
            assign roles to ftd interfaces
        :param cmd_lines_create_logical_device_app_instance: command lines to
            create logical device and app instance
        :param scp_password: scp password to download images
        :param http_url: In case this is given, it will download the fxos image from the url provided.
        :param wait_upto: wait time for app installation to be completed
        :param power_cycle_flag: if True power cycle the device before baseline
        :param reinitialize_slot: can be used to disable the slot reinitialization if set
        to False; by default it is set to true;
        :param delete_ld_and_app_instances: can be used to skip the deletion of the
        logical device and application instances if set to False. by default it is set to True
        :return: None

        """
        publish_kick_metric('device.ssp_fxos_and_app_standalone_ftd.baseline', 1)

        self.set_default_auth_timeouts()

        if delete_ld_and_app_instances:
            # Delete logical device and app instance for the slot
            logger.info('=== Delete logical device and app instance')
            self.delete_logical_device_and_app_instance(slot_id)

        if reinitialize_slot:
            self.reinitialize_slot(slot_id)

        if not fxos_url:
            logger.info('!!! Fxos was not provided this could lead to incompatibility between app instance '
                        'and existing fxos version !!!')
        # Validate the slot_id is valid
        slot_list = self.get_equipped_slot_list()
        # Empty slot, assert
        assert slot_id in slot_list, '==== Empty Slot with slot_id = {} !!!'.format(slot_id)
        # Power cycle the device if power_cycle_flag is True
        logger.info('=== Power cycle the device if power_cycle_flag is True')
        logger.info('=== power_cycle_flag={}'.format(str(power_cycle_flag)))
        if power_cycle_flag:
            self.power_cycle()

        # Setup out-of-band interface for chassis
        logger.info('=== Setup out-of-band interface for chassis')
        try:
            self.execute_lines(cmd_lines=cmd_lines_setup_chassis_mgmt_network)
        except:
            pass

        if fxos_url:
            # Download fxos bundle image
            logger.info('=== Download fxos bundle image')
            self.download_fxos(fxos_url=fxos_url, file_server_password=scp_password, http_url=http_url)

            # Upgrade bundle image
            logger.info('=== Upgrade bundle image')
            bundle_package = fxos_url.split('/')[-1].strip()
            if self.upgrade_bundle_package(bundle_package):
                logger.info("Package installation has been completed successfully!")
        else:
            logger.info("fxos package installation step was skipped as user did not provide fxos url!")

        self.set_default_auth_timeouts()

        # Download FTD image of .csp file
        logger.info('=== Download FTD image of .csp file')
        self.download_csp(csp_url=csp_url, file_server_password=scp_password)

        # Set mgmt, data and eventing interfaces
        logger.info('=== Set mgmt, data and eventing interfaces')
        self.execute_lines(cmd_lines=cmd_lines_assign_ftd_interfaces)

        # Set ip addresses for mgmt, data and eventing interfaces
        # Set domain, dns, firepower mode, device manager
        logger.info('=== Set ip addresses for mgmt, data and eventing interfaces')
        logger.info('=== Set domain, dns, firepower mode, device manager')
        logger.info('=== Also due to logical device creation app will be automatically created')
        self.execute_lines(cmd_lines=cmd_lines_create_logical_device_app_instance, timeout=60,
                           exception_on_bad_command=True)

        self.check_all_logical_devices_configuration()

        # wait for app to be created
        self.wait_for_app_creation(slot_id, app_instance_name='ftd', wait_upto=wait_upto)

    def baseline_fxos_and_app_cluster_ftd(self,
                                          cmd_lines_setup_chassis_mgmt_network,
                                          fxos_url,
                                          csp_url,
                                          cmd_lines_assign_ftd_interfaces,
                                          cmd_lines_create_logical_device,
                                          key,
                                          cmd_lines_set_ftd_mgmt_networks,
                                          cmd_lines_accept_license_agreement,
                                          app_instance_name,
                                          slot_list_str,
                                          scp_password="",
                                          http_url="",
                                          wait_upto=3600,
                                          power_cycle_flag=False, **kwargs):
        """Baseline function for fxos and application installation in Cluster
        Mode.

        :param cmd_lines_setup_chassis_mgmt_network: command lines to
            setup out-of-band interface for the chassis
        :param fxos_url: fxos url, you can also use your own container instead by adding the port like in the example
            e.g. scp://pxe@172.23.47.63:/tftpboot/fxos-k9.2.1.1.64.SPA
            e.g. scp://root@container_ip:container_port:/tmp/fxos-k9.2.1.1.64.SPA
        :param csp_url: application csp url
            e.g. scp://pxe@172.23.47.63:/tftpboot/cisco-ftd.6.2.0.296.SPA.csp
        :param cmd_lines_assign_ftd_interfaces: command lines to
            set mgmt, data, fp_eventing ports
        :param cmd_lines_create_logical_device: command lines to
            create logical device
        :param key: security key
        :param cmd_lines_set_ftd_mgmt_networks: command lines to
            set ftd mgmt network interfaces
        :param cmd_lines_accept_license_agreement: command lines to
            accept license agreement for ftd application
        :param app_instance_name: app instance name: ftd
        :param slot_list_str: slot list to be clustered: e.g. 1,2,3
        :param scp_password: scp password to download images
        :param http_url: In case this is given, it will download the fxos image from the url provided.
        :param wait_upto: wait time for app installation to be completed
        :param power_cycle_flag: if True power cycle the device before baseline
        :return: None

        """

        publish_kick_metric('device.ssp_fxos_and_app_cluster_ftd.baseline', 1)

        # Delete logical device
        logger.info('=== Delete logical device')
        self.delete_all_logical_devices()

        # Delete app instances
        logger.info('=== Delete app instances')
        self.delete_all_app_instances()

        if not fxos_url:
            logger.info('!!! Fxos was not provided this could lead to incompatibility between app instance '
                        'and existing fxos version !!!')
        # Power cycle the device if power_cycle_flag is True
        logger.info('=== Power cycle the device if power_cycle_flag is True')
        logger.info('=== power_cycle_flag={}'.format(str(power_cycle_flag)))
        if power_cycle_flag:
            self.power_cycle()

        # Setup out-of-band interface for chassis
        logger.info('=== Setup out-of-band interface for chassis')
        try:
            self.execute_lines(cmd_lines=cmd_lines_setup_chassis_mgmt_network)
        except:
            pass
        if fxos_url:
            # Download fxos bundle image
            logger.info('=== Download fxos bundle image')
            self.download_fxos(fxos_url=fxos_url, file_server_password=scp_password, http_url=http_url)

            # Upgrade bundle image
            logger.info('=== Upgrade bundle image')
            bundle_package = fxos_url.split('/')[-1].strip()
            self.upgrade_bundle_package(bundle_package)
        else:
            logger.info("fxos package installation step was skipped as user did not provide fxos url!")

        # Download FTD image of .csp file
        logger.info('=== Download FTD image of .csp file')
        self.download_csp(csp_url=csp_url, file_server_password=scp_password)

        # Set port type for interfaces
        self.assign_all_interfaces_to_data_type()
        self.execute_lines(cmd_lines_assign_ftd_interfaces)

        # Set default ftd image and accept license agreement
        logger.info('=== Set default ftd image and accept license agreement')
        self.execute_lines(cmd_lines_accept_license_agreement, timeout=30)

        # Create logical device
        logger.info('=== Create logical device')
        self.execute_lines(cmd_lines=cmd_lines_create_logical_device)
        time.sleep(1)
        self.spawn_id.sendline('set key')
        time.sleep(1)

        # Set security key
        logger.info('=== Set security key')
        d1 = Dialog([
            ['[K|k]ey:', 'sendline({})'.format(key), None, True, False],
            [self.sm.get_state('mio_state').pattern, None, None, False, False],
        ])
        d1.process(self.spawn_id, timeout=30)

        time.sleep(20)

        # Set mgmt ip, netmask, gateway for each slot
        logger.info('=== Set mgmt ip, netmask, gateway for each slot')
        self.execute_lines(cmd_lines_set_ftd_mgmt_networks, exception_on_bad_command=True)

        self.check_all_logical_devices_configuration()

        # Create logical device and app instances
        logger.info('=== Validate app intances are up running ...')
        self.create_app_instance_in_cluster(
            cmd_lines=cmd_lines_accept_license_agreement,
            app_instance_name=app_instance_name,
            slot_list_str=slot_list_str,
            wait_upto=wait_upto)

    def switch_to_module(self, slot_id, deploy_type='native',
                         app_identifier='', app_hostname='firepower'):
        """Method used to switch between the modules

        :param slot_id: the slot Id to connect to
        :param deploy_type: the deploy type of the app (container or native)
        :param app_identifier: the app identifier (in case of container deploy)
        :return:
        """

        self.go_to('mio_state')

        pattern = SspPatterns(self.sm.patterns.hostname,
                              self.sm.patterns.login_username,
                              self.sm.patterns.login_password,
                              self.sm.patterns.sudo_password,
                              slot_id, app_hostname, deploy_type,
                              app_identifier)

        new_sm = SspStateMachine(pattern)
        self.sm = new_sm
        self.spawn_id.sendline()
        self.go_to('any')
        self.go_to('fireos_state', timeout=240)

    def set_key(self, key):
        """
        Needed to add cluster password as below:

        FPR4120-6-Rack10-A# scope ssa
        FPR4120-6-Rack10-A /ssa # enter logical-device ftd-logic ftd 1 clustered
        FPR4120-6-Rack10-A /ssa/logical-device # enter cluster-bootstrap
        PR4120-6-Rack10-A /ssa/logical-device/cluster-bootstrap # set key
        Key:
        FPR4120-6-Rack10-A /ssa/logical-device/cluster-bootstrap* # commit-buffer

        :param key: the key

        :return: None
        """

        self.spawn_id.sendline('set key')

        d = Dialog([
            ['[K|k]ey:', 'sendline({})'.format(key), None, False, False]
        ])
        d.process(self.spawn_id)

    def set_value(self, value):
        """
        Needed to add cluster password as below:

        FPR4120-6-Rack10-A /ssa/logical-device* # enter mgmt-bootstrap ftd
        FPR4120-6-Rack10-A /ssa/logical-device/mgmt-bootstrap* # enter bootstrap-key-secret PASSWORD
        FPR4120-6-Rack10-A /ssa/logical-device/mgmt-bootstrap/bootstrap-key-secret* # set value
        Value:
        FPR4120-6-Rack10-A /ssa/logical-device/mgmt-bootstrap/bootstrap-key-secret* # exit

        :param value: the value
        :return: None
        """

        self.spawn_id.sendline('set value')

        d = Dialog([
            ['Value:', 'sendline({})'.format(value), None, False, False]
        ])
        d.process(self.spawn_id)

    def disconnect(self):
        """Disconnect the Device."""
        if self.spawn_id is not None:
            if self.type == 'ssh':
                self.go_to('mio_state')
        super().disconnect()

    def is_fxos_image_on_device(self, fxos_url):
        self.go_to('mio_state')
        image_name = os.path.basename(fxos_url)
        fxos_query = self.execute_lines('top\nscope firmware\nshow package')
        if image_name in fxos_query:
            return True
        return False

    def is_app_image_on_device(self, image_url):
        self.go_to('mio_state')
        image_name = os.path.basename(image_url)
        app_version = re.search(r'\d+\.\d+\.\d+\.\d+', image_name).group(0)
        apps = self.execute_lines('top\nscope ssa\nshow app')
        found = re.search(r'\s+.*?\s*%s\s+' % re.escape(app_version),
                          apps)
        if found:
            return True
        return False

    def baseline_by_branch_and_version(self, site, branch, version, cluster_flag, serverIp='', tftpPrefix='',
                                       scpPrefix='', docs='', fxosDir='', pxePassword='', **kwargs):
        """Baseline Ssp by branch and version using PXE servers.
        Look for needed files on devit-engfs and releng29, copy them to the local kick server
        and use them to baseline the device.

        :param site: e.g. 'ful', 'ast', 'bgl'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param cluster_flag: boolean: "True" or "False"
            'True' - installation is done in cluster mode
            'False' - installation is done in standalone mode
        :param *** kwargs:
        :param cmd_lines_setup_chassis_mgmt_network: command lines to
               setup out-of-band interface for the chassis
        :param cmd_lines_assign_ftd_interfaces: command lines to
               set mgmt, data, fp_eventing ports
        :param fxos_file: e.g. 'fxos-k9.2.2.2.17.SPA', the script will get it from releng29 page or
        :param fxos_url: in case this is given, it will download the fxos file from the provide url.
            if 'cluster_flag' is 'True', meaning the installation of applications is done in cluster mode, following
            mandatory parameters are required:
        :param cmd_lines_create_logical_device: command lines to
               create logical device
        :param key: security key
        :param cmd_lines_set_ftd_mgmt_networks: command lines to
               set ftd mgmt network interfaces
        :param cmd_lines_accept_license_agreement: command lines to
               accept license agreement for ftd application
        :param app_instance_name: app instance name: ftd
        :param slot_list_str: slot list to be clustered: e.g. 1,2,3

            if 'cluster_flag' is 'False', meaning the installation of applications is done in standalone mode, following
            mandatory parameters are required:
        :param logical_device_name: logical device name
        :param slot_id: module slot id, e.g. 1, 2, or 3
        :param cmd_lines_assign_ftd_interfaces: command lines to
            assign roles to ftd interfaces
        :param cmd_lines_create_logical_device_app_instance: command lines to
            create logical device and app instance

        Optional common parameters:

        :param wait_upto: wait time for app installation to be completed
        :param power_cycle_flag: if True power cycle the device before baseline
        :return:

        """

        server_password = None
        if not kwargs.get('fxos_file') and not kwargs.get('fxos_url'):
            raise RuntimeError("Please provide the fxos version you want to use via fxos_file OR fxos_url")

        fxos_url = kwargs.get('fxos_url', None)
        fxos_file = kwargs.get('fxos_file', None) or fxos_url.split('/')[-1]

        is_sw_on_device = self.is_fxos_image_on_device(fxos_file) and \
                          self.is_app_image_on_device(version.lower().replace('-', '.').strip())
        if not is_sw_on_device:
            if KICK_EXTERNAL:
                server_ip = serverIp
                tftp_prefix = tftpPrefix
                scp_prefix = scpPrefix
                files = docs
                scp_fxos_link = 'scp://pxe@{}:{}/{}'.format(server_ip, fxosDir, fxos_file)
                server_password = pxePassword
            else:
                server_ip, tftp_prefix, scp_prefix, files = \
                    prepare_installation_files(site, 'Ssp', branch, version,
                                               fxos_file=fxos_file,
                                               fxos_link=fxos_url)
                scp_fxos_link = 'scp://pxe@{}:{}/{}'.format(
                    server_ip, pxe_dir['fxos_dir'], fxos_file)
                server_password = pxe_password

            csp_file = [file for file in files if file.endswith('.csp')][0]
            scp_csp_link = "scp://pxe@{}:/{}/{}".format(server_ip,
                                                        scp_prefix, csp_file)
        else:
            logger.info('\n\n\nFXOS and APP images found already downloaded on '
                        'device.\n\n\n')
            scp_fxos_link = fxos_url
            scp_csp_link = version.lower().replace('-', '.').strip()

        kwargs['fxos_url'] = scp_fxos_link
        kwargs['csp_url'] = scp_csp_link
        kwargs['scp_password'] = server_password
        kwargs['http_url'] = ''

        if cluster_flag:
            self.baseline_fxos_and_app_cluster_ftd(**kwargs)
        else:
            self.baseline_fxos_and_app_standalone_ftd(**kwargs)
