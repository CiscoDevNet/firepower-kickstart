"""Library to load new images on a Sensor Series3.

We require a file server to be co-located with the device. This file
server has both the img files mounted.  Image downloading is via http.

The file server is a PXE server in each site.

"""
import logging
import os
import subprocess
import re
import urllib
import time

import datetime

logger = logging.getLogger(__name__)

from unicon.eal.expect import Spawn, TimeoutError
from unicon.eal.dialogs import Dialog
from kick.device2.series3.actions.webserver import Webserver
from ...general.actions.basic import BasicDevice, BasicLine
from kick.device2.general.actions.power_bar import power_cycle_all_ports
try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True
    pass


DUT_DIR_TMP = '/tmp'
DUT_DIR_BOOT = '/boot'
DUT_DIR_ETC = '/etc'
DUT_LILO_TMPL_FILE = 'lilo.conf'
DUT_LILO_FILE = 'lilo.conf.atf'
DUT_LILO_TMPL_PATH = '{}/{}'.format(DUT_DIR_ETC, DUT_LILO_TMPL_FILE)
DUT_LILO_TMP_PATH = '{}/{}'.format(DUT_DIR_TMP, DUT_LILO_FILE)
DUT_LILO_PATH = '{}/{}'.format(DUT_DIR_ETC, DUT_LILO_FILE)
MAX_TIME_INSTALL = 7200
DEFAULT_TIMEOUT = 10
SSH_DEFAULT_TIMEOUT = 90


class Series3(BasicDevice):
    def __init__(self, hostname='firepower', login_username='admin',
                 login_password='Admin123',
                 sudo_password='Admin123'):
        """Constructor for FTD.

        :param hostname: hostname for the device
        :param login_username: user credentials
        :param login_password: device login password with user name 'admin'
        :param sudo_password: device sudo password for 'root'

        """

        super().__init__()
        publish_kick_metric('device.series3.init', 1)
        from .patterns import Series3Patterns
        self.patterns = Series3Patterns(hostname, login_username,
                                        login_password, sudo_password)

        # create the state machine that contains the proper attributes.
        from .statemachine import Series3Statemachine
        self.sm = Series3Statemachine(self.patterns)

        self.line_class = Series3Line

    def ssh_vty(self, ip, port, username='admin', password='Admin123', timeout=None,
                line_type='ssh', rsa_key=None):
        """
        Set up an ssh connection to device's interface.

        This goes into device's ip address, not console.

         :param ip: ip address of terminal server
         :param port: port of device on terminal server
         :param username: usually "admin"
         :param password: usually "Admin123"
         :param line_type: 'ssh'
         :param timeout: in seconds
         :param rsa_key: identity file (full path)
         :return: a line object (where users can call execute(), for example)

         """

        publish_kick_metric('device.series3.ssh', 1)
        if not timeout:
            timeout = self.default_timeout

        from .constants import Series3Constants
        Series3Constants.uut_ssh_ip = ip
        Series3Constants.uut_ssh_port = port
        
        if rsa_key:
            resp = subprocess.getoutput('chmod 400 {}'.format(rsa_key))
            if 'No such file or directory' in resp:
                raise RuntimeError(
                    'The identity file {} you provided does not exist'.format(
                        rsa_key))
            spawn = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                          '-i {} -l {} -p {} {} \n'.format(rsa_key, username, port, ip))
        else:
            spawn = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                          '-l {} -p {} {} \n'.format(username, port, ip))
        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['(p|P)assword:', 'sendline({})'.format(password),
             None, False, False],
        ])
        try:
            d1.process(spawn, timeout=timeout)
        # spawn.sendline()
        except TimeoutError:
            logger.info("\n SSH Connection not available...")
            pass

        ssh_line = Series3Line(spawn, self.sm, line_type, timeout=timeout)
        return ssh_line

    def log_checks(self, ftd_line, list_files=['/var/log/messages'],
                   search_strings=['fatal', 'error'], exclude_strings=[], timeout=300):
        """Wrapper function to Get logs for FTD.

        :param ftd_line: Instance of FTD line used to connect to FTD
        :param list_files: List of file paths for files to search in
        :param search_strings: List of keywords to be searched in the logs
        :param exclude_strings: List of keywords to be excluded in the logs
        :param timeout: The number for seconds to wait for log retrieval
                        e.g list_files = ['/var/log/boot_1341232','/var/log/boot_*']
                        search_strings = ['fatal','error', 'crash']
                        exclude_strings = ['ssl_flow_errors', 'firstboot.S09']

        """

        self.sm.go_to('sudo_state', ftd_line.spawn_id)

        grep_command_list = []
        exclude_line = ''

        if exclude_strings:
            exclude_cmd = ['| grep -v {}'.format(string) for string in exclude_strings]
            exclude_line = ''.join(exclude_cmd)

        if list_files and search_strings:
            for file in list_files:
                for string in search_strings:
                    grep_command = "grep -Ii {} {} | " \
                                   "sort -u {}".format(string, file, exclude_line)
                    grep_command_list.append(grep_command)
        try:
            output_log = ftd_line.execute_lines(("\n".join(grep_command_list)),
                                                timeout=timeout)
        except:
            output_log = "Log retrieval command timed out"

        logger.info("""
            ***********************************************************

            Logs for the requested files in FTD are : -

            {}

            ***********************************************************
            """.format(output_log))


class Series3Line(BasicLine):
    def __init__(self, spawn, sm, type, timeout=None):
        """Constructor for series3 line A

        :param spawn: spawn of the line
        :param sm: object of statemachine
        :param type: line type, e.g. 'ssh', 'telnet'
        :return: None

        """
        self.spawn_id = spawn
        self.sm = sm
        self.type = type
        self.set_default_timeout(DEFAULT_TIMEOUT)
        try:
            sm.go_to('any', spawn, timeout=timeout)
        except:
            # Catch the case ftd is back from installation
            # Does not have a stable state
            pass

    def expert_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """
        :param cmd: cpmmand to be executed in expert state given as a string
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :return: output as string
        """
        self.go_to('expert_state')
        return self.execute(cmd, timeout, exception_on_bad_command)

    ### the following functions are for device baselining. This only works on
    ### a ssh connection.
    def generate_config_file(self):
        """Compose the config file. Copy the config file to
        self.http_dir_for_build on Webserver. Create symbolic link to the iso
        image on Webserver.

        :return: None

        """

        server = Webserver(hostname=self.scp_hostname,
                           login_username=self.scp_username,
                           login_password=self.scp_password)
        dev = server.ssh_vty(self.scp_server)
        output = dev.execute('mkdir -p -m 775 {}'.format(self.http_dir_for_build))
        result = re.search('File exists', output)
        if result is not None:
            logger.info('File exists and it will be deleted ...')
            dev.execute('rm -rf {}'.format(self.http_dir_for_build))
            dev.execute('mkdir -p -m 775 {}'.format(self.http_dir_for_build))
        dev.execute('ln -s {}/{} {}'.format(self.http_dir_root,
                                            self.iso_image_path, self.http_dir_for_build))
        config_file_content = """TRANS=httpsrv
SRV={}
IPCONF=dhcp
REPLACE_TFTP_BOOT_FILE=Yes
TFTPSERVER={}
FN={}
TARGET_ARCH={}
""".format(self.http_server,
           self.http_server,
           self.iso_image_path,
           self.arch)
        dev.execute('echo "{}" > {}'.format(config_file_content, self.config_path))
        output = dev.execute('ls {}'.format(self.config_path))
        output = dev.execute('cat {}'.format(self.config_path))
        output = dev.execute('wget -O - http://{}:{}/{}'.format(self.http_server, self.http_port, self.config_file_url))
        assert 'TRANS=httpsrv' in output, \
            '\nFailed to access the boot configuration file.\nVerify http_dir_tmp is correct.\nhttp://{}:{}/{}'. \
                format(self.http_server, self.http_port, self.config_file_url)
        dev.disconnect()

    def scp_file_to_local(self, local_dir, sftp_ip, sftp_port,
                          username, password, remote_path):
        """Scp a remote file to DUT.

        :param local_dir: local directory as the destination directory on DUT
        :param sftp_ip: remote sftp server ip address
        :param sftp_port: remote sftp server port
        :param username: username to login to sftp server
        :param password: password to login to sftp server
        :param remote_path: file path with filename on remote sftp server
        :return: None

        """

        filename = remote_path.split('/')[-1]
        self.execute('rm -f {}/{}'.format(local_dir, filename))
        self.spawn_id.sendline('scp -P {} {}@{}:{} {}'.format(sftp_port,
                                                              username, sftp_ip, remote_path, local_dir))
        current_prompt = self.sm.get_state(self.sm.current_state).pattern
        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['(p|P)assword:', 'sendline({})'.format(password), None, True, False],
            [current_prompt, 'sendline()', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=300)
        self.execute('pwd', timeout=180)
        time.sleep(1)
        self.read_buffer()
        output = self.execute('ls -ltr {}/{}'.format(local_dir, filename),
                              timeout=20)
        full_filename = output.split('/')[-1]
        logger.info('filename={}, full_filename={}'.format(filename,
                                                           full_filename))
        assert ('No such file or directory' not in output) and \
               (filename[:-1] in full_filename), \
            'Failed to copy {}'.format(filename)
        return full_filename

    def copy_bz_usb_files_setup_lilo_to_install(self):
        """Scp bz and usb image files from remote sftp server to DUT. Configure
        lilo file on DUT. Execute run_lilo_and_depmod. Mount usb. Reboot to
        install.

        :return: None

        """

        # Scp bz and usb files
        self.go_to('sudo_state')

        full_bz_filename = self.scp_file_to_local(local_dir=DUT_DIR_TMP,
                                                  sftp_ip=self.scp_server, sftp_port=self.scp_port,
                                                  username=self.scp_username, password=self.scp_password,
                                                  remote_path=self.bz_image_path)
        logger.info('=== Extract bz_filename from {}: {}'.format(self.bz_image_path,
                                                                 full_bz_filename))
        full_usb_filename = self.scp_file_to_local(local_dir=DUT_DIR_TMP,
                                                   sftp_ip=self.scp_server, sftp_port=self.scp_port,
                                                   username=self.scp_username, password=self.scp_password,
                                                   remote_path=self.usb_image_path)
        logger.info('=== Extract usb_filename from {}: '
                    '{}'.format(self.usb_image_path,
                                full_usb_filename))
        cmd = 'mv {}/{} {}'.format(DUT_DIR_TMP,
                                   full_bz_filename,
                                   DUT_DIR_BOOT)
        self.execute_only(cmd=cmd)

        cmd = 'mv {}/{} {}'.format(DUT_DIR_TMP,
                                   full_usb_filename,
                                   DUT_DIR_BOOT)
        self.execute_only(cmd=cmd)

        # Generate lilo file
        cmd = "cat {} | perl -pe 's/default=[^\n]+/default=INSTALL/g'" \
              " > {}".format(DUT_LILO_TMPL_PATH, DUT_LILO_TMP_PATH)
        self.execute_only(cmd=cmd)

        lilo_append_lines = """
image=/boot/{}
      label=INSTALL
      read-only
      initrd=/boot/{}
      append="root=/dev/ram0 rw PRESERVE_DATA=Yes choicedevice=eth0 INTEGCONF={}/{}"
""".format(full_bz_filename, full_usb_filename, self.http_server, self.config_file_url)
        cmd = '''echo '{}' >> {}'''.format(lilo_append_lines,
                                           DUT_LILO_TMP_PATH)
        self.execute_only(cmd=cmd)

        self.execute('cat {}'.format(DUT_LILO_TMP_PATH))
        self.execute('mv {} {}'.format(DUT_LILO_TMP_PATH, DUT_LILO_PATH))
        logger.info('=== Generated lilo file [{}]\n{}\n'.format(DUT_LILO_PATH,
                                                                lilo_append_lines))
        logger.info('=== run_lilo_and_depmod')
        cmd = '/bin/bash -c "source /etc/lilo.d/functions.lilo; ' \
              'run_lilo_and_depmod"'
        self.execute_only(cmd=cmd, timeout=180)

        self.execute('mount LABEL=SFKEYFOB /usb')
        self.execute('lilo -P ignore -C /etc/lilo.conf.atf')
        self.execute('lilo -q 2>&1')
        logger.info('=== System will reboot!')
        self.spawn_id.sendline('reboot')

    def confirm_device_rebooted(self):
        """Confirm device is rebooting by executing command pwd.

        If device is not reachable, exit. Wait until device is not
        reachable.

        """

        count = 0
        wait_time = 60
        total_count = 20
        while count < total_count:
            try:
                self.execute('pwd')
                count += 1
                logger.info('=== Wait {} seconds for device to reboot ...'.
                            format(wait_time))
                time.sleep(wait_time)
            except:
                logger.info('=== The Appliance at {} is Rebooting.'.format(self.uut_ip))
                break
        if count >= total_count:
            msg = '=== The appliance {} does not appear to have gone down' \
                  ' for reboot. Installer has failed'.format(self.uut_ip)
            logger.info(msg)
            raise RuntimeError(msg)

    def reconnect_and_process_dialog(self, device_reconnect_count, wait_time,
                                     dialog_timeout, start_time, dialog_name, dialog):
        """Reconnect to the device. Process the dialog. Device could reboot
        multiple times. Wait until the device can be accessed and dialog is
        processed.

        :param device_reconnect_count: initial device reconnect count
        :param wait_time: wait time in each loop
        :param dialog_timeout: dialog timeout
        :param start_time: installation start time used to calculate elapsed_time
        :param dialog_name: dialog name used for logging info
        :param dialog: object of Dialog to be processed for device configuration

        """
        from .constants import Series3Constants
        now = datetime.datetime.now()
        elapsed_time = (now - start_time).total_seconds()
        initial_password = self.sm.patterns.default_password
        if elapsed_time < self.installation_timeout:
            logger.info('=== Sleep for {} seconds'.format(wait_time))
        # Once EULA is agreed, device will reboot again

        is_up = True
        while elapsed_time < self.installation_timeout:
            try:
                logger.info('=== Begin: {}'.format(dialog_name))
                time.sleep(wait_time)

                if not self.console:
                    newdev = self.ftd.ssh_vty(ip=Series3Constants.uut_ssh_ip,
                                              port=Series3Constants.uut_ssh_port,
                                              password=initial_password,
                                              timeout=self.ssh_timeout)
                    self.spawn_id = newdev.spawn_id
                    self.sm = newdev.sm
                    device_reconnect_count += 1
                    logger.info('Device reconnected, {} times'.format(device_reconnect_count))
                logger.info('Started dialog process spawn {} timeout {}'.format(self.spawn_id, dialog_timeout))
                dialog.process(self.spawn_id, timeout=dialog_timeout)
                logger.info('=== End: {}'.format(dialog_name))
                return device_reconnect_count
            except Exception as e:
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
                logger.info('=== Device cannot be accessed, elapsed_time={}, '
                            'wait for {} seconds. Exception {} ...'.format(elapsed_time, wait_time, e))
                is_up = False

        if not is_up:
            raise RuntimeError('=== Waited enough time for device to be up. Seems like it is gone!')

    def poll_device_and_configure(self):
        """Device configuration: agree to EULA, network configuration. Device
        will reboot multiple times.

        :return: None

        """

        start_time = datetime.datetime.now()
        elapsed_time = 0

        if not self.console:
            # Wait for the second reboot
            d0 = Dialog([
                ['Broadcast message from', None, None, False, False],
            ])

            device_reconnect_count0 = self.reconnect_and_process_dialog(
                device_reconnect_count=0,
                wait_time=120,
                dialog_timeout=3600,
                start_time=start_time,
                dialog_name='wait for second reboot',
                dialog=d0)
        else:
            device_reconnect_count0 = 0

        d1 = Dialog([
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, True, False],
            ['--More--', 'send(q)', None, True, False],
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ",
             'sendline(YES)', None, True, False],
            ['You must change the password for ', None, None, False, False],
        ])

        device_reconnect_count1 = self.reconnect_and_process_dialog(
            device_reconnect_count=device_reconnect_count0,
            wait_time=120,
            dialog_timeout=3600,
            start_time=start_time,
            dialog_name='wait for EULA agreement',
            dialog=d1)

        d2 = Dialog([
            ['Enter new password:', 'sendline({})'.format(self.sm.patterns.login_password),
             None, True, True],
            ['Confirm new password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True,
             False],
            ['Do you want to configure IPv4', 'sendline(y)', None, True, False],
        ])

        if self.uut_ip6 is None:
            d2.append(['Do you want to configure IPv6', 'sendline(n)', None, True, False])
        else:
            d2.append(['Do you want to configure IPv6', 'sendline(y)', None, True, False])

        d2.append(['Configure IPv4 via DHCP or manually', 'sendline(manual)', None, True, False])
        d2.append(['Enter an IPv4 address for the management interface',
                   'sendline({})'.format(self.uut_ip), None, True, False])
        d2.append(['Enter an IPv4 netmask for the management interface',
                   'sendline({})'.format(self.uut_netmask), None, True, False])
        d2.append(['Enter the IPv4 default gateway for the management interface',
                   'sendline({})'.format(self.uut_gateway), None, True, False])

        if self.uut_ip6 is not None:
            d2.append(['Configure IPv6 via DHCP, router, or manually', 'sendline(manual)', None, True, False])
            d2.append(['Enter the IPv6 address for the management interface',
                       'sendline({})'.format(self.uut_ip6), None, True, False])
            d2.append(['Enter the IPv6 address prefix for the management interface',
                       'sendline({})'.format(self.uut_prefix), None, True, False])
            d2.append(['Enter the IPv6 gateway for the management interface',
                       'sendline({})'.format(self.uut_gateway6), None, True, False])

        d2.append(['Enter a fully qualified hostname for this system ',
                   'sendline({})'.format(self.hostname), None, True, False])
        d2.append(['Enter a comma-separated list of DNS servers or',
                   'sendline({})'.format(self.dns_server), None, True, False])
        d2.append(['Enter a comma-separated list of search domains or',
                   'sendline({})'.format(self.search_domains), None, True, False])
        d2.append(['Allow LCD Panel to configure network settings', 'sendline(n)', None, True, False])
        d2.append(['Choose Detection Mode', 'sendline({})'.format(self.detection_mode), None, True, False])
        d2.append(['> ', 'sendline()', None, False, False])

        # must reconnect here. cli_firstboot is started before everything is ready in the ssh case.
        self.reconnect_and_process_dialog(
            device_reconnect_count=device_reconnect_count1,
            wait_time=120,
            dialog_timeout=600,
            start_time=start_time,
            dialog_name='wait for new password',
            dialog=d2)

        logger.info('fully installed.')

    def validate_version(self):
        """Checks if the installed version matches the version in package
        url.

        :return: None

        """

        # check version
        response = self.execute('show version', 30)
        build = re.findall('Build\s(\d+)', response)[0]
        version = re.findall(r'(Version\s){1}([0-9.]+\d)', str(response))[0][1]
        if build in self.version_build and version in self.version_build:
            logger.info('>>>>>> show version result:\n{}\nmatches '
                        'ftd package image: {}'.format(response,
                                                       self.version_build))
            logger.info('Installed ftd version validated')
        else:
            logger.error('Exception: not the same version and build')
            raise RuntimeError('>>>>>> show version result:\n{}\ndoes not match '
                               'ftd package image: {}'.format(response,
                                                              self.version_build))

    def configure_manager(self):
        """Configure manager to be used for registration

        :return: None

        """

        # check version
        if self.manager_nat_id is None:
            response = self.execute('configure manager add {} {}'.format(self.manager,
                                                                         self.manager_key),
                                    120)
        else:
            response = self.execute('configure manager add {} {} {}'.format(self.manager,
                                                                            self.manager_key,
                                                                            self.manager_nat_id),
                                    120)
        matched_obj = re.search('Manager successfully configured.', response)
        if matched_obj is not None:
            logger.info('Configured FTD manager.')
        else:
            logger.error('Exception: configuration of manager failed')
            raise RuntimeError('>>>>>> configure manager result:\n{}\ndoes not match'.format(response))

    def series3_baseline(self, ftd, http_server, scp_server, scp_port,
                         scp_username, scp_password, scp_hostname,
                         version_build, iso_image_path,
                         uut_ip, uut_netmask, uut_gateway, dns_server,
                         hostname='firepower',
                         search_domains='cisco.com',
                         detection_mode='Inline',
                         http_dir_root='/var/www',
                         http_dir_tmp='iso/tmp_dev',
                         scp_dir_root='/nfs/netboot/ims/Release',
                         bz_image='bzImage*',
                         usb_image='usb-ramdisk*',
                         arch='x86_64',
                         uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                         console=False,
                         manager=None, manager_key=None, manager_nat_id=None,
                         timeout=None, http_port='80'):
        """Install FTD iso image on Series 3 Sensor device via http.

        :param ftd: object of Series3 for reconnecting the device
        :param http_server: HTTP Server IP Address, e.g. '10.89.23.80'
                            must use the same http server as the scp server
        :param http_port: HTTP server port, e.g. '80'
        :param scp_server: SCP Server IP Address, e.g. '10.89.23.80'
        :param scp_port: SCP Server Port, e.g. '22'
        :param scp_username: SCP Username
        :param scp_password: SCP Password
        :param scp_hostname: SCP Hostname
        :param version_build: e.g. '6.2.1-1366'
        :param iso_image_path: FTD image path on HTTP server
                                e.g. '/netboot/ims/Development/6.2.1-1366/iso/Sourcefire_3D_Device_S3-6.2.1-1366-Restore.iso'
        :param uut_ip: Device IP Address
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param hostname: hostname to be set, e.g. 'BATIT-3D8130-1-AST'
        :param search_domains: search domains delimited by comma,
                                defaulted to 'cisco.com'
        :param detection_mode: defaulted to 'Inline',
                                can be: 'Passive','Inline','Access Control','Network Discovery'
        :param http_dir_root: absolute path of the http root
                                e.g. '/var/www'
        :param http_dir_tmp: the temp dir under http_dir_root for version_build
                            and the config file, e.g. 'iso/tmp_dev'
        :param scp_dir_root: absolute path of the dir for version_build
                            e.g. '/nfs/netboot/ims/Release' or '/nfs/netboot/ims/Development'
        :param bz_image: bz image has to be installed on DUT, which is copied
                        from the scp_server, defaulted to 'bzImage*'
        :param usb_image: usb image has to be installed on DUT, which is copied
                            from the scp_server, defaulted to 'usb-ramdisk*'
        :param arch: arch type, defaulted to 'x86_64'
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param console: set to True if the device is accessed through its console;
                defaulted to False
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :return: None

        """
        publish_kick_metric('device.series3.baseline', 1)
        # set baseline timeout
        self.set_installation_timeouts(timeout)
        # Define attributes and variables
        self.ftd = ftd
        self.http_server = http_server
        self.http_port = http_port
        self.scp_server = scp_server
        self.scp_port = scp_port
        self.scp_username = scp_username
        self.scp_password = scp_password
        self.scp_hostname = scp_hostname
        self.version_build = version_build
        self.iso_image_path = iso_image_path
        self.iso_file = iso_image_path.split('/')[-1]
        self.uut_ip = uut_ip
        self.uut_netmask = uut_netmask
        self.uut_gateway = uut_gateway
        self.uut_ip6 = uut_ip6
        self.uut_prefix = uut_prefix
        self.uut_gateway6 = uut_gateway6
        self.dns_server = dns_server
        self.hostname = hostname
        self.search_domains = search_domains
        self.detection_mode = detection_mode
        self.http_dir_root = http_dir_root
        self.http_dir_tmp = http_dir_tmp
        self.http_dir_for_build = '{}/{}/{}'.format(self.http_dir_root,
                                                    self.http_dir_tmp, self.version_build)
        self.config_file = '{}.config'.format(self.iso_file.strip('.iso'))
        self.config_path = '{}/{}'.format(self.http_dir_for_build, self.config_file)
        self.config_file_url = '{}/{}/{}'.format(self.http_dir_tmp, self.version_build, self.config_file)
        self.scp_dir_root = scp_dir_root
        self.bz_image = bz_image
        self.usb_image = usb_image
        self.arch = arch
        self.bz_image_path = '{}/{}/os/{}/boot/{}'.format(self.scp_dir_root,
                                                          self.version_build,
                                                          self.arch, self.bz_image)
        self.usb_image_path = '{}/{}/os/{}/ramdisks/{}'.format(self.scp_dir_root,
                                                               self.version_build,
                                                               self.arch, self.usb_image)
        self.console = console

        self.manager = manager
        self.manager_key = manager_key
        self.manager_nat_id = manager_nat_id

        logger.info('=== Generate config file on the http server ...')
        self.generate_config_file()

        logger.info('=== Copy bz and usb files to dut ...')
        logger.info('=== Generate lilo file on dut ...')
        self.go_to('sudo_state')
        self.copy_bz_usb_files_setup_lilo_to_install()

        if not self.console:
            logger.info('=== Confirm device is rebooted ...')
            self.confirm_device_rebooted()
        else:
            logger.info('=== Console connection available, wait for login prompt ...')
            d = Dialog([
                ['login:', 'sendline({})'.format(self.sm.patterns.login_username),
                 None, False, False],
            ])
            d.process(self.spawn_id, timeout=self.installation_timeout)
            time.sleep(60)
            self.spawn_id.sendline('{}'.format(self.sm.patterns.default_password))

        logger.info('=== Wait for device to be up and configure device ...')
        self.poll_device_and_configure()

        self.go_to('any')

        if self.manager is not None:
            self.configure_manager()

        logger.info('=== Validate version installed ...')
        self.validate_version()

        logger.info('Installation completed successfully.')

    def baseline_by_branch_and_version(self, site, branch, version,
                                       uut_ip, uut_netmask, uut_gateway,
                                       dns_server, iso_file_type='Restore',
                                       serial_port=False, serverIp='', tftpPrefix='',
                                       scpPrefix='', docs='', pxeUsername='', pxePassword='',
                                       pxeHostname='', scpDirRoot='', httpDirRoot='', httpDirTmp='', **kwargs):
        """Baseline series3 sensor by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the local kick server
        and use them to baseline the device.

        :param site: e.g. 'ful', 'ast', 'bgl'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param uut_ip: Device IP Address
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param iso_file_type: 'Autotest' or 'Restore'; defaulted to 'Restore'
        :param serial_port: flag used to specify if baseline is done through
            physical serial port; defaulted to 'False'
        :param \**kwargs:
            :Keyword Arguments, any of below optional parameters:
        :param hostname: hostname to be set, e.g. 'BATIT-3D8130-1-AST'
        :param search_domains: search domains delimited by comma,
                                defaulted to 'cisco.com'
        :param detection_mode: defaulted to 'Inline',
                                can be: 'Passive','Inline','Access Control','Network Discovery'
        :param http_dir_root: absolute path of the http root
                                e.g. '/tftpboot/asa/'
        :param http_dir_tmp: the temp dir under http_dir_root for version_build
                            and the config file, e.g. '/cache/temp_config'
        :param scp_dir_root: absolute path of the dir for version_build
                            e.g. '/tftpboot/asa/cache/Release' or '/tftpboot/asa/cache/Development'
        :param bz_image: bz image has to be installed on DUT, which is copied
                        from the scp_server, defaulted to 'bzImage*'
        :param usb_image: usb image has to be installed on DUT, which is copied
                            from the scp_server, defaulted to 'usb-ramdisk*'
        :param arch: arch type, defaulted to 'x86_64'
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param console: set to True if the device is accessed through its console;
                defaulted to False
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :return: None

        """

        kwargs['uut_ip'] = uut_ip
        kwargs['uut_netmask'] = uut_netmask
        kwargs['uut_gateway'] = uut_gateway
        kwargs['dns_server'] = dns_server
        arch = kwargs.get('arch', 'x86_64')

        if KICK_EXTERNAL:
            server_ip = serverIp
            tftp_prefix = tftpPrefix
            scp_prefix = scpPrefix
            files = docs
        else:
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 's3', branch, version,
                                                                                   iso=iso_file_type, arch_type=arch)
        if not files[0]:
            raise Exception('Series3 iso file not found on server')

        if serial_port:
            iso_file = 'http://{}/{}/{}'.format(server_ip, tftp_prefix[len('asa'):], files[0])
            kwargs['iso_url'] = iso_file
            kwargs['hostname'] = kwargs.get('hostname', 'firepower')
            self.baseline_using_serial(**kwargs)
        else:
            iso_file_name = '{}/{}'.format(tftp_prefix[len('asa'):], files[0])
            kwargs['http_server'] = server_ip
            kwargs['scp_server'] = server_ip
            kwargs['scp_port'] = '22'
            if KICK_EXTERNAL:
                kwargs['scp_username'] = pxeUsername
                kwargs['scp_password'] = pxePassword
                kwargs['scp_hostname'] = pxeHostname
                kwargs['scp_dir_root'] = scpDirRoot
                kwargs['http_dir_root'] = httpDirRoot
                kwargs['http_dir_tmp'] = httpDirTmp
            else:
                kwargs['scp_username'] = pxe_username
                kwargs['scp_password'] = pxe_password
                kwargs['scp_hostname'] = pxe_hostname
                kwargs['scp_dir_root'] = kwargs.get('scp_dir_root',
                                                    '{}/{}'.format(pxe_dir['scp_dir_root'], branch))
                kwargs['http_dir_root'] = kwargs.get('http_dir_root', pxe_dir['http_dir_root'])
                kwargs['http_dir_tmp'] = kwargs.get('http_dir_tmp', pxe_dir['http_dir_tmp'])

            kwargs['iso_image_path'] = iso_file_name
            kwargs['version_build'] = version
            self.series3_baseline(**kwargs)

    def set_installation_timeouts(self, install_timeout=None, ssh_timeout=None):
        """Set the baseline timeout value for this device.

        :param install_timeout: in seconds, timeout for baseline procedure
        :param ssh_timeout: in seconds, timeout for ssh_vty connection
        :return: None
        """

        self.installation_timeout = install_timeout or MAX_TIME_INSTALL
        logger.info('setting baseline max timeout to {}'.format(self.installation_timeout))
        self.ssh_timeout = ssh_timeout or SSH_DEFAULT_TIMEOUT
        logger.info('setting ssh vty max timeout to {}'.format(self.ssh_timeout))

    def _try_to_goto_prompt(self, prompt, num_of_tries=10, raise_execption=True):
        """ Try to go to given prompt in given number of attempts

        :param prompt: Prompt
        :param num_of_tries: Number of attempts to go to given prompt
        :param raise_execption: Raise exception on failure

        :return: return 0 - success
                        1 - failure

        """

        for i in range(1, num_of_tries+1):
            try:
                self.go_to(prompt)
                break
            except:
                pass

        if i >= num_of_tries:
            msg = "Could not go to %s even after %s tries" % (prompt, num_of_tries)
            logger.error(msg)
            if raise_execption:
                raise RuntimeError(msg)

            return 1

        return 0

    def _move_from_lilo_boot_menu_to_lilo_os(self):
        """Go to LILO boot menu to lilo os """

        for i in range(0, 30):
            # Keep sending control+c till device moved to lilo os state
            self.spawn_id.send("\x03")
            try:
                self.spawn_id.expect("Please press Enter to activate this console", timeout=10)
                self.spawn_id.send("\r")
                self.spawn_id.expect(self.sm.patterns.prompt.lilo_os_prompt, timeout=10)
                break
            except:
                pass

        if i >= 30:
            msg = "Could not go to LILO OS prompt from LILO boot prompt"
            logger.error(msg)
            raise RuntimeError(msg)

    def power_cycle(self, power_bar_server, power_bar_port, power_bar_user='admn', power_bar_pwd='admn'):
        """Power cycle the device using power_bar

        :param power_bar_server: comma-separated string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string of power port on the PDU's
        :param power_bar_user: comma-separated string of usernames for power bar servers
        :param power_bar_pwd:  comma-separated string of passwords for power bar servers
        :return:
        """
        if power_bar_server == '' or power_bar_port == '':
            raise AssertionError("Cannot power cycle. powerbar server or powerbar port info missing")

        power_cycle_all_ports(power_bar_server, power_bar_port, power_bar_user, power_bar_pwd)

    def baseline_using_serial(self, iso_url, uut_ip, uut_netmask, uut_gateway, hostname,
                              dns_server='1.1.1.1', search_domains="example.net",
                              detection_mode="Inline", mgmt_intf="eth0", timeout=None, power_cycle_flag=False,
                              pdu_ip='', pdu_port='', pdu_user='admn', pdu_pwd='admn', **kwargs):
        """ Baseline S3 devices through Serial console.

        :param iso_url: HTTP URL for the image.
                    e.g., http://10.83.65.25/cache/Release/6.2.2-81/iso/Sourcefire_3D_Device_S3-6.2.2-81-Restore.iso
        :param uut_ip: Device IP Address
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param hostname: hostname to be set, e.g. 'BATIT-3D8130-1-AST'
        :param dns_server: DNS server
        :param search_domains: search domains delimited by comma,
                                defaulted to 'cisco.com'
        :param detection_mode: defaulted to 'Inline',
                                can be: 'Passive','Inline','Access Control','Network Discovery'
        :param mgmt_intf: Management Interface name (default: eth0)
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param power_cycle_flag: True power cylce before baseline, False otherwise
        :param pdu_ip: string of IP addresses of the PDU's
        :param pdu_port: string of power port on the PDU's
        :param pdu_user: usernames for power bar servers
        :param pdu_pwd: passwords for power bar servers
        :return: None

        """
        # set baseline timeout
        self.set_installation_timeouts(timeout)
        if power_cycle_flag:
            self.power_cycle(pdu_ip, pdu_port, pdu_user, pdu_pwd)
            d0 = Dialog([
                ['boot:', None, None, False, False],
            ])
            print(d0.process(self.spawn_id, timeout=600))

            self.spawn_id.send("\t")
            self.spawn_id.expect('boot:')
            self.spawn_id.send("\t")
            self.spawn_id.expect('boot:')

            self.spawn_id.send("Restore_Serial\r")
            self.spawn_id.expect(self.sm.patterns.prompt.lilo_boot_menu_prompt, timeout=120)

            self._move_from_lilo_boot_menu_to_lilo_os()
        else:
            self._try_to_goto_prompt(prompt='any')

            # TODO: Handle eula_prompt and firstboot_state if needed
            # TODO: Add mechanism to handle liloboot_state during login.
            #       It is tough to catch during login as newline or carriage return cause the system to boot.

            # Raise exception if device is not in below states
            baseline_valid_states = ["expert_state", "sudo_state", "prelogin_state", "lilos_state",
                                     "lilobootmenu_state", "fireos_state"]
            if self.sm.current_state not in baseline_valid_states:
                msg = "Baseline Serial function needs one of the valid state from %s" % baseline_valid_states
                logger.error(msg)
                raise RuntimeError(msg)

            # Go to fireos state if serial console is in having active FTD
            if self.sm.current_state in ["expert_state", "sudo_state", "prelogin_state"]:
                self._try_to_goto_prompt(prompt='fireos_state')

            # ---------------------------------------------
            # Bring the system to liloos_state if it is in fireos state
            # ---------------------------------------------
            if self.sm.current_state in ["lilobootmenu_state"]:
                self._move_from_lilo_boot_menu_to_lilo_os()

            elif self.sm.current_state in ["fireos_state"]:
                # term_conn.execute("system reboot", prompt="'YES' or 'NO'")
                # term_conn.spawn_id.sendline("YES")
                self.spawn_id.sendline("system reboot")

                d0 = Dialog([
                    ["This command will reboot the system.  Continue", None, None, True, False],
                    ["'YES' or 'NO':", "sendline(YES)", None, True, False],
                    ['reboot: machine restart', None, None, True, False],
                    ['boot:', None, None, False, False],
                ])

                print(d0.process(self.spawn_id, timeout=600))

                self.spawn_id.send("\t")
                self.spawn_id.expect('boot:')
                self.spawn_id.send("\t")
                self.spawn_id.expect('boot:')

                self.spawn_id.send("Restore_Serial\r")
                self.spawn_id.expect(self.sm.patterns.prompt.lilo_boot_menu_prompt, timeout=120)

                self._move_from_lilo_boot_menu_to_lilo_os()

        # Here means device is in LILO OS State
        self.sm.update_cur_state('lilos_state')

        # Try install seq with retry for 5 times
        for i in range(1, 5):
            ret = self._install_from_iso(iso_url=iso_url, uut_ip=uut_ip, uut_netmask=uut_netmask,
                                         uut_gateway=uut_gateway, mgmt_intf=mgmt_intf)

            if ret == 0:
                break

            # If the device moved back to lilo boot menu. Try to go to lilo os and try install again
            if ret == 1:
                self._move_from_lilo_boot_menu_to_lilo_os()

        # Raise error in all the attempts failed
        if i >= 5:
            msg = "Failed to install S3 using serial for %s times" % i
            logger.error(msg)
            raise RuntimeError(msg)

        time.sleep(60)

        # Perform Initialization
        for i in range(1, 4):
            try:
                self._initialize_dev_after_baseline(uut_ip=uut_ip, uut_netmask=uut_netmask,
                                                    uut_gateway=uut_gateway, dns_server=dns_server,
                                                    hostname=hostname, search_domains=search_domains,
                                                    detection_mode=detection_mode, dhcp=False)
                break
            except:
                logger.error("Failed to perform system initialization")
                raise RuntimeError("Failed to perform system initialization")

    def _install_from_iso(self, iso_url, uut_ip, uut_netmask, uut_gateway, mgmt_intf="eth0", usb_loc="/dev/sdb1"):
        """ Install image from given ISO

        :param iso_url: ISO URL
        :param uut_ip:  Device IP
        :param uut_netmask: Device netmask
        :param uut_gateway: Devcie Gateway
        :param mgmt_intf: Management Interface name (default: eth0)
        :param usb_loc: USB location in devcie (default: /dev/sdb1)
        :return: None

        """

        p = self.sm.patterns.prompt.lilo_os_prompt

        self.spawn_id.sendline("")
        self.spawn_id.expect(self.sm.patterns.prompt.lilo_os_prompt)

        self.execute("mount %s /mnt/usb" % usb_loc)
        self.execute("/sbin/ifconfig %s %s netmask %s" % (mgmt_intf, uut_ip, uut_netmask))
        self.execute("route add default gw %s" % uut_gateway)

        # Get ISO name, path and server ip from URL path
        url_data = urllib.parse.urlparse(iso_url)
        install_srv = url_data.netloc
        iso_name = os.path.basename(url_data.path)
        iso_path = os.path.dirname(url_data.path)[1:]

        self.execute("""echo "SRV=%s
        dirpath=%s
        TRANS=httpsvr
        choicedevice=%s
        IPCONF=dhcp
        IPFAM=ipv4
        choiceiso=%s
        " > /mnt/usb/configs/default_config.conf""" % (install_srv, iso_path, mgmt_intf, iso_name))

        self.execute("cat /mnt/usb/configs/default_config.conf")

        self.execute("umount /cdrom  2> /dev/null")
        self.execute("rm -f /mnt/tmpfs/*")
        self.execute("umount /mnt/tmpfs 2> /dev/null")
        self.execute("umount /mnt/hd/ 2> /dev/null")
        self.execute("umount /mnt/usb 2> /dev/null")

        self.execute("/etc/rc.d/install.sh --partition-only", timeout=240)

        # Download image into /mnt/var and initiate installation
        self.execute("cd /mnt/var/")

        for i in range(1, 11):
            try:
                d1 = Dialog([
                    ['The file is already fully retrieved; nothing to do.', None, None, False, False],
                    ["'%s' saved" % iso_name, None, None, False, False],
                ])
                self.spawn_id.sendline("wget -c %s" % iso_url)
                d1.process(self.spawn_id, timeout=300)
                break
            except:
                pass

        if i >= 10:
            msg = "Failed to down load %s in 10 attempts with timeout 5 mins" % "wget -c %s" % iso_url
            logger.error(msg)
            raise RuntimeError(msg)

        self.execute("mount -t iso9660 -o loop /mnt/var/%s /cdrom" % iso_name, timeout=90)

        # Install steps
        self.execute("umount /mnt/usb &> /dev/null")

        self.spawn_id.sendline("/cdrom/install/menu.sh")

        d0 = Dialog([
            ["The system will restart after you press enter.", 'sendline()', None, True, False],
            ['Restore the system.*yes/no.*:', 'sendline(yes)', None, True, False],
            ['Delete license and network settings.*yes/no.*:', 'sendline(no)', None, True, False],
            ['Are you sure.*yes/no.*:', 'sendline(yes)', None, True, False],
            [p, None, None, False, False],
            [self.sm.patterns.prompt.lilo_boot_menu_prompt, None, None, False, False],
        ])
        res = d0.process(self.spawn_id, timeout=600)
        print(dir(res))

        if self.sm.patterns.prompt.lilo_boot_menu_prompt in res.match_output:
            logger.info("Device moved back to lilo boot menu")
            return 1

        if "root@(none)" in res.match_output:
            self.execute("umount /cdrom")
            self.execute("losetup -d /dev/loop0")
            self.execute("rm -rf /mnt/var/*.iso")

            # Reboot system to complete install process
            self.spawn_id.sendline("reboot")
            d0 = Dialog([
                ["firepower login:", None, None, False, False],
                [self.sm.patterns.prompt.prelogin_prompt, None, None, False, False],
                [self.sm.patterns.prompt.lilo_boot_menu_prompt, None, None, False, False],
            ])
            res = d0.process(self.spawn_id, timeout=self.installation_timeout)

            if self.sm.patterns.prompt.lilo_boot_menu_prompt in res.match_output:
                logger.info("Device moved back to lilo boot menu")
                return 1
            elif 'login:' in res.match_output:
                print("Install is done and got firepower login: prompt")
                logger.info("Install is done and got firepower login: prompt")
                self.sm.update_cur_state('prelogin_state')
                return 0

        logger.error("Unknown state. It should be never be here")

        return 2

    def _initialize_dev_after_baseline(self, dhcp=True, uut_ip=None, uut_netmask=None, uut_gateway=None,
                                       dns_server='1.1.1.1', hostname=None, search_domains="example.net",
                                       detection_mode="Inline"):
        """ Perform System Initialization after installation.

        :param dhcp: Is IP from DHCP. True- from dhcp, False - manual
        :param uut_ip: Device IP Address
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param hostname: hostname to be set, e.g. 'BATIT-3D8130-1-AST'
        :param search_domains: search domains delimited by comma,
                                defaulted to 'cisco.com'
        :param detection_mode: defaulted to 'Inline',
                                can be: 'Passive','Inline','Access Control','Network Discovery'
        :param mgmt_intf: Management Interface name (default: eth0)
        :return: None

        """

        # TODO: Handling IPv6 address configuration

        # Perform Initialization
        self.spawn_id.sendline("")

        d2 = Dialog([
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, True, False],
        ])
        d2.append(['--More--', 'send(q)', None, True, False])
        d2.append(["Please.*enter.*YES.*AGREE.*EULA:", 'sendline(YES)', None, True, False])
        d2.append(["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ", 'sendline(YES)', None, True, False])
        d2.append(['Enter new password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, True])
        d2.append(['Confirm new password:', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False])

        d2.append(['Do you want to configure IPv4', 'sendline(y)', None, True, False])
        d2.append(['Do you want to configure IPv6', 'sendline(n)', None, True, False])

        if dhcp:
            d2.append(['Configure IPv4 via DHCP or manually', 'sendline(dhcp)', None, True, False])
        else:
            d2.append(['Configure IPv4 via DHCP or manually', 'sendline(manual)', None, True, False])

            d2.append(['Enter an IPv4 address for the management interface', 'sendline({})'.format(uut_ip),
                       None, True, False])
            d2.append(['Enter an IPv4 netmask for the management interface', 'sendline({})'.format(uut_netmask),
                       None, True, False])
            d2.append(['Enter the IPv4 default gateway for the management interface', 'sendline({})'.format(uut_gateway),
                       None, True, False])
            d2.append(['Enter a fully qualified hostname for this system ', 'sendline({})'.format(hostname),
                       None, True, False])
            d2.append(['Enter a comma-separated list of DNS servers or', 'sendline({})'.format(dns_server),
                       None, True, False])
            d2.append(['Enter a comma-separated list of search domains or', 'sendline({})'.format(search_domains),
                       None, True, False])

        d2.append(['Allow LCD Panel to configure network settings', 'sendline(n)', None, True, False])
        d2.append(['Choose Detection Mode', 'sendline({})'.format(detection_mode), None, False, False])
        d2.append(['firepower login:', "sendline({})".format(self.sm.patterns.username), None, True, False])
        d2.append(['{} login:'.format(hostname), "sendline({})".format(self.sm.patterns.username), None, True, False])
        d2.append(['[P|p]assword:', "sendline({})".format(self.sm.patterns.default_password), None, True, False])

        res = d2.process(self.spawn_id, timeout=720)

        time.sleep(20)
        self.spawn_id.sendline("")
        self.spawn_id.expect(">", timeout=300)

    def replace_asa_image(self, source_location, pwd, timeout=300):
        """ Not implemented for Series3Line class"""

        raise NotImplementedError

