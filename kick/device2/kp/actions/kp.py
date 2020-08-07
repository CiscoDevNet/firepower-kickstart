import collections
import datetime
import logging
import time
import re
import os.path
import subprocess


from unicon.core.errors import StateMachineError
from unicon.eal.dialogs import Dialog
from unicon.eal.expect import Spawn
from unicon.eal.utils import ExpectMatch
from unicon.utils import AttributeDict

try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric
from .constants import KpConstants
from .patterns import KpPatterns
from .statemachine import KpStateMachine, KpFtdStateMachine, KpAsaStateMachine
from ...general.actions.basic import BasicDevice, BasicLine, NewSpawn
from ...general.actions.power_bar import power_cycle_all_ports

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
    from kick.file_servers.file_servers import _normalize_site
except ImportError:
    KICK_EXTERNAL = True
    pass

logger = logging.getLogger(__name__)

KpInitCmds = '''
    top
    terminal length 0
    terminal width 511
'''
MAX_RETRY_COUNT = 3
DEFAULT_TIMEOUT = 60


class Kp(BasicDevice):

    def __init__(self, hostname, login_username='admin',
                 login_password='cisco123', sudo_password="cisco123",
                 power_bar_server='',
                 power_bar_port='',
                 power_bar_user='admn',
                 power_bar_pwd='admn',
                 config_hostname='firepower',
                 use_asa=False):
        """Constructor of Kp.

        :param hostname: host name in prompt
                e.g. 'BATIT-2100-2-AST'
        :param login_username: user name for login
        :param login_password: password for login
        :param sudo_password: root password for FTD
        :param power_bar_server: IP address of the PDU
        :param power_bar_port: port for device on the PDU
        :param power_bar_user: user for device on the PDU
        :param power_bar_pwd: pwd for device on the PDU
        :param config_hostname: initial hostname of a device BEFORE being set by baseline
                    e.g. Fresh device, no config: 'ciscoasa', 'firepower'
                    e.g. Previously used device, already configured: 'BATIT-2100-2-AST'
        :param use_asa: bool value to indicate using ASA statemachine while interacting with KP.
                        Should be set to 'True' if baselining to/from ASA.

        :return: None
        """

        super().__init__()
        publish_kick_metric('device.kp.init', 1)
        self.set_default_timeout(DEFAULT_TIMEOUT)

        # set hostname, login_username and login_password
        # config_hostname = kwargs.get('config_hostname', 'firepower')
        if use_asa and config_hostname == 'firepower':
            config_hostname = 'ciscoasa'
        self.patterns = KpPatterns(hostname, login_username, login_password, sudo_password, config_hostname)

        # create the state machine that contains the proper attributes.
        if use_asa:
            self.sm = KpAsaStateMachine(self.patterns)
        else:
            self.sm = KpFtdStateMachine(self.patterns)

        KpConstants.power_bar_server = power_bar_server
        KpConstants.power_bar_port = power_bar_port
        KpConstants.power_bar_user = power_bar_user
        KpConstants.power_bar_pwd = power_bar_pwd

        # important: set self.line_class so that a proper line can be created
        # by ssh_console(), etc.
        self.line_class = KpLine
        logger.info("Done: Kp instance created")

    def poll_ssh_connection(self, ip, port, username='admin', password='Admin123', retry=60):
        """Poll SSH connection until it's accessable. You may need to use this after a
        system reboot.

        :param ip: platform management IP
        :param port: ssh port
        :param username: usually "admin"
        :param password: usually "Admin123"
        :param retry: total times of ssh connection retry
        :return a line object (where users can call execute(), for example)

        """

        # wait until SSH back up
        ctx = AttributeDict({'password': password})
        patterns = '{}|{}'.format(
            self.sm.get_state('fireos_state').pattern,
            self.sm.get_state('fxos_state').pattern)
        d = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['[pP]assword:', 'sendline_ctx(password)', None, True, False],
            [patterns, None, None, False, False],
        ])

        for i in range(0, retry):
            try:
                spawn_id = Spawn(
                    'ssh -o UserKnownHostsFile=/dev/null '
                    '-o StrictHostKeyChecking=no -l {usr} -p {port} {ip} \n' \
                        .format(usr=username, port=port, ip=ip))
                d.process(spawn_id, context=ctx)
            except:
                spawn_id.close()
                pass
            else:
                break
            time.sleep(10)
        else:
            raise RuntimeError('SSH connection not coming up after %r retries' % retry)

        # wait until app instance comes online
        ssh_line = self.line_class(spawn_id, self.sm, 'ssh', chassis_line=True)
        for i in range(0, 60):
            try:
                ssh_line.execute_lines('top\nscope ssa', exception_on_bad_command=True)
            except:
                pass
            else:
                break
            time.sleep(10)
        else:
            raise RuntimeError('FXOS not ready after 10 min')

        for i in range(0, 60):
            online = True
            apps = ssh_line.get_app_instance_list()
            for app in apps:
                if app.operational_state is None:
                    raise RuntimeError('Cannot get app instance operational state')
                elif app.operational_state == 'Online':
                    logger.info('App {} comes online'.format(app.application_name))
                else:
                    online = False
            if online:
                break
            time.sleep(20)
        else:
            raise RuntimeError('Application instance not coming up after 20 min')
        return ssh_line

    # TODO
    # check with owners
    def log_checks(self, kp_line, list_files=['/var/log/boot_*'],
                   search_strings=['fatal', 'error'], exclude_strings=[]):
        """Wrapper function to get logs from from an ftd in Kilburn Park
        device.

        :param kp_line: Instance of device line used to connect to FTD
               e.g. kp_line = dev.console_tenet('172.28.41.142','2007')
        :param list_files: List of file paths for files to search in
        :param search_strings: List of keywords to be searched in the logs
        :param exclude_strings: List of keywords to be excluded in the logs
               e.g list_files = ['/var/log/boot_1341232','/var/log/boot_*']
               search_strings = ['fatal','error', 'crash']
               exclude_strings = ['ssl_flow_errors', 'firstboot.S09']

        """

        log_output = self.get_logs(kp_line=kp_line,
                                   list_files=list_files,
                                   search_strings=search_strings,
                                   exclude_strings=exclude_strings)

        logger.info("""
                    ***********************************************************

                    Logs for the requested files in the FTD are : -
                    {}

                    ***********************************************************
                    """.format(log_output))

    # TODO
    # check with owners
    def get_logs(self, kp_line, list_files=['/var/log/boot_*'],
                 search_strings=['fatal', 'error'], exclude_strings=[]):
        """Switch to root on the connected FTD and then return a list of unique
        errors from a given list of files. Switch back to scope.

        :param kp_line: Instance of device line used to connect to FTD
               e.g. kp_line = dev.console_tenet('172.28.41.142','2007')
        :param list_files: List of file paths for files to search in
        :param search_strings: List of keywords to be searched in the logs
        :param exclude_strings: List of keywords to be excluded in the logs
               e.g list_files = ['/var/log/boot_1341232','/var/log/boot_*']
               search_strings = ['fatal','error', 'crash']
               exclude_strings = ['ssl_flow_errors', 'firstboot.S09']
        :return: list of errors from given list of files

        """

        self.sm.go_to('sudo_state', kp_line.spawn_id, timeout=30)

        grep_command_list = []
        exclude_line = ''

        if exclude_strings:
            exclude_cmd = ['| grep -v {}'.format(string) for string in exclude_strings]
            exclude_line = ''.join(exclude_cmd)

        if list_files and search_strings:
            for file in list_files:
                for string in search_strings:
                    grep_command = "grep -Ii {} {} | sort -u {}".format(string,
                                                                        file, exclude_line)
                    grep_command_list.append(grep_command)

        output_log = kp_line.execute_lines_total("\n".join(grep_command_list))

        if kp_line.chassis_line:
            self.go_to('fxos_state')
        else:
            self.go_to('fireos_state')

        return output_log

    def ssh_vty(self, ip, port, username='admin', password='Admin123',
                timeout=None, line_type='ssh', rsa_key=None):
        """Set up a ssh connection to FTD.

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
            ['[.*>#$] ', 'sendline()', None, False, False],
        ])

        d.process(spawn_id, context=ctx, timeout=timeout)
        logger.debug('ssh_vty() finished successfully')

        ssh_line = self.line_class(spawn_id, self.sm, line_type, chassis_line=False, timeout=timeout)

        return ssh_line


class KpLine(BasicLine):

    def __init__(self, spawn_id, sm, type, chassis_line=True, timeout=None):
        """Constructor of KpLine.

        :param spawn_id: spawn connection instance
        :param sm: state machine instance
        :param type: type of connection, e.g. 'telnet', 'ssh'
        :param chassis_line: True if ssh/telnet console connection is used, False if ssh to FTD
                             if console connection is used, the device could remain
                             in an unknown state in order to be able to recover it
        """

        self.chassis_line = chassis_line
        self.line_type = 'KpLine'
        self.change_password_flag = False
        self.power_cycle_flag = False

        try:
            super().__init__(spawn_id, sm, type, timeout=timeout)
            self.spawn_id.sendline()
            self.go_to('any')
            self._set_to_proper_state()
        except:
            if not chassis_line:
                raise RuntimeError("Unknown device state")
            logger.info("Try to drop device to rommon state.")
            try:
                self.wait_for_rommon(timeout=300)
                logger.info("Device is in 'rommon' state.")
            except:
                # keep the KpLine 'alive' in case the power cycle function is used
                # in order to start a baseline
                logger.info("Failed to go to rommon. Unknown device state.")
                return

        if self.chassis_line and self.sm.current_state is not 'rommon_state':
            self.init_terminal(determine_state=False)

        # Set default power bar info
        self.power_bar_server = KpConstants.power_bar_server
        self.power_bar_port = KpConstants.power_bar_port
        self.power_bar_user = KpConstants.power_bar_user
        self.power_bar_pwd = KpConstants.power_bar_pwd

        # self.go_to('any')

    def init_terminal(self, determine_state=True):
        """Initialize terminal size."""

        if self.sm.current_state in ['disable_state', 'enable_state', 'config_state']:
            # Not allowed to go to fxos_state
            return

        ##### There were defects CSCvq86739, CSCvq96757 and CSCvq93377 where device prompt and command were lagging
        #### This sleep provide to wait for prompt to come
        time.sleep(5)
        self.spawn_id.sendline()
        try:
            if determine_state:
                self.go_to('any')
            self.go_to('fxos_state')
        except StateMachineError as exc:
            logger.error('Cannot initialize FXOS terminal: {}'.format(str(exc)), exc_info=True)
            return

        for cmd in KpInitCmds.split('\n'):
            cmd = cmd.strip()
            if cmd == "":
                continue
            self.execute_only(cmd)

    def disconnect(self):
        """Disconnect the Device."""
        if self.spawn_id is not None:
            if self.chassis_line and self.sm.current_state != 'rommon_state':
                self.go_to('fxos_state')
        super().disconnect()

    def expect_and_sendline(self, this_spawn, es_list, timeout=10):
        """takes a list of expect/send actions and perform them one by one.

        es_list looks like:
        [['exp_pattern1', 'send_string1', 30],
         ['exp_pattern2', 'send_string2'],
         ...
        ]
        The third element is for timeout value, and can be ommitted when the
        overall timeout value applies.

        :param this_spawn: the spawn associated with the device line
        :param es_list: expected string and send string
        :param timeout: defaulted to 10 seconds
        :return: None

        """

        for es in es_list:
            if len(es) == 2:
                exp_pattern = es[0]
                send_string = es[1]
                to = timeout
            elif len(es) == 3:
                exp_pattern = es[0]
                send_string = es[1]
                to = int(es[2])
            else:
                raise RuntimeError("Unknown expect_and sendline input")
            #####Any first command is sending with trimming some character, issue with unicon. Added fix for (CSCvs29201)####
            time.sleep(5)
            this_spawn.sendline()
            this_spawn.sendline(send_string)
            this_spawn.expect(exp_pattern, timeout=to)

    def wait_until_device_on(self, timeout=600):
        """Wait until the device is on

        :param timeout: time to wait for the device to boot up
        :return: None

        """

        # The system will reboot, wait for the following prompts
        d = Dialog([
            ['vdc 1 has come online', None, None, False, False],
            ['SW-DRBG health test passed', None, None, False, False],
        ])
        d.process(self.spawn_id, timeout=timeout)

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
            logger.error('Invalid power bar server/port')
            return None

        # If new server and port are provided, replace the existing power bar
        if power_bar_server or power_bar_port:
            self.set_power_bar(power_bar_server, power_bar_port, power_bar_user, power_bar_pwd)

        result = power_cycle_all_ports(self.power_bar_server, self.power_bar_port, self.power_bar_user,
                                       self.power_bar_pwd)

        if wait_until_device_is_on:
            self.wait_until_device_on(timeout=timeout)

        return result

    def get_app_instance_list(self):
        """
        Get the list of app instances

        Application Name: ftd
        Slot ID: 1
        Admin State: Enabled
        Operational State: Online
        Running Version: 6.2.1.341
        Startup Version: 6.2.1.341
        Cluster Oper State: Not Applicable
        Current Job Type: Start
        Current Job Progress: 100
        Current Job State: Succeeded
        Clear Log Data: Available
        Error Msg:
        Hotfixes:
        Externally Upgraded: No

        :return: a list of named tuple that restores the app instance info

        """
        cmd_lines = '''
            top
            scope ssa
            show app-instance detail
        '''
        self.go_to('fxos_state')
        output = self.execute_lines(cmd_lines)

        AppInstance = collections.namedtuple('AppInstance',
                                             ['application_name', 'slot_id', 'admin_state', 'operational_state',
                                              'running_version', 'startup_version', 'cluster_oper_state',
                                              'cluster_role', 'job_type', 'job_progress', 'job_state',
                                              'clear_log_data', 'error_msg', 'hotfixes', 'externally_upgraded'])
        app_instance_list = []

        blocks = [i.start() for i in re.finditer('Application Name:', output)]
        if blocks:
            blocks.append(len(output))
            for i in range(0, len(blocks) - 1):
                name = slot = admin_state = oper_state = \
                    running_version = startup_version = cluster_oper_state = job_type = \
                    job_progress = job_state = clear_log_data = error_msg = hotfixes = \
                    externally_upgraded = cluster_role = None

                for line in output[blocks[i]: blocks[i + 1]].splitlines():
                    line = line.strip()
                    match = re.search('(.*):(.*)', line)
                    if match:
                        key = match.group(1).strip()
                        value = match.group(2).strip()
                        if key == 'Application Name':
                            name = value
                        elif key == 'Slot ID':
                            slot = int(value)
                        elif key == 'Admin State':
                            admin_state = value
                        elif key == 'Operational State':
                            oper_state = value
                        elif key == 'Running Version':
                            running_version = value
                        elif key == 'Startup Version':
                            startup_version = value
                        elif key == 'Cluster Oper State':
                            cluster_oper_state = value
                        elif key == 'Cluster Role':
                            cluster_role = value
                        elif key == 'Current Job Type':
                            job_type = value
                        elif key == 'Current Job Progress':
                            job_progress = value
                        elif key == 'Current Job State':
                            job_state = value
                        elif key == 'Clear Log Data':
                            clear_log_data = value
                        elif key == 'Error Msg':
                            error_msg = value
                        elif key == 'Hotfixes':
                            hotfixes = value
                        elif key == 'Externally Upgraded':
                            externally_upgraded = value
                app_instance = AppInstance(application_name=name, slot_id=slot,
                                           admin_state=admin_state, operational_state=oper_state,
                                           running_version=running_version, startup_version=startup_version,
                                           cluster_oper_state=cluster_oper_state, cluster_role=cluster_role,
                                           job_type=job_type, job_progress=job_progress, job_state=job_state,
                                           clear_log_data=clear_log_data, error_msg=error_msg, hotfixes=hotfixes,
                                           externally_upgraded=externally_upgraded)
                app_instance_list.append(app_instance)

        return app_instance_list

    def get_packages(self):
        """Get packages currently downloaded to the box."""

        self.go_to('fxos_state')
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

    def _get_download_status(self, image_name, timeout=120):
        """Gets the status of download

        :param image_name: the name of the image. it should look like:
               fxos-k9.2.0.1.68.SPA
        :return: status as 'Downloaded' or 'Downloading'

        """
        self.go_to('fxos_state')
        output = self.execute('show download-task {} detail | grep State'
                              ''.format(image_name), timeout=timeout)

        r = re.search('State: (\w+)', output)

        status = r.group(1)
        logger.info("download status: {}".format(status))
        return status

    def _wait_till_download_complete(self, file_url, wait_upto=1800):
        """Waits until download completes

        :param file_url: should look like one of the following:
               tftp://172.23.47.63/cisco-ftd.6.2.0.296.SPA.csp
        :param wait_upto: how long to wait for download to complete in seconds
        :return: None

        """

        self.go_to('fxos_state')
        if file_url.startswith("scp"):
            r = re.search('(\w+)://(\w+)@[0-9\.]+:([\w\-\./]+)', file_url)
            assert r, "unknown file_url: {}".format(file_url)
            full_path = r.group(3)

        elif file_url.startswith("tftp"):
            r = re.search('(\w+)://[0-9\.]+/([\w\-\./]+)', file_url)
            assert r, "unknown file_url: {}".format(file_url)
            full_path = r.group(2)
        else:
            raise RuntimeError("Incorrect file url download protocol")

        image_name = os.path.basename(full_path)
        start_time = datetime.datetime.now()
        elapsed_time = 0
        while elapsed_time < wait_upto:
            logger.info("sleep 10 seconds for download to complete")
            time.sleep(10)
            download_status = self._get_download_status(image_name)
            if download_status == 'Downloaded':
                logger.info("download completed for {}".format(image_name))
                return download_status
            elif download_status == "Downloading":
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
            elif download_status == "Failed":
                return download_status
        raise RuntimeError("download took too long: {}".format(image_name))

    def wait_till(self, stop_func, stop_func_args, wait_upto=300,
                  sleep_step=10):
        """Wait till stop_func returns True.

        :param wait_upto: in seconds
        :param stop_func: when stop_func(stop_func_args) returns True,
               break out.
        :param stop_func_args: see above.
        :param sleep_step: sleeps this long (in seconds between each call to
               stop_func(stop_func_args).
        :return:

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
                logger.debug("sleep {} seconds and test again".format(sleep_step))
                time.sleep(sleep_step)
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
        raise RuntimeError("{}({}) took too long to return True"
                           "".format(stop_func, stop_func_args))

    def download_ftd_fp2k(self, fxos_url, ftd_version, file_server_password=""):
        """Download ftd package.

        :param fxos_url: url of combined ftd package
            e.g. scp://pxe@172.23.47.63:/tftpboot/cisco-ftd-fp2k.6.2.1-1088.SSA
        :param file_server_password: sftp server password, e.g. pxe
        :param ftd_version: ftd version, e.g. 6.2.1-1088

        """
        bundle_package_name = fxos_url.split("/")[-1].strip()
        self.go_to('fxos_state')

        if self.is_firmware_fp2k_ready(ftd_version):
            # the bundle package has already been installed
            logger.info("fxos fp2k bundle package {} has been installed, "
                        "nothing to do".format(bundle_package_name))
            return

        self.execute_lines('top\nscope firmware')
        packages = self.get_packages()
        if bundle_package_name in [package.name for package in packages]:
            logger.info('Target package %s already downloaded' % bundle_package_name)
            return

        retry_count = MAX_RETRY_COUNT
        while retry_count > 0:
            self.execute_lines('''
                top
                scope firmware
                ''')
            self.spawn_id.sendline('download image {}'.format(fxos_url))
            time.sleep(5)

            d = Dialog([
                ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
                ['Password:', 'sendline({})'.format(file_server_password),
                 None, True, False],
                [self.sm.get_state('fxos_state').pattern, None, None, False, False],
            ])
            d.process(self.spawn_id)

            status = self._wait_till_download_complete(fxos_url)

            if status == "Failed":
                retry_count -= 1
                if retry_count == 0:
                    raise RuntimeError(
                        "Download failed after {} tries. Please check details "
                        "again: {}".format(MAX_RETRY_COUNT, fxos_url))
                logger.info("Download failed. Trying to download {} "
                            "more times".format(retry_count))
            elif status == "Downloaded":
                return
            logger.info('Download failed, the script will wait 5 minutes before retrying download again')
            for i in range(30):
                self.spawn_id.sendline('\x03')
                time.sleep(10)

    def is_firmware_fp2k_ready(self, version):
        """Check fp2k package firepower /system # show firmware package-version
        FPRM: Package-Vers: 6.2.1-1052.

        :param version: FTD version, for example 6.2.1-1088

        """

        self.go_to('fxos_state')
        cmd_lines = """
            top
            scope system
            show firmware package-version | grep Package-Vers
        """

        # get string 'Package-Vers: 6.2.1-1052', for example
        output = self.execute_lines(cmd_lines)
        list_ = output.split(':')

        # get string '6.2.1-1052', for example
        fprm_ver = list_[1].strip()

        if fprm_ver != version:
            return False

        return True

    def format_goto_rommon(self, timeout=300):
        """Format disk and go to ROMMON mode.

        :param timeout: time to wait for boot message
        :return: None

        """

        self.go_to('fxos_state')
        self.go_to('local_mgmt_state')
        self.spawn_id.sendline('format everything')
        # The system will reboot, wait for the following prompts
        d = Dialog([
            ['Do you still want to format', 'sendline(yes)', None, False, False],
        ])
        d.process(self.spawn_id, timeout=30)
        self.wait_for_rommon(timeout=timeout)

    def power_cycle_goto_rommon(self, timeout=300, power_bar_server=None, power_bar_port=None,
                                power_bar_user='admn', power_bar_pwd='admn'):
        """Power cycle chassis and go to ROMMON mode.

        :param timeout: time to wait for boot message
        :param power_bar_server: comma-separated string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string of power ports on the PDU's
        :param power_bar_user: comma-separated string of usernames for the PDU's
        :param power_bar_pwd: comma-separated string of passwords for the PDU's
        :return: None
        """
        if self.sm.current_state == 'rommon_state':
            # Already in rommon mode
            return

        # Power cycle KP, but don't wait for startup
        self.power_cycle(power_bar_server=power_bar_server, power_bar_port=power_bar_port,
                         wait_until_device_is_on=False, power_bar_user=power_bar_user, power_bar_pwd=power_bar_pwd)
        # drop device to rommon
        self.wait_for_rommon(timeout=timeout)

    def wait_for_rommon(self, timeout):
        # The system will reboot, wait for the following prompts
        d = Dialog([['Boot in 10 seconds.', 'sendline({})'.format(chr(27)), None, False, False],
                    [self.sm.get_state('rommon_state').pattern, None, None, False, False],
                    ])
        d.process(self.spawn_id, timeout=timeout)
        self.sm.update_cur_state('rommon_state')

    def rommon_factory_reset_and_format(self, boot_timeout=300, format_timeout=300):
        """From rommon, execute a factory reset and format everything after booting up.
        Useful when login information is unknown.

        :param boot_timeout: int seconds to wait for login after factory reset
        :param format_timeout: int seconds to wait for rommon after format everything
        :return: None
        """

        self.change_password_flag = False
        if self.sm.current_state != 'rommon_state':
            self.go_to('any')
            self.power_cycle_goto_rommon(timeout=format_timeout)

        logger.info('=== Issuing factory-reset from rommon')
        self.spawn_id.sendline('set')

        d1 = Dialog([
            ['rommon.*> ', 'sendline(factory-reset)', None, True, False],
            [' yes/no .*:', 'sendline(yes)', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=30)

        if self.line_type is 'WmLine':
            d11 = Dialog([
                ['Please type \'ERASE\' to confirm the operation', 'sendline(ERASE)', None, True, False],
                [' yes/no .*:', 'sendline(yes)', None, False, False],
                ['rommon.*> ', None, None, False, False],
            ])
            d11.process(self.spawn_id, timeout=30)

        self.spawn_id.sendline('boot')
        d2 = Dialog([
            ['[a-zA-Z0-9_-]+.*login: ', 'sendline(admin)', None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.default_password), None, False, False],
            ['boot: cannot determine first file name on device', None, None, False, False]
        ])

        res = d2.process(self.spawn_id, timeout=boot_timeout)
        if 'boot: cannot determine first file name on device' not in res.match_output:
            self.__change_password()
            self.init_terminal()
        else:
            logger.info("Boot disk not found. Still in rommon mode")
            return

        logger.info('=== Issuing format everything')
        self.format_goto_rommon(timeout=format_timeout)

    def rommon_configure(self, tftp_server, rommon_file,
                         uut_ip, uut_netmask, uut_gateway):
        """In ROMMON mode, set network configurations.

        :param tftp_server: tftp server ip that uut can reach
        :param rommon_file: build file with path,
               e.g. '/netboot/ims/Development/6.2.1-1159/installers/'
                    'fxos-k8-fp2k-lfbff.82.2.1.386i.SSA'
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :return: None

        """
        logger.info('add rommon config')
        es_list = [
            ['rommon', 'set'],
            ['rommon', 'address {}'.format(uut_ip)],
            ['rommon', 'netmask {}'.format(uut_netmask)],
            ['rommon', 'gateway {}'.format(uut_gateway)],
            ['rommon', 'server {}'.format(tftp_server)],
            ['rommon', 'image {}'.format(rommon_file)],
            ['rommon', 'sync'],
        ]
        self.expect_and_sendline(self.spawn_id, es_list, timeout=20)

        try:
            self.check_settings_in_rommon(tftp_server, rommon_file, uut_ip, uut_netmask, uut_gateway)
        except RuntimeError:
            logger.info(">>>>>> In ROMMON: set network configuration again")
            self.expect_and_sendline(self.spawn_id, es_list, timeout=20)

        for i in range(20):
            self.spawn_id.sendline('ping {}'.format(tftp_server))
            try:
                self.spawn_id.expect('Success rate is 100 percent', timeout=5)
            except TimeoutError:
                time.sleep(60)
                continue
            else:
                break
        else:
            raise RuntimeError(">>>>>> Ping to {} server not working".format(tftp_server))

    def rommon_tftp_download(self, tftp_server, rommon_file, username,
                             timeout=1200):
        """Send tftpdnld command in rommon mode If the prompt returns back to
        rommon will retry to download until timeout.

        :param tftp_server: tftp server ip that uut can reach
        :param rommon_file: build file with path,
               e.g. '/netboot/ims/Development/6.2.1-1159/installers/'
                    'fxos-k8-fp2k-lfbff.82.2.1.386i.SSA'
        :param username: User Name to login to uut
        :param timeout: timeout to detect errors for downloading
        :return: None

        """

        # self.go_to('rommon_state')
        # Start tftp downloading
        logger.info('=== Wait for installation to complete, timeout = {}'
                    ' seconds ...'.format(str(timeout)))
 
        d = Dialog([            
            ['[a-zA-Z0-9_-]+[^\bLast \b] login: ', 'sendline({})'.format(username), None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.default_password), None, False, False],
        ])

        if 'lfbff' in rommon_file:
            d.append(['rommon.*> ', 'sendline(tftpdnld)', None, True, False])
        else:
            d.append(['rommon.*> ', 'sendline(tftpdnld -b)', None, True, False])

        try:
            d.process(self.spawn_id, timeout=timeout)
            # self.spawn_id.sendline()
            logger.info("=== Rommon file was installed successfully.")
        except:
            logger.info("=== Rommon file download failed, raise runtime error. ")
            raise RuntimeError(
                "Download failed. Please check details - "
                "tftp_server: {}, image file: {}".format(tftp_server, rommon_file))

        # handle change fxos password dialog
        self.change_password_flag = False
        self.__change_password()

    def __change_password(self):

        # handle change password enforcement at first login
        change_password_dialog = Dialog([
            ['You (are required to|must) change your password', None, None, True, False],
            ['System is coming up', lambda: time.sleep(60), None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
            ['[ -~]+(?<!Last)(?<!failed) login: ', 'sendline({})'.format(self.sm.patterns.login_username), None, True,
             False],
            ['Enter old password:', 'sendline({})'.format(self.sm.patterns.default_password), None, True, False],
            ['Enter new password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
            ['Confirm new password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
            ['Your password (was|has been) updated successfully', None, None, False, False],
            ['Login timed out', None, None, False, False],
            [self.sm.patterns.prompt.fxos_prompt, None, None, False, False]
        ])

        output = change_password_dialog.process(self.spawn_id, timeout=900)
        if 'updated successfully' in output.match_output:
            self.change_password_flag = True
            logger.info('Password has been changed successfully')
        elif 'Login timed out' in output.match_output:
            logger.error('Logging in to FXOS failed with {} password. Exiting...\n Please make sure you have provided '
                         'the correct device credentials before starting the baseline'.
                         format(self.sm.patterns.login_password))
            raise RuntimeError('Incorrect Login password.')
        elif 'Password:' in output.match_output:
            logger.info('Successfully logged in with {} password'.format(self.sm.patterns.login_password))
        else:
            logger.info('Changing password was not required...')

        if self.power_cycle_flag:
            logger.info('Device was rebooted from a remote power unit. \n Waiting for '
                        'initialization to complete before reinstalling the application')
            wait_for_ftd_init = Dialog([
                ['Cisco FTD initializing', None, None, True, False],
                ['Verifying the signature of the Application image', 'sendline()', None, False, False],
                ['Failed logins since the last login:', None, None, False, False],
                ['INFO: SW-DRBG health test passed.', None, None, True, False],
                ['Cisco FTD installation finished successfully', None, None, True, False],
                ['[a-zA-Z0-9_-]+[^<]*[^>][>#][^>]', 'sendline()', None, False, False]
            ])
            wait_for_ftd_init.process(self.spawn_id, timeout=600)

    def configure_manager(self, manager, manager_key, manager_nat_id):
        """Configure manager to be used for registration
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id

        :return: None

        """
        if manager_nat_id is None:
            response = self.execute('configure manager add {} {}'.format(manager, manager_key), 120)
        else:
            response = self.execute('configure manager add {} {} {}'.format(manager, manager_key, manager_nat_id), 120)
        success = re.search('Manager successfully configured', response)
        if success is None:
            logger.error('Exception: failed to configure the manager')
            raise RuntimeError('>>>>>> configure manager failed:\n{}\n'.format(response))

    def _in_enable_not_fxos_state(self,timeout=None):
        """
        Tell whether device is in "enable_state" or "fxos_state".

        There may be a confusion in these two states (the prompts look similar). Run "show version" and
        read the output. If "Boot Loader version:" is seen, it is fxos_state. If "Cisco Adaptive Security
         Appliance Software Version" is seen, it is in enable_state.
        :return: True - in enable_state, or False - in fxos_state
        """
        ##### There were defects CSCvq86739, CSCvq96757 and CSCvq93377 where device prompt and command were lagging
        #### This sleep provide to wait for prompt to come
        time.sleep(2)
        valid_messages = ["Boot Loader version:", "Startup-Vers:", "Package-Vers:", "Platform-Vers:"]
        r = self.execute("show version | include [Vv]ers", timeout=10)
        if "Cisco Adaptive Security Appliance Software Version" in r:
            logger.debug("device in enable_state, not fxos_state")
            return True
        elif any(message in r for message in valid_messages):
            # for KP and WM, in fxos_state, old version will include a line "Boot Loader version:".
            # new version will include a line "Startup-Vers:".
            logger.debug("device in fxos_state, not enable_state")
            return False
        else:
            raise RuntimeError("Can't tell either enable_state or fxos_state")

    def _set_to_proper_state(self):
        """
        Set to the proper state.

        If in enable_state or fxos_state, check which state we are in, by _in_enable_not_fxos_state().
        Then set the state properly. If in other states, do thing.
        :return: None
        """

        if self.sm.current_state in ['enable_state', 'fxos_state']:
            logger.debug("trying to see if truly in enable_state or fxos_state")
            if self._in_enable_not_fxos_state():
                logger.debug("setting current_state to enable_state")
                self.sm.update_cur_state('enable_state')
            else:
                logger.debug("setting current_state to fxos_state")
                self.sm.update_cur_state('fxos_state')
        else:
            logger.debug("no change on current_state")

    def go_to(self, state, **kwargs):
        """
        In case we land in "fxos_state" or "enable_state", double check that we are in
        the correct state as we think. Then do go_to()
        :param state:
        :param kwargs:
        :return:
        """
        self._set_to_proper_state()
        super().go_to(state, **kwargs)

    def check_settings_in_rommon(self, tftp_server, rommon_file, uut_ip, uut_netmask, uut_gateway):

        expected_settings = ['ADDRESS={}'.format(uut_ip), 'NETMASK={}'.format(uut_netmask),
                             'GATEWAY={}'.format(uut_gateway), 'SERVER={}'.format(tftp_server),
                             'IMAGE={}'.format(rommon_file)]

        current_settings = self.execute_only('set', 30)
        if all([expected in [el.strip() for el in current_settings.split('\n\r')] for expected in expected_settings]):
            logger.info('Environment variables were configured as expected')
        else:
            logger.error('Environment variables are NOT configured as expected')
            raise RuntimeError('>>>>>> Environment variables are NOT configured as expected: \n {}'.
                               format(current_settings))

    ### baseline asa without an fxos image
    def baseline_asa_by_branch_and_version(
            self, 
            site, 
            branch, 
            version,
            uut_hostname,
            uut_password, 
            uut_ip,
            uut_netmask, 
            uut_gateway,
            dns_servers, 
            search_domains):
        """Baseline Kp with ASA image by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the pxe-site
        and use them to baseline the device.

        :param site: PXE site to download image from e.g. 'ful', 'ast', 'bgl'
        :param branch: Branch name, e.g. 'tahoe'
        :param version: Software build-version, e,g, 99.16.1.100
        :param uut_hostname: Device Host Name in the prompt
        :param uut_username: User Name to login to uut
        :param uut_password: Password to login to uut
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway

        :param dns_servers: DNS Servers
        :param search_domains: Search Domains      

        :return None
        """
        logger.info('Preparing ASA image for tftp - pxe-site: {} branch: {} version: {}'.format(site,branch,version))
        asa_filename = self.find_asa_bundle_image(branch, version)
        server_name, tftp_prefix, scp_prefix = prepare_asa_file(
            site=site, asa_branch=branch, asa_version=version,
            file=asa_filename)
        pxe_ip = pxeserver_ip[server_name]
        asa_file_tftp_url = os.path.join('tftp://{}'.format(pxe_ip),
                                         tftp_prefix, asa_filename)
        logger.info('ASA image is available on {}'.format(asa_file_tftp_url))

        return self.baseline_asa_by_tftp_url(site=site, 
                                             asa_file_tftp_url=asa_file_tftp_url,
                                             uut_hostname=uut_hostname, 
                                             uut_password=uut_password,
                                             uut_ip=uut_ip, 
                                             uut_netmask=uut_netmask, 
                                             uut_gateway=uut_gateway,
                                             dns_servers=dns_servers, 
                                             search_domains=search_domains)

    def baseline_asa_by_tftp_url(
            self, 
            site, 
            asa_file_tftp_url,
            uut_hostname,
            uut_password, 
            uut_ip,
            uut_netmask, 
            uut_gateway,
            dns_servers, 
            search_domains):
        """Baseline Kp with ASA image by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the pxe-site
        and use them to baseline the device.

        :param site: PXE site to download image from e.g. 'ful', 'ast', 'bgl'
        :param asa_file_tftp_url: TFTP url to image on PXE server; Use IP address instead of host to be FXOS friendly
        :param uut_hostname: Device Host Name in the prompt
        :param uut_username: User Name to login to uut
        :param uut_password: Password to login to uut
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway

        :param dns_servers: DNS Servers
        :param search_domains: Search Domains
        """        
        r = re.search('tftp://([\d\.]+)/(.*)', asa_file_tftp_url)
        if not r:
            raise RuntimeError('Cannot parse asa_file_tftp_url {}'
                               ''.format(asa_file_tftp_url))
        pxe_ip = r.group(1)
        rommon_tftp_path = r.group(2)
        
        if self.sm.current_state == 'rommon_state':
            self.from_rommon_to_fxos(tftp_server=pxe_ip,
                                     rommon_file=rommon_tftp_path,
                                     uut_ip=uut_ip,
                                     uut_netmask=uut_netmask,
                                     uut_gateway=uut_gateway,
                                     username='admin',
                                     format_timeout=300)

        self.format_goto_rommon()
        self.from_rommon_to_fxos(tftp_server=pxe_ip,
                                 rommon_file=rommon_tftp_path,
                                 uut_ip=uut_ip,
                                 uut_netmask=uut_netmask,
                                 uut_gateway=uut_gateway,
                                 username='admin',
                                 format_timeout=300)

        self.fxos_network_config(uut_hostname=uut_hostname,
                                 uut_ip=uut_ip,
                                 uut_netmask=uut_netmask,
                                 uut_gateway=uut_gateway,
                                 dns_servers=dns_servers,
                                 search_domains=search_domains)

        self.from_fxos_download_app_bundle(app_bundle_url=asa_file_tftp_url)

        self.from_fxos_install_asa(asa_file=asa_file_tftp_url,
                                   uut_hostname=uut_hostname,
                                   uut_password=uut_password,
                                   uut_ip=uut_ip,
                                   uut_netmask=uut_netmask,
                                   uut_gateway=uut_gateway)

        self.asa_bootup_config(uut_hostname, uut_ip, uut_netmask, uut_gateway)

        logger.info('====== ASA baseline complete')

    def get_asa_bundle_name_template(self, asa_version):
        return 'cisco-asa-fp2k.{}.(SS[AB]|SPA)'.format(asa_version)
    
    def get_asa_bundle_name_pattern(self):
        return 'cisco-asa-fp2k\.([\d\.\-]+)\.(SS[AB]|SPA)'

    def find_asa_bundle_image(self, asa_branch, asa_version):
        pattern = self.get_asa_bundle_name_template(asa_version)
        files = search_asa_artifactory_with_regex(asa_branch,
                                                  asa_version,
                                                  pattern)

        if not len(files):
            raise RuntimeError('Found {} asa bundle image, instead of 1'
                               ''.format(len(files)))

        return files[0]

    def from_rommon_to_fxos(self, tftp_server, rommon_file,
                            uut_ip, uut_netmask, uut_gateway,
                            username, format_timeout=300):
        """Format disk and install integrated fxos build in rommon mode.

        :param tftp_server: tftp server ip that uut can reach
        :param rommon_file: build file with path,
               e.g. '/netboot/ims/Development/6.2.1-1159/installers/'
                    'fxos-k8-fp2k-lfbff.82.2.1.386i.SSA'
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param username: User Name to login to uut
        :param format_timeout: in sec; time to wait for rommon after format everything
                        default value is 300s
        :return: None

        """

        logger.info('====== format disk, download and install integrated '
                    'fxos build {} from server {} ...'.format(rommon_file, tftp_server))

        logger.info('=== Drop device into rommon mode')
        if self.sm.current_state != 'rommon_state':
            self.format_goto_rommon(timeout=format_timeout)

        logger.info('=== Configure management network interface')
        self.rommon_configure(tftp_server, rommon_file,
                              uut_ip, uut_netmask, uut_gateway)

        logger.info('=== Tftp download and install integrated fxos build')
        self.rommon_tftp_download(tftp_server, rommon_file, username)

        time.sleep(60)
        logger.info('=== Rommon build installed.')
        self.init_terminal()

    def fxos_network_config(self, uut_hostname, uut_ip, uut_netmask,
                            uut_gateway, dns_servers, search_domains):

        dns_server = dns_servers.split(',')[0]
        domain = uut_hostname.partition('.')[2]
        if domain == '':
            domain = search_domains

        # Set out of band ip, dns and domain
        logger.info('=== Set out of band ip, dns and domain')
        # time.sleep(120)
        cmd_lines_initial = """
            top
            scope system
                scope services
                    disable dhcp-server
                    create dns {}
                    set domain-name {}
                    show dns
                    show domain-name
            scope fabric a
                show detail
                set out-of-band static ip {} netmask  {} gw {}
                commit-buffer
                show detail
                top
            scope system
                scope services
                    show dns
                    show domain-name
                    top
            """.format(dns_server, domain,
                       uut_ip, uut_netmask, uut_gateway)
        self.execute_lines(cmd_lines_initial)

        logger.info('=== Done configuring fxos network')

    def from_fxos_download_app_bundle(self, app_bundle_url):
        bundle_package_name = app_bundle_url.split("/")[-1].strip()

        self.execute_lines('top\nscope firmware')

        retry_count = MAX_RETRY_COUNT
        while retry_count > 0:
            self.execute_lines('''
                top
                scope firmware
                ''')
            self.spawn_id.sendline('download image {}'.format(app_bundle_url))
            time.sleep(5)

            status = self._wait_till_download_complete(app_bundle_url)

            if status == "Failed":
                retry_count -= 1
                if retry_count == 0:
                    raise RuntimeError(
                        "Download failed after {} tries. Please check details "
                        "again: {}".format(MAX_RETRY_COUNT, app_bundle_url))
                logger.info("Download failed. Trying to download {} "
                            "more times".format(retry_count))
            elif status == "Downloaded":
                return
            logger.info('Download failed, the script will wait 5 minutes before retrying download again')
            for i in range(30):
                self.spawn_id.sendline('\x03')
                time.sleep(10)

    def from_fxos_install_asa(self, asa_file, uut_hostname, uut_password,
                              uut_ip, uut_netmask, uut_gateway):
        self.go_to('fxos_state')

        cmd_lines = """
                    top
                    scope firmware
                    scope auto-install
                """
        self.execute_lines(cmd_lines)

        pattern = self.get_asa_bundle_name_pattern()
        r = re.search(pattern, asa_file)
        if not r:
            raise RuntimeError('Cannot parse version from {}'.format(asa_file))
        asa_version = r.group(1)
        logger.info('====== Install security package {} ...'.format(asa_version))
        self.spawn_id.sendline("install security-pack version {}".format(asa_version))

        d1 = Dialog([
            ['Do you want to proceed', 'sendline(yes)', None, True, False],
            ['Triggered the install of software package version {}'.format(asa_version),
             None, None, True, False],
            ['Cisco Adaptive Security Appliance Software', None, None, True, False],
            ['ciscoasa> ', 'sendline(enable)', None, True, False],
            ['The enable password is not set.', None, None, True, False],
            ['Enter  Password: ', 'sendline({})'.format(uut_password), None, True, False],
            ['Repeat Password: ', 'sendline({})'.format(uut_password), None, True, False],
            ['ciscoasa# ', None, None, False, False]
        ])
        d1.process(self.spawn_id, timeout=1800)

    def asa_bootup_config(self, uut_hostname, uut_ip, uut_netmask, uut_gw):

        self.spawn_id.sendline('config t')
        self.spawn_id.expect('Help to improve the ASA platform')

        d = Dialog([
            ['\[A\]sk later:', 'sendline(N)', None, True, False],
            ['ciscoasa\(config\)# ', 'sendline(hostname {})'.format(uut_hostname), None, False, False],
            ['{}\(config\)# '.format(uut_hostname), None, None, False, False]
        ])
        d.process(self.spawn_id, timeout=5)
        self.sm.update_cur_state('config_state')

        cmd_lines = """
            interface Management1/1
             no ip addr dhcp
             ip addr {} {}
            route management 0 0 {}
        """.format(uut_ip, uut_netmask, uut_gw)
        self.spawn_id.sendline(cmd_lines)
        self.spawn_id.expect(uut_hostname)

    ### baseline ftd without an fxos image
    def baseline_ftd_by_branch_and_version(
            self, 
            site, 
            branch, 
            version, 
            uut_hostname, 
            uut_password, 
            uut_ip, 
            uut_netmask, 
            uut_gateway,                                                       
            dns_servers, 
            search_domains,
            uut_ip6=None, 
            uut_prefix=None,
            uut_gateway6=None,
            mode='local',
            manager=None,
            manager_key=None,
            manager_nat_id=None, 
            firewall_mode='routed'):
        """Baseline Kp with FTD image by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the pxe-site
        and use them to baseline the device.

        Notice for ASA to FTD Baselines: 
        ASA uses on a different State Machine to handle the ASA-cli (as opposed to FTD).
        The state machine is set/created when instantiating the KP Object via 'use_asa'.
        As a result, some state transitions will not work once FTD is installed.
        The instance of this device object cannot be used.
        
        To work around this, you will need to:
            * Disconnect the previous device object
            * Create a new KP object omitting 'use_asa' (Value is False by default)
            * Start a new connection and resume usage
     
        This will create a new device object with the FTD statemachine.

        :param site:           PXE site to download image from e.g. 'ful', 'ast', 'bgl'
        :param branch:         branch name, e.g. 'Release', 'Feature'
        :param version:        software build-version, e,g, 6.2.3-623

        :param uut_hostname:   Device Host Name in the prompt
        :param uut_username:   User Name to login to uut
        :param uut_password:   Password to login to uut
        :param uut_ip:         Device IP Address to access TFTP Server
        :param uut_netmask:    Device Netmask
        :param uut_gateway:    Device Gateway
        :param 
        :param dns_servers:    DNS Servers
        :param search_domains: Search Domains

        :param uut_ip6:        Device IPv6 Address
        :param uut_prefix:     Device IPv6 Prefix
        :param uut_gateway6:   Device IPv6 Gateway

        :param mode:           the manager mode (local, remote)
        :param manager:        FMC to be configured for registration
        :param manager_key:    Registration key
        :param manager_nat_id: Registration NAT Id

        :param firewall_mode:  the firewall mode (routed, transparent, ngips)       
        """
        logger.info('Preparing FTD image for tftp - pxe-site: {} branch: {} version: {}'.format(site,branch,version))            
        pxe_ip, tftp_prefix, scp_prefix, files = \
            prepare_installation_files(site, 'Kp', branch, version)
        ftd_filename = self.find_ftd_bundle_image(files)
        ftd_file_tftp_url = os.path.join('tftp://{}'.format(pxe_ip),
                                         tftp_prefix, ftd_filename)
        logger.info('FTD image is available on {}'.format(ftd_file_tftp_url))

        return self.baseline_ftd_by_tftp_url(site=site,
                                             ftd_file_tftp_url=ftd_file_tftp_url,                                              
                                             uut_hostname=uut_hostname, 
                                             uut_password=uut_password, 
                                             uut_ip=uut_ip, 
                                             uut_netmask=uut_netmask, 
                                             uut_gateway=uut_gateway,                                                       
                                             dns_servers=dns_servers, 
                                             search_domains=search_domains,
                                             uut_ip6=uut_ip6, 
                                             uut_prefix=uut_prefix,
                                             uut_gateway6=uut_gateway6,
                                             mode=mode,
                                             manager=manager,
                                             manager_key=manager_key,
                                             manager_nat_id=manager_nat_id, 
                                             firewall_mode=firewall_mode)

    def baseline_ftd_by_tftp_url(
            self,
            site,
            ftd_file_tftp_url,
            uut_hostname, 
            uut_password, 
            uut_ip, 
            uut_netmask, 
            uut_gateway,                                                       
            dns_servers, 
            search_domains,
            uut_ip6=None, 
            uut_prefix=None,
            uut_gateway6=None,
            mode='local',
            manager=None,
            manager_key=None,
            manager_nat_id=None, 
            firewall_mode='routed'):
        """Baseline Kp with FTD image by branch and version using PXE servers.
        Assumes image is already in place at ftd_file_tftp_url's path.

        Notice for ASA to FTD Baselines: 
        ASA uses on a different State Machine to handle the ASA-cli (as opposed to FTD).
        The state machine is set/created when instantiating the KP Object via 'use_asa'.
        As a result, some state transitions will not work once FTD is installed.
        The instance of this device object cannot be used.
        
        To work around this, you will need to:
            * Disconnect the previous device object
            * Create a new KP object omitting 'use_asa' (Value is False by default)
            * Start a new connection and resume usage
     
        This will create a new device object with the FTD statemachine.
        
        :param site:               PXE site to download image from e.g. 'ful', 'ast', 'bgl'
        :param ftd_file_tftp_url:  TFTP url to image on PXE server; Use IP address instead of host to be FXOS friendly
        :param uut_hostname:       Device Host Name in the prompt
        :param uut_username:       User Name to login to uut
        :param uut_password:       Password to login to uut
        :param uut_ip:             Device IP Address to access TFTP Server
        :param uut_netmask:        Device Netmask
        :param uut_gateway:        Device Gateway
        :param 
        :param dns_servers:        DNS Servers
        :param search_domains:     Search Domains

        :param uut_ip6:            Device IPv6 Address
        :param uut_prefix:         Device IPv6 Prefix
        :param uut_gateway6:       Device IPv6 Gateway

        :param mode:               The manager mode for FTD (local, remote)
        :param manager:            FMC to be configured for registration
        :param manager_key:        Registration key
        :param manager_nat_id:     Registration NAT Id

        :param firewall_mode:      the firewall mode (routed, transparent, ngips)         
        """
        r = re.search('tftp://([\d\.]+)/(.*)', ftd_file_tftp_url)
        if not r:
            raise RuntimeError('Cannot parse ftd_file_tftp_url {}'
                               ''.format(ftd_file_tftp_url))
        pxe_ip = r.group(1)
        rommon_tftp_path = r.group(2)

        if self.sm.current_state == 'rommon_state':
            self.from_rommon_to_fxos(tftp_server=pxe_ip,
                                     rommon_file=rommon_tftp_path,
                                     uut_ip=uut_ip,
                                     uut_netmask=uut_netmask,
                                     uut_gateway=uut_gateway,
                                     username='admin',
                                     format_timeout=300)

        self.format_goto_rommon()
        self.from_rommon_to_fxos(tftp_server=pxe_ip,
                                 rommon_file=rommon_tftp_path,
                                 uut_ip=uut_ip,
                                 uut_netmask=uut_netmask,
                                 uut_gateway=uut_gateway,
                                 username='admin',
                                 format_timeout=300)

        self.fxos_network_config(uut_hostname=uut_hostname,
                                 uut_ip=uut_ip,
                                 uut_netmask=uut_netmask,
                                 uut_gateway=uut_gateway,
                                 dns_servers=dns_servers,
                                 search_domains=search_domains)

        self.from_fxos_download_app_bundle(app_bundle_url=ftd_file_tftp_url)

        self.from_fxos_install_ftd(ftd_file=ftd_file_tftp_url)

        self.ftd_bootup_config(uut_hostname=uut_hostname, 
                               uut_password=uut_password, 
                               uut_ip=uut_ip,
                               uut_netmask=uut_netmask, 
                               uut_gateway=uut_gateway,
                               uut_ip6=uut_ip6,
                               uut_prefix=uut_prefix,
                               uut_gateway6=uut_gateway6,  
                               dns_servers=dns_servers,
                               search_domains=search_domains, 
                               mode=mode,
                               firewall_mode=firewall_mode)
                
        if mode != 'local':
            self.go_to('any')
            self.go_to('fireos_state')
            self.configure_manager(manager=manager, 
                                   manager_key=manager_key,
                                   manager_nat_id=manager_nat_id)
        
        ###Bug fix for CSCvu57632 ####
        self.go_to("any")
        self.go_to("fxos_state") # This does not go to FXOS state
        self.execute_lines('scope security\n'
                           'scope default-auth\n'
                           'set absolute-session-timeout 0\n'
                           'set session-timeout 0\n'
                           'commit-buffer\n'
                           'top\n')
        ####End of fix ###

        logger.info('====== FTD baseline complete')
        

    def get_ftd_bundle_name_pattern(self):
        return 'cisco-ftd-fp2k\.([\d\.\-]+)\.(SS[AB]|SPA)'

    def find_ftd_bundle_image(self, install_files):
        pattern = self.get_ftd_bundle_name_pattern()
        files = [file for file in install_files
                  if re.search(pattern, file)]

        if len(files) > 1:
            logger.info('Multiple FTD images were found for given branch and version: {}'.format(files))
            logger.info('The default behavior is to prioritize the .SSA build.')
            logger.info('If you would perfer to use a specific build, please use Kp.baseline_ftd_by_tftp_url()')
            for f in files:
                if f.endswith('SSA'):
                    return f
            return files[0]
        elif len(files) == 1:
            return files[0]
        else:
            raise RuntimeError('FTD image was not found in given PXE directory')

    def from_fxos_install_ftd(self, ftd_file):
        self.go_to('fxos_state')

        cmd_lines = """
                    top
                    scope firmware
                    scope auto-install
                """
        self.execute_lines(cmd_lines)

        pattern = self.get_ftd_bundle_name_pattern() 
        r = re.search(pattern, ftd_file)
        if not r:
            raise RuntimeError('Cannot parse version from {}'.format(ftd_file))
        ftd_version = r.group(1)
        logger.info('====== Install security package {} ...'.format(ftd_version))
        self.spawn_id.sendline("install security-pack version {}".format(ftd_version))

        d1 = Dialog([
            ['Do you want to proceed', 'sendline(yes)', None, True, False],
            ['Triggered the install of software package version {}'.format(ftd_version),
             None, None, True, False],
            ['INFO: Power-On Self-Test complete.', None, None, True, False],
            ['firepower> ', 'sendline(connect ftd)', None, True, False],
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, True, False],
            ['--More--', 'sendline(q)', None, True, False],
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA:",
             'sendline(YES)', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=1800)

    def ftd_bootup_config(
            self, 
            uut_hostname, 
            uut_password, 
            uut_ip,
            uut_netmask, 
            uut_gateway,
            uut_ip6,
            uut_prefix,
            uut_gateway6, 
            dns_servers,
            search_domains, 
            mode,
            firewall_mode):
        """Baseline Kp by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the pxe-site
        and use them to baseline the device.

        Args:
            uut_hostname:   Device Host Name in the prompt
            uut_username:   User Name to login to uut
            uut_password:   Password to login to uut
            uut_ip:         Device IP Address to access TFTP Server
            uut_netmask:    Device Netmask
            uut_gateway:    Device Gateway
            
            dns_servers:    DNS Servers
            search_domains: Search Domains

            uut_ip6:        Device IPv6 Address
            uut_prefix:     Device IPv6 Prefix
            uut_gateway6:   Device IPv6 Gateway

            mode:   the manager mode (local, remote)
            firewall_mode:  the firewall mode (routed, transparent, ngips)       
        """
        if mode == 'local':
            local_mode = 'yes'
        else:
            local_mode = 'no'

        d1 = Dialog([
            ['Do you want to configure IPv4', 'sendline(y)', None, True, False],
            ['Configure IPv4 via DHCP or manually', 'sendline(manual)', None,
             True, False],
            ['Enter an IPv4 address for the management interface',
             'sendline({})'.format(uut_ip), None, True, False],
            ['Enter an IPv4 netmask for the management interface',
             'sendline({})'.format(uut_netmask), None, True, False],
            ['Enter the IPv4 default gateway for the management interface',
             'sendline({})'.format(uut_gateway), None, True, False],
            ['Enter a fully qualified hostname for this system ',
             'sendline({})'.format(uut_hostname), None, True, False],
            ['Enter a comma-separated list of DNS servers or',
             'sendline({})'.format(dns_servers), None, True, False],
            ['Enter a comma-separated list of search domains or',
             'sendline({})'.format(search_domains), None, True, False],
            ['Manage the device locally?', 'sendline({})'.format(local_mode),
             None, True, False],
            ['Configure (firewall|deployment) mode', 'sendline({})'.format(firewall_mode),
             None, True, False],
            ['Successfully performed firstboot initial configuration steps',
             'sendline()', None, True, False],
            ['> ', None, None, False, False]
        ])

        # Handle IPv6 configurations
        if uut_ip6 and uut_prefix and uut_gateway6:
            d1.append(['Do you want to configure IPv6', 'sendline(y)', None, True, False])
            d1.append(['Configure IPv6 via DHCP, router, or manually',
                           'sendline(manual)', None, True, False])
            d1.append(['Enter the IPv6 address for the management interface',
                        'sendline({})'.format(uut_ip6), None, True, False])
            d1.append(['Enter the IPv6 address prefix for the management interface',
                        'sendline({})'.format(uut_prefix), None, True, False])
            d1.append(['Enter the IPv6 gateway for the management interface',
                        'sendline({})'.format(uut_gateway6), None, True, False])
        else:
            d1.append(['Do you want to configure IPv6', 'sendline(n)', None, True, False])
        
        d1.process(self.spawn_id, timeout=300)

        self.sm.update_cur_state('fireos_state')

    ### legacy code
    def baseline_by_branch_and_version(self, site, branch, version,
                                       uut_ip=None, uut_netmask=None, uut_gateway=None,
                                       dns_server='', serverIp='', tftpPrefix='', scpPrefix='', docs='', only_ftd=False, dhcp=False,
                                       **kwargs):
        """Baseline Kp by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the local kick server
        and use them to baseline the device.

        :param site: e.g. 'ful', 'ast', 'bgl'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param uut_ip: Device IP Address
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param \**kwargs:
            :Keyword Arguments, any of below optional parameters:
        :param uut_hostname: Device Host Name in the prompt
        :param uut_username: User Name to login to uut
        :param uut_password: Password to login to uut
        :param search_domains: search domain, defaulted to 'cisco.com'
        :param file_server_password: if use scp protocol, this is the password to
               download the image
        :param power_cycle_flag: if True power cycle the device before baseline
        :param mode: the manager mode (local, remote)
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param firewall_mode: the firewall mode (routed, transparent, ngips)
        :param timeout: in seconds; time to wait for installing the security package;
                        default value is 3600s
        :param reboot_timeout: in seconds; time to wait for system to restart;
                        default value is 300s
        :param only_ftd: Flag to install only FTD package, default is "False"
        :param dhcp: Flag to baselie with DHCP client enabled, default is "False"
        :return: dhcp_ip
        """

        if KICK_EXTERNAL:
            server_ip = serverIp
            tftp_prefix = tftpPrefix
            scp_prefix = scpPrefix
            files = docs
        else:
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 'Kp', branch, version)
        try:
            rommon_file = self._get_rommon_file(branch, version, files)

        except Exception as e:
            raise Exception('Got {} while getting fxos file'.format(e))
        rommon_image = os.path.join(tftp_prefix, rommon_file)
        files.remove(rommon_file)
        pkg_file = files[0]
        ftd_file = os.path.join('tftp://{}'.format(server_ip), tftp_prefix, pkg_file)
        logger.info('FDT image download path is {} '.format(ftd_file))
        if not kwargs.get('ftd_version'):
            ftd_version = re.findall(r'[\d.]+-[\d]+', version)[0]
            kwargs['ftd_version'] = ftd_version
        ###########Keyword Argument common on baseline_fp2k_ftd and  baseline_ftd ######
        kwargs['fxos_url'] = ftd_file
        kwargs['uut_ip'] = uut_ip
        kwargs['uut_netmask'] = uut_netmask
        kwargs['uut_gateway'] = uut_gateway
        kwargs['dns_servers'] = dns_server
        kwargs['dhcp'] = dhcp
        kwargs['search_domains'] = kwargs.get('search_domains', 'cisco.com')
        kwargs['uut_hostname'] = kwargs.get('uut_hostname', 'firepower')
        kwargs['uut_password'] = kwargs.get('uut_password', 'Admin123')
        logger.info("=======keyword arguments are======= ", kwargs)
        if only_ftd:
            dhcp_ip = self.baseline_ftd(**kwargs)
        else:
            kwargs['tftp_server'] = server_ip
            kwargs['rommon_file'] = rommon_image
            kwargs['uut_username'] = kwargs.get('uut_username', 'admin')
            dhcp_ip = self.baseline_fp2k_ftd(**kwargs)
        return dhcp_ip

    def install_rommon_build_fp2k(self, tftp_server, rommon_file,
                                   uut_ip, uut_netmask, uut_gateway,
                                   username, format_timeout=300):
        """Format disk and install integrated fxos build in rommon mode.

        :param tftp_server: tftp server ip that uut can reach
        :param rommon_file: build file with path,
               e.g. '/netboot/ims/Development/6.2.1-1159/installers/'
                    'fxos-k8-fp2k-lfbff.82.2.1.386i.SSA'
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param username: User Name to login to uut
        :param format_timeout: in sec; time to wait for rommon after format everything
                        default value is 300s
        :return: None

        """

        logger.info('====== format disk, download and install integrated '
                    'fxos build {} from server {} ...'.format(rommon_file, tftp_server))

        logger.info('=== Drop device into rommon mode')
        if self.sm.current_state != 'rommon_state':
            self.format_goto_rommon(timeout=format_timeout)

        logger.info('=== Configure management network interface')
        self.rommon_configure(tftp_server, rommon_file,
                              uut_ip, uut_netmask, uut_gateway)

        logger.info('=== Tftp download and install integrated fxos build')
        self.rommon_tftp_download(tftp_server, rommon_file, username)

        time.sleep(60)
        logger.info('=== Rommon build installed.')
        self.init_terminal()

    def upgrade_bundle_package_fp2k(self, bundle_package_name, ftd_version,
                                     uut_hostname, uut_password,uut_ip, uut_netmask, uut_gateway,
                                     dns_servers, search_domains,
                                     mode,
                                     uut_ip6, uut_prefix, uut_gateway6,
                                     firewall_mode,timeout=3600,dhcp=False):
        """Upgrade the ftd package and configure device.

        :param bundle_package_name: combined fxos and ftd image
               e.g. cisco-ftd-fp2k.6.2.1-1088.SSA
        :param ftd_version: ftd version, e.g. 6.2.1-1088
        :param uut_hostname: Device hostname or fqdn
        :param uut_password: Password to login to uut
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param dns_servers: DNS Servers
        :param search_domains: Search Domains
        :param mode: the manager mode (local, remote)
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param firewall_mode: the firewall mode (routed, transparent, ngips)
        :param dhcp: dhcp enabled or disable during FTD network configuration , default is "False"
        :param timeout: time to wait for installing the security package
        :return: None

        """

        self.go_to('fxos_state')

        cmd_lines = """
            top
            scope firmware
            scope auto-install
        """
        self.execute_lines(cmd_lines)
        logger.info('====== Install security package {} ...'.format(bundle_package_name))
        self.spawn_id.sendline("install security-pack version {}".format(
            re.search(r'[\d.]+-[\d]+', ftd_version).group()))

        # The system will reboot, wait for the following prompts
        d1 = Dialog([
            ['Invalid Software Version', None, None, False, False],
            ['Do you want to proceed', 'sendline(yes)', None, True, False],
            ['Triggered the install of software package version {}'.format(ftd_version),
             None, None, True, False],
            ['Stopping Cisco Firepower 21[1-4]0 Threat Defense', None, None, True, False],
            ['Rebooting...', None, None, True, False],
            ['Cisco FTD begins installation ...', None, None, True, False],
            ['Cisco FTD installation finished successfully.', None, None, True, False],
            ['Cisco FTD initialization finished successfully.', None, None, True, False],
            ['INFO: Power-On Self-Test complete.', None, None, True, False],
            ['INFO: SW-DRBG health test passed.', None, None, True, False],
            ['Failed logins since the last login:', None, None, False, False],
            ['Logins over the last', None, None, True, False],
            # ['[a-zA-Z0-9_-]+[^<]*[^>]>[^>]', 'sendline()', None, False, False],
            [self.sm.patterns.prompt.rommon_prompt, 'sendline({})'.format('boot'), None, True, False],
        ])
        ###Below fix is for defect CSCvq24032 where device was stuck in the FTD installation dialog###
        try:
            resp = d1.process(self.spawn_id, timeout=timeout)
            if isinstance(resp, ExpectMatch):
                if 'Invalid Software Version' in resp.match_output:
                    logger.error('Invalid Software Version,  please check your installation package')
                    raise RuntimeError('Invalid Software Version,  please check your installation package')
        except:
            self.spawn_id.buffer = ''
        #### End of fix####
        # send an ENTER to hit the prompt
        fxos_login_password = self.sm.patterns.login_password if self.change_password_flag else \
            self.sm.patterns.default_password
        self.spawn_id.sendline()
        d2 = Dialog([
            ['[ -~]+(?<!Last)(?<!failed) login: ', 'sendline({})'.format(self.sm.patterns.login_username),
             None, True, False],
            ['Password: ', 'sendline({})'.format(fxos_login_password), None, True, False],
            ['Enter new password:', 'sendline({})'.format(uut_password), None, True, False],
            ['Confirm new password:', 'sendline({})'.format(uut_password), None, True, False],
            ['firepower.*#', 'sendline({})'.format('connect ftd'), None, True, False],
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, False, False],

        ])
        d2.process(self.spawn_id, timeout=180)
        d3 = Dialog([
            ['--More--', 'send(q)', None, False, False],
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ", 'sendline()', None, False, False],
        ])

        d3.process(self.spawn_id, timeout=180)

        d4 = Dialog([
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ", 'sendline(YES)', None, True, False],
            ['Enter new password:', 'sendline({})'.format(uut_password), None, True, False],
            ['Confirm new password:', 'sendline({})'.format(uut_password), None, True, False],
            ['You must configure the network to continue.', None, None, False, False],
        ])
        d4.process(self.spawn_id, timeout=360)

        if dhcp:

            d5 = Dialog([
                ['Do you want to configure IPv4', 'sendline(y)', None, True, False],
            ])
            if uut_ip6 is None:
                d5.append(['Do you want to configure IPv6', 'sendline(n)', None, True, False])
            else:
                d5.append(['Do you want to configure IPv6', 'sendline(y)', None, True, False])
            d5.append(['Configure IPv4 via DHCP or manually', 'sendline(dhcp)', None,
                       True, False])
            d5.append(['For HTTP Proxy configuration, run \'configure network http-proxy\'', None, None, False, False])

            d5.process(self.spawn_id, timeout=600)
        else:

            d5 = Dialog([
                ['Do you want to configure IPv4', 'sendline(y)', None, True, False],
            ])
            if uut_ip6 is None:
                d5.append(['Do you want to configure IPv6', 'sendline(n)', None, True, False])
            else:
                d5.append(['Do you want to configure IPv6', 'sendline(y)', None, True, False])
            d5.append(['Configure IPv4 via DHCP or manually', 'sendline(manual)', None,
                       True, False])
            d5.append(['Enter an IPv4 address for the management interface',
                       'sendline({})'.format(uut_ip), None, True, False])
            d5.append(['Enter an IPv4 netmask for the management interface',
                       'sendline({})'.format(uut_netmask), None, True, False])
            d5.append(['Enter the IPv4 default gateway for the management interface',
                       'sendline({})'.format(uut_gateway), None, True, False])
            if uut_ip6 is not None:
                d5.append(['Configure IPv6 via DHCP, router, or manually',
                           'sendline(manual)', None, True, False])
                d5.append(['Enter the IPv6 address for the management interface',
                           'sendline({})'.format(uut_ip6), None, True, False])
                d5.append(['Enter the IPv6 address prefix for the management interface',
                           'sendline({})'.format(uut_prefix), None, True, False])
                d5.append(['Enter the IPv6 gateway for the management interface',
                           'sendline({})'.format(uut_gateway6), None, True, False])
            d5.append(['Enter a fully qualified hostname for this system ',
                       'sendline({})'.format(uut_hostname), None, True, False])
            d5.append(['Enter a comma-separated list of DNS servers or',
                       'sendline({})'.format(dns_servers), None, True, False])
            d5.append(['Enter a comma-separated list of search domains or',
                       'sendline({})'.format(search_domains), None, False, False])
            d5.process(self.spawn_id, timeout=600)

        d6 = Dialog([
            ['Configure (firewall|deployment) mode', 'sendline({})'.format(firewall_mode),
             None, True, False]
        ])

        if mode == 'local':
            d6.append(['Manage the device locally?', 'sendline(yes)', None, True, False])
        else:
            d6.append(['Manage the device locally?', 'sendline(no)', None, True, False])
        d6.append(['Successfully performed firstboot initial configuration steps',
                   'sendline()', None, True, False])
        d6.append([self.sm.patterns.prompt.fireos_prompt, 'sendline()', None, False, False])
        d6.process(self.spawn_id, timeout=900)

        # by the time we finish the above dialogs, and fireos_prompt is seen, we should now be in fireos_state
        self.sm.update_cur_state('fireos_state')
        ###Bug fix for CSCvu57632 ####
        self.go_to("fxos_state")
        self.execute_lines('scope security\n'
                           'scope default-auth\n'
                           'set absolute-session-timeout 0\n'
                           'set session-timeout 0\n'
                           'commit-buffer\n'
                           'top\n')
        self.go_to("fireos_state")
        ####End of fix ###
        logger.info('fully installed.')

    def validate_version(self, ftd_version):
        """Checks if the installed version matches the version from ftd version.
        :param ftd_version: ftd version, e.g. '6.2.1-1177'

        :return: None

        """
        response = self.execute('show version', 30)
        if not response:
            response = self.execute('show version', 30)
        build = re.findall('Build\s(\d+)', response)[0]
        version = re.findall(r'(Version\s){1}([0-9.]+\d)', str(response))[0][1]
        if build in ftd_version and version in ftd_version:
            logger.info('>>>>>> show version result:\n{}\nmatches '
                        'ftd package image: {}'.format(response, ftd_version))
            logger.info('Installed ftd version validated')
        else:
            logger.error('Exception: not the same version and build')
            raise RuntimeError('>>>>>> show version result:\n{}\ndoes not match '
                               'ftd package image: {}'.format(response, ftd_version))

        self.go_to('fxos_state')

    def baseline_fp2k_ftd(self, tftp_server, rommon_file,
                          uut_hostname, uut_username, uut_password,
                          uut_ip, uut_netmask, uut_gateway,
                          dns_servers, search_domains,
                          fxos_url, ftd_version, file_server_password="",
                          power_cycle_flag=False,
                          mode='local',
                          uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                          manager=None, manager_key=None, manager_nat_id=None,
                          firewall_mode='routed', timeout=3600, reboot_timeout=300,dhcp=False):
        """Upgrade the package and configure device.

        :param tftp_server: tftp server to get rommon and fxos images
        :param rommon_file: rommon build,
               e.g. '/netboot/ims/Development/6.2.1-1177/installers/'
                    'fxos-k8-fp2k-lfbff.82.2.1.386i.SSA'
        :param uut_hostname: Device Host Name in the prompt
        :param uut_username: User Name to login to uut
        :param uut_password: Password to login to uut
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_servers: DNS Servers
        :param search_domains: Search Domains
        :param fxos_url: FXOS+FTD image url,
               e.g. 'tftp://10.89.23.80/netboot/ims/Development/6.2.1-1177/'
                    'installers/cisco-ftd-fp2k.6.2.1-1177.SSA'
        :param ftd_version: ftd version, e.g. '6.2.1-1177'
        :param file_server_password: if use scp protocol, this is the password to
               download the image
        :param power_cycle_flag: if True power cycle the device before baseline
        :param dhcp: Flag to enable the DHCP client on FTD, default is "False"
        :param mode: the manager mode (local, remote)
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param firewall_mode: the firewall mode (routed, transparent, ngips)
        :param timeout: in seconds; time to wait for installing the security package;
                        default value is 3600s
        :param reboot_timeout: in seconds; time to wait for system to restart;
                        default value is 300s

        :return: dhcp_ip

        """
        publish_kick_metric('device.kp.baseline', 1)
        # Power cycle the device if power_cycle_flag is True
        logger.info('=== Power cycle the device if power_cycle_flag is True')
        logger.info('=== power_cycle_flag={}'.format(str(power_cycle_flag)))

        self.power_cycle_flag = power_cycle_flag

        if power_cycle_flag:
            self.power_cycle_goto_rommon(timeout=reboot_timeout)

        # Drop fp2k to rommon mode
        # Download rommon build and Install the build
        logger.info('=== Drop fp2k to rommon mode')
        logger.info('=== Download rommon build and Install the build')
        self.install_rommon_build_fp2k(tftp_server=tftp_server,
                                       rommon_file=rommon_file,
                                       uut_ip=uut_ip,
                                       uut_netmask=uut_netmask,
                                       uut_gateway=uut_gateway,
                                       username=uut_username,
                                       format_timeout=reboot_timeout)

        # Set out of band ip, dns and domain
        logger.info('=== Set out of band ip, dns and domain')
        dns_server = dns_servers.split(',')[0]
        domain = uut_hostname.partition('.')[2]
        if domain == '':
            domain = search_domains
        # Software Error: Exception during execution:
        # [Error: Timed out communicating with DME]
        time.sleep(120)
        cmd_lines_initial = """
            top
            scope system
                scope services
                    disable dhcp-server
                    create dns {}
                    set domain-name {}
                    show dns
                    show domain-name
            scope fabric a
                show detail
                set out-of-band static ip {} netmask  {} gw {}
                commit-buffer
                show detail
                top
            scope system
                scope services
                    show dns
                    show domain-name
                    top
            """.format(dns_server, domain,
                       uut_ip, uut_netmask, uut_gateway)
        self.execute_lines(cmd_lines_initial)

        # Download fxos package, select download protocol
        # based on the url prefix tftp or scp
        logger.info('=== Download fxos package, select download protocol')
        logger.info('=== based on the url prefix tftp or scp')
        self.download_ftd_fp2k(fxos_url=fxos_url,
                               file_server_password=file_server_password,
                               ftd_version=ftd_version)

        # Upgrade fxos package
        logger.info('=== Upgrade fxos package')
        bundle_package = fxos_url.split('/')[-1].strip()
        self.upgrade_bundle_package_fp2k(bundle_package_name=bundle_package,
                                         ftd_version=ftd_version,
                                         uut_hostname=uut_hostname,
                                         uut_password=uut_password,
                                         uut_ip=uut_ip,
                                         uut_netmask=uut_netmask,
                                         uut_gateway=uut_gateway,
                                         uut_ip6=uut_ip6,
                                         uut_prefix=uut_prefix,
                                         uut_gateway6=uut_gateway6,
                                         dns_servers=dns_servers,
                                         search_domains=search_domains,
                                         mode=mode,
                                         firewall_mode=firewall_mode,dhcp=dhcp,
                                         timeout=timeout)


        self.go_to('any')
        self.go_to('fireos_state')
        if manager is not None and mode != 'local':
            logger.info('=== Configure manager ...')
            self.configure_manager(manager=manager, manager_key=manager_key,
                                   manager_nat_id=manager_nat_id)

        if dhcp:
            self.go_to('fxos_state')
            self.init_terminal()
            self.go_to('fireos_state')
            logger.info('======DHCP IP======')
            dhcp_ip = self.network_detail()
            logger.info('Network details extracted  successfully.')
            return dhcp_ip
        else:
            pass
        self.go_to('any')
        self.go_to('fireos_state')
        logger.info('=== Validate installed version ...')
        self.validate_version(ftd_version=ftd_version)
        logger.info('Installation completed successfully.')

    def _is_split_version(self, version):
        """
        Whether the version may (combined with the right branch) use split fxos image.

        :param version:
        :return: True or False
        """
        r = re.search('^6.(\d)', version)
        if not r:
            raise RuntimeError("Cannot parse version {}".format(version))
        else:
            # split starts at 6.5
            return int(r.group(1)) >= 5

    def _get_rommon_file(self, branch, version, files):
        """
        Find the proper rommon_file.

        For old releases, it is always fxos-k8-fp2k-lfbff..., or fxos-k8-lfbff..., regardless
        of KP or WM. In new releases, it will be fxos-k8-fp2k for KP, fxos-k8-fp1k for WM.

        :param branch: such as Release
        :param version: such as 6.4.0-102
        :param files: list of files from prepare_installation_files()
                For example: ['cisco-ftd-fp2k.6.4.0-102.SPA',
                              'fxos-k8-fp2k-lfbff.2.6.1.133.SPA',
                              'fxos-k8-fp2k-lfbff.2.6.1.133i.SSB']
        :return:
        """

        if self._is_split_version(version):
            p = 'fxos-k8-fp2k-lfbff.*'
        else:
            p = 'fxos-k8-(fp2k-)?lfbff.*'

        if branch == 'Release':
            p += 'SPA'
        else:
            p += 'SSB'

        for f in files:
            if re.search(p, f):
                return f
        else:
            raise RuntimeError("Cannot file rommon_file in list of {}".format(files))

    def baseline_ftd(self, uut_hostname, uut_password,
                     uut_ip, uut_netmask, uut_gateway,
                     dns_servers, search_domains,
                     fxos_url, ftd_version, file_server_password="",
                     mode='local',
                     uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                     firewall_mode='routed',timeout=3600,dhcp=False):
        """Upgrade the FTD package and configure device.

        :param uut_hostname: Device Host Name in the prompt
        :param uut_password: Password to login to uut
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_servers: DNS Servers
        :param search_domains: Search Domains
        :param fxos_url: FXOS+FTD image url,
               e.g. 'tftp://10.89.23.80/netboot/ims/Development/6.2.1-1177/'
                    'installers/cisco-ftd-fp2k.6.2.1-1177.SSA'
        :param ftd_version: ftd version, e.g. '6.2.1-1177'
        :param file_server_password: if use scp protocol, this is the password to
               download the image
        :param mode: the manager mode (local, remote)
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param firewall_mode: the firewall mode (routed, transparent, ngips)
        :param timeout: in seconds; time to wait for installing the security package;
                        default value is 3600s
        :param reboot_timeout: in seconds; time to wait for system to restart;
                        default value is 300s
        :param dhcp: Flag to do the network configuration using DHCP , default is "False"
        :return: dhcp_ip

        """
        publish_kick_metric('device.kp.baseline', 1)
        logger.info('=== Download fxos package, select download protocol')
        logger.info('=== based on the url prefix tftp or scp')
        ####tftp download of FTD package , package will also contain compatible fxos###
        self.download_ftd_fp2k(fxos_url=fxos_url,
                               file_server_password=file_server_password,
                               ftd_version=ftd_version)
        # Upgrade fxos/ftd package
        logger.info('=== Upgrade fxos package')
        bundle_package = fxos_url.split('/')[-1].strip()
        self.upgrade_bundle_package_fp2k(bundle_package_name=bundle_package,
                                         ftd_version=ftd_version,
                                         uut_hostname=uut_hostname,
                                         uut_password=uut_password,
                                         uut_ip=uut_ip,
                                         uut_netmask=uut_netmask,
                                         uut_gateway=uut_gateway,
                                         uut_ip6=uut_ip6,
                                         uut_prefix=uut_prefix,
                                         uut_gateway6=uut_gateway6,
                                         dns_servers=dns_servers,
                                         search_domains=search_domains,
                                         mode=mode,
                                         firewall_mode=firewall_mode,
                                         dhcp=dhcp,
                                         timeout=timeout)

        if dhcp:
            self.go_to('fxos_state')
            self.init_terminal()
            self.go_to('fireos_state')
            logger.info('======Network configuration using DHCP======')
            dhcp_ip = self.network_detail()
            logger.info('Network details extracted  successfully.')
            return dhcp_ip
        else:
            pass
        self.go_to('any')
        self.go_to('fireos_state')
        logger.info('=== Validate installed version ...')
        self.validate_version(ftd_version=ftd_version)
        logger.info('Installation completed successfully.')

    def network_detail(self):
        """Get and return the IP assigned by dhcp  , e.g. '192.168.0.106'

        :return: ip

        """

        global ip
        ####This sleep is added to reflect the DHCP network configuration on FTD#####
        time.sleep(10)
        response_output = self.execute('show network', 20)
        ip = re.findall(r'Address\s+:(\s\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', str(response_output))[0]
        logger.debug("DHCP IP is ", ip)
        if 'Address' in response_output and ip is not None:
            logger.info('>>>>>> show network result:\n{}\ncontains '
                        'DHCP IP: {}'.format(str(response_output), ip))
            logger.info('DHCP IP validated')
        else:
            logger.error('Exception: IP not assign to management')
            raise RuntimeError('>>>>>> show network result:\n{}\ndoes not contain'
                               'DHCP IP : {}; Please check the dhcp-server is enabled or not'.
                               format(str(response_output), ip))
        self.sm.update_cur_state('fireos_state')
        return ip

