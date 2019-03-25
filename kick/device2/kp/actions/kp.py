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
from .statemachine import KpStateMachine
from ...general.actions.basic import BasicDevice, BasicLine, NewSpawn
from ...general.actions.power_bar import power_cycle_all_ports

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
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
                 *args,
                 **kwargs
                 ):
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
        :kwargs
        :param: 'config_hostname': output of 'show running-config hostname'
        :return: None

        """

        super().__init__()
        publish_kick_metric('device.kp.init', 1)
        self.set_default_timeout(DEFAULT_TIMEOUT)

        # set hostname, login_username and login_password
        config_hostname = kwargs.get('config_hostname', 'firepower')
        self.patterns = KpPatterns(hostname, login_username, login_password, sudo_password, config_hostname)

        # create the state machine that contains the proper attributes.
        self.sm = KpStateMachine(self.patterns)

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
                    '-o StrictHostKeyChecking=no -l {usr} -p {port} {ip} \n'\
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

        try:
            super().__init__(spawn_id, sm, type, timeout=timeout)
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

    def init_terminal(self, determine_state=True):
        """Initialize terminal size."""
        try:
            if determine_state:
                self.go_to('any')
            self.go_to('fxos_state')
        except StateMachineError as exc:
            logger.error('Cannot initialize FXOS terminal in KP: {}'.format(str(exc)), exc_info=True)
            return

        for cmd in KpInitCmds.split('\n'):
            cmd = cmd.strip()
            if cmd == "":
                continue
            self.execute_only(cmd)

    def disconnect(self):
        """Disconnect the Device."""
        if self.chassis_line:
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

        result = power_cycle_all_ports(self.power_bar_server, self.power_bar_port, self.power_bar_user, self.power_bar_pwd)

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
            ['application_name', 'slot_id', 'admin_state', 'operational_state', 'running_version',
            'startup_version', 'cluster_oper_state', 'cluster_role', 'job_type', 'job_progress',
            'job_state', 'clear_log_data', 'error_msg', 'hotfixes', 'externally_upgraded'])
        app_instance_list = []

        blocks = [i.start() for i in re.finditer('Application Name:', output)]
        if blocks:
            blocks.append(len(output))
            for i in range(0, len(blocks)-1):
                name = slot = admin_state = oper_state = \
                running_version = startup_version = cluster_oper_state = job_type = \
                job_progress = job_state = clear_log_data = error_msg = hotfixes = \
                externally_upgraded = cluster_role = None

                for line in output[blocks[i]: blocks[i+1]].splitlines():
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

    def _get_download_status(self, image_name):
        """Gets the status of download

        :param image_name: the name of the image. it should look like:
               fxos-k9.2.0.1.68.SPA
        :return: status as 'Downloaded' or 'Downloading'

        """

        self.go_to('fxos_state')
        output = self.execute('show download-task {} detail | grep State'
                              ''.format(image_name))

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

        self.spawn_id.sendline('connect local-mgmt')
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

        # self.go_to('rommon_state')
        logger.info('add rommon config')
        es_list = [
            ['rommon', 'address {}'.format(uut_ip)],
            ['rommon', 'netmask {}'.format(uut_netmask)],
            ['rommon', 'gateway {}'.format(uut_gateway)],
            ['rommon', 'server {}'.format(tftp_server)],
            ['rommon', 'image {}'.format(rommon_file)],
            ['rommon', 'sync'],
        ]
        self.expect_and_sendline(self.spawn_id, es_list)

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
                             timeout=600):
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
            ['rommon.*> ', 'sendline(tftpdnld)', None, True, False],
            ['[a-zA-Z0-9_-]+[^\bLast \b] login: ', 'sendline({})'.format(username), None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.default_password), None, False, False],
        ])

        try:
            d.process(self.spawn_id, timeout=timeout)
            #self.spawn_id.sendline()
            logger.info("=== Rommon file was installed successfully.")
        except:
            logger.info("=== Rommon file download failed, raise runtime error. ")
            raise RuntimeError(
                "Download failed. Please check details - "
                "tftp_server: {}, image file: {}".format(tftp_server, rommon_file))

        # handle change fxos password dialog
        self.__change_password()
        self.spawn_id.sendline()

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
        else:
            # issue factory reset from rommon and
            # then format everything in order to reset the device to default values
            self.rommon_factory_reset_and_format(format_timeout=format_timeout)

        logger.info('=== Configure management network interface')
        self.rommon_configure(tftp_server, rommon_file,
                              uut_ip, uut_netmask, uut_gateway)

        logger.info('=== Tftp download and install integrated fxos build')
        self.rommon_tftp_download(tftp_server, rommon_file, username)

        time.sleep(60)
        self.init_terminal()
        logger.info('=== Rommon build installed.')

    def upgrade_bundle_package_fp2k(self, bundle_package_name, ftd_version,
                                    uut_hostname, uut_password,
                                    uut_ip, uut_netmask, uut_gateway,
                                    dns_servers, search_domains,
                                    mode,
                                    uut_ip6, uut_prefix, uut_gateway6,
                                    firewall_mode, timeout=3600):
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
            #['[a-zA-Z0-9_-]+[^<]*[^>]>[^>]', 'sendline()', None, False, False],
            [self.sm.patterns.prompt.rommon_prompt, 'sendline({})'.format('boot'), None, True, False],
        ])
        resp = d1.process(self.spawn_id, timeout=timeout)
        if isinstance(resp, ExpectMatch):
            if 'Invalid Software Version' in resp.match_output:
                logger.error('Invalid Software Version,  please check your installation package')
                raise RuntimeError('Invalid Software Version,  please check your installation package')

        # send an ENTER to hit the prompt
        fxos_login_password = self.sm.patterns.login_password if self.change_password_flag else \
            self.sm.patterns.default_password

        self.spawn_id.sendline()
        d2 = Dialog([
            ['[a-zA-Z0-9_-]+[^\bLast \b] login: ', 'sendline(admin)', None, True, False],
            ['Password: ', 'sendline({})'.format(fxos_login_password), None, True, False],
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

        logger.info('fully installed.')

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
                          firewall_mode='routed', timeout=3600, reboot_timeout=300):
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
        :return: None

        """
        publish_kick_metric('device.kp.baseline', 1)
        # Power cycle the device if power_cycle_flag is True
        logger.info('=== Power cycle the device if power_cycle_flag is True')
        logger.info('=== power_cycle_flag={}'.format(str(power_cycle_flag)))
        if power_cycle_flag:
            self.power_cycle_goto_rommon(timeout=reboot_timeout)
            self.rommon_factory_reset_and_format(format_timeout=reboot_timeout)

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
                                         firewall_mode=firewall_mode,
                                         timeout=timeout)

        self.go_to('any')
        self.go_to('fireos_state')

        if manager is not None and mode != 'local':
            logger.info('=== Configure manager ...')
            self.configure_manager(manager=manager, manager_key=manager_key,
                                   manager_nat_id=manager_nat_id)

        logger.info('=== Validate installed version ...')
        self.validate_version(ftd_version=ftd_version)

        logger.info('Installation completed successfully.')

    def baseline_by_branch_and_version(self, site, branch, version,
                                       uut_ip, uut_netmask, uut_gateway,
                                       dns_server='', serverIp='', tftpPrefix='', scpPrefix='', docs='', **kwargs):
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
        :return: None

        """

        if KICK_EXTERNAL:
            server_ip = serverIp
            tftp_prefix = tftpPrefix
            scp_prefix = scpPrefix
            files = docs
        else:
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 'Kp', branch, version)
        try:
            rommon_file = [file for file in files if file.startswith('fxos-k8-fp2k-lfbff')][0]
        except Exception as e:
            raise Exception('Got {} while getting fxos file'.format(e))
        rommon_image = os.path.join(tftp_prefix, rommon_file)
        files.remove(rommon_file)
        pkg_file = files[0]
        ftd_file = os.path.join('tftp://{}'.format(server_ip), tftp_prefix, pkg_file)

        if not kwargs.get('ftd_version'):
            ftd_version = re.findall(r'[\d.]+-[\d]+', version)[0]
            kwargs['ftd_version'] = ftd_version

        kwargs['tftp_server'] = server_ip
        kwargs['rommon_file'] = rommon_image
        kwargs['fxos_url'] = ftd_file
        kwargs['uut_ip'] = uut_ip
        kwargs['uut_netmask'] = uut_netmask
        kwargs['uut_gateway'] = uut_gateway
        kwargs['dns_servers'] = dns_server
        kwargs['search_domains'] = kwargs.get('search_domains', 'cisco.com')
        kwargs['uut_hostname'] = kwargs.get('uut_hostname', 'firepower')
        kwargs['uut_username'] = kwargs.get('uut_username', 'admin')
        kwargs['uut_password'] = kwargs.get('uut_password', 'Admin123')

        self.baseline_fp2k_ftd(**kwargs)

    def __change_password(self):

        # handle change password enforcement at first login
        change_password_dialog = Dialog([
            ['You are required to change your password', None, None, True, False],
            ['System is coming up', lambda: time.sleep(60), None, True, False],
            ['[a-zA-Z0-9_-]+[^\bLast \b] login:', 'sendline({})'.format(self.sm.patterns.login_username), None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.default_password), None, True, False],
            ['Enter old password:', 'sendline({})'.format(self.sm.patterns.default_password), None, True, False],
            ['Enter new password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
            ['Confirm new password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
            ['Your password (was|has been) updated successfully', None, None, False, False],
            [self.sm.patterns.prompt.fxos_prompt, None, None, False, False]
        ])

        output = change_password_dialog.process(self.spawn_id, timeout=900)
        if 'updated successfully' in output.match_output:
            self.change_password_flag = True
            logger.info('Password has been changed successfully')
        else:
            logger.info('Changing password was not required...')
