import datetime
import logging
import os.path
import re
import time
import urllib

from unicon.eal.dialogs import Dialog

from kick.device2.general.actions.power_bar import power_cycle_all_ports
from .patterns import FmcPatterns
from .statemachine import FmcStatemachine
from ...general.actions.basic import BasicDevice, BasicLine

try:
    from kick.kick_constants import KickConsts
except ImportError:
    from kick.miscellaneous.credentials import KickConsts

try:
    import kick.graphite.graphite as graphite
except ImportError:
    import kick.metrics.metrics as graphite

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10
MAX_RETRY_COUNT = 3


class Fmc(BasicDevice):
    def __init__(self, hostname='firepower',
                 login_username='admin',
                 login_password=KickConsts.DEFAULT_PASSWORD,
                 sudo_password=KickConsts.DEFAULT_PASSWORD,
                 *args,
                 **kwargs):
        """Constructor for FMC.

        :param hostname: fmc hostname or fqdn e.g. FS2000-01 or FS2000-01.domain.com
        :param login_username: user name for login
        :param login_password: password for login
        :param fmc_root_password: root password for FMC
        :return: None

        Add *args and **kwargs so that the initiator can be invoked with
        additional (unused) arguments.

        """

        super().__init__()
        graphite.publish_kick_metric('device.fmc.init', 1)
        self.patterns = FmcPatterns(
            hostname=hostname,
            login_username=login_username,
            login_password=login_password,
            sudo_password=sudo_password)
        self.sm = FmcStatemachine(self.patterns)
        self.line_class = FmcLine

    def log_checks(self, fmc_line, list_files=['/var/log/boot_*'],
                   search_strings=['fatal', 'error'], exclude_strings=[], timeout=300):
        """Wrapper function to Get logs for FMC.

        :param fmc_line: Instance of fmc line used to connect to FMC
        :param list_files: List of file paths for files to search in
        :param search_strings: List of keywords to be searched in the logs
        :param exclude_strings: List of keywords to be excluded in the logs
        :param timeout: The number for seconds to wait for log retrieval
        
        e.g list_files = ['/var/log/boot_1341232','/var/log/boot_*']
            search_strings = ['fatal','error', 'crash']
            exclude_strings = ['ssl_flow_errors', 'firstboot.S09']

        """

        self.sm.go_to('sudo_state', fmc_line.spawn_id, timeout=30)

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
        try:
            output_log = fmc_line.execute_lines(("\n".join(grep_command_list)), timeout=timeout)
        except:
            output_log = "Log retrieval command timed out"

        logger.info("""
            ***********************************************************

            Logs for the requested files in FMC are : -

            {}

            ***********************************************************
            """.format(output_log))

    def define_contexts(self, contexts=None):
        raise NotImplementedError

    def ssh_vty(self, ip, port, username='admin', password=KickConsts.DEFAULT_PASSWORD,
                timeout=None, line_type='ssh_vty', rsa_key=None):
        return super().ssh_vty(ip, port, username=username, password=password,
                               timeout=timeout, line_type=line_type, rsa_key=rsa_key)


class FmcLine(BasicLine):
    def __init__(self, spawn, sm, type, timeout=None):
        """ Constructor of FmcLine

        :param spawn: spawn_id of the line
        :param sm: object of statemachine
        :param type: line type, e.g. 'ssh', 'telnet'
        :return: object of the line

        """

        try:
            super().__init__(spawn, sm, type, timeout)
        except:
            if self.type in ['ssh_vty', 'ssh_cimc']:
                raise
            # keep the FmcLine 'alive' in case the power cycle function is used
            # in order to start a baseline
            logger.info("=== Device was accessed via console port")
            logger.info("=== Failed to go to a known state. Though we keep the FmcLine "
                        "'alive' in case the power cycle function is used")

    def expert_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """Run a command as 'admin' and return its output

        :param cmd: command to be executed as 'admin' given as a string
        :param timeout: in seconds; how long to wait for command output
        :param exception_on_bad_command: True/False - whether to raise an exception
                on a bad command
        :return: output as a string

        """

        self.go_to('admin_state')
        return self.execute(cmd, timeout, exception_on_bad_command)

    def changeto_context(self, ctx, timeout=60):
        """ Not implemented for FmcLine class"""

        raise NotImplementedError

    def find_matched_str(self,
                         expected_str,
                         return_data,
                         matched_whole_line=False):
        """Find matched line or substring from return_data.

        :param expected_str: expected string for the output of cmd executed
        :param return_data: command output
        :param matched_whole_line: True if want to match the whole line, otherwise, match the substring
        :return: matched_obj

        """

        matched_obj = False
        if matched_whole_line:
            for line in return_data.split('\n'):
                line = line.strip()
                if line == '':
                    continue
                logger.debug('line=' + line)
                if line == expected_str:
                    matched_obj = line
                    break
        else:
            matched_obj = re.search(expected_str, return_data)
        return matched_obj

    def execute_and_verify(self, cmd,
                           expected_str,
                           cmd_set_config='',
                           timeout=60,
                           interval=2,
                           timeout_total=60,
                           retry_count=MAX_RETRY_COUNT,
                           matched_whole_line=False):
        """Execute a command, verify the output.

        set the config if the output is not expected,
        The command will be run and retried for no more than retry_count,
        and no more than timeout_total in seconds
        Assert if expected_str is not found in the output of cmd

        :param cmd: command to be executed
        :param expected_str: expected string for the output of cmd executed
        :param cmd_set_config: command to be executed if expected_str is not seen, if cmd_set_config is an empty string,
                                the function is waiting only
        :param timeout: timeout for execute() in seconds
        :param interval: wait time for each retry in seconds
        :param timeout_total: total wait time in seconds
        :param retry_count: Max count for retries
        :param matched_whole_line: True if want to match the whole line
        :return: None

        """

        logger.info("""Command: {}
            Expected String: {}
            Command to set configuration: {}
        """.format(cmd, expected_str, cmd_set_config))
        count = 0
        expected = False
        start_time = datetime.datetime.now()
        elapsed_time = 0
        while count < retry_count and elapsed_time < timeout_total:
            return_data = self.execute(cmd, timeout=timeout)
            matched_obj = self.find_matched_str(expected_str, return_data,
                                                matched_whole_line)
            if matched_obj is None:
                if cmd_set_config is not '':
                    # Execute the command to get expected_str
                    self.execute(cmd_set_config, timeout=timeout)
                    self.execute('commit', timeout=timeout)
                count += 1
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
                time.sleep(interval)
            else:
                expected = True
                break
        assert expected, "Command: {}, Expected String: {} " \
                         "not found".format(cmd, expected_str)

    def validate_mysql_process(self):
        """ Validate mysql process"""

        self.go_to('admin_state')
        self.execute_and_verify(cmd='ps -ef | grep mysql | grep -v grep',
                                expected_str='mysqld',
                                timeout=120,
                                interval=5,
                                timeout_total=300,
                                retry_count=60)
        self.execute_and_verify(cmd='ls /var/run/mysql/',
                                expected_str='mysql\.sock',
                                timeout=120,
                                interval=5,
                                timeout_total=300,
                                retry_count=60)
        self.execute_and_verify(cmd='ls /var/run/mysql/',
                                expected_str='mysqld\.pid',
                                timeout=120,
                                interval=5,
                                timeout_total=300,
                                retry_count=60)

    def configure_network(self, mgmt_gateway, mgmt_ip, mgmt_netmask,
                          mgmt_ip6=None, mgmt_prefix=None, mgmt_gateway6=None,
                          change_password=True):
        """
        Configure the network setting of the management interface

        :param mgmt_ip: management interface ip address
        :param mgmt_netmask: management interface netmask
        :param mgmt_gateway: management interface gateway
        :param mgmt_ip6: management interface IPv6 Address
        :param mgmt_prefix: management interface IPv6 Prefix
        :param mgmt_gateway6: management interface IPv6 Gateway
        :param change_password: Flag to change the password after baseline
        :return:
        """
        #Configure network
        try:
            self.spawn_id.sendline('expert')
        except:
            pass
        self.spawn_id.sendline('sudo su -')
        self.spawn_id.expect("Password: ", 10)
        self.spawn_id.sendline(self.sm.patterns.default_password)
        self.go_to('any')
        self.spawn_id.sendline('configure-network')
        d5 = Dialog([
            ['Do you wish to configure IPv4', 'sendline({})'.format('y'),
             None, True, False],
            ['Management IP address', 'sendline({})'.format(mgmt_ip),
             None, True, False],
            ['Management netmask', 'sendline({})'.format(mgmt_netmask),
             None, True, False],
            ['Management default gateway', 'sendline({})'.format(mgmt_gateway),
             None, False, False],
        ])
        d5.process(self.spawn_id, timeout=180)
        d6 = Dialog([
            ['Are these settings correct', 'sendline({})'.format('y'),
             None, False, False],
        ])
        d6.process(self.spawn_id, timeout=180)
        if mgmt_ip6 is None:
            d7 = Dialog([
                ['Do you wish to configure IPv6', 'sendline({})'.format('n'),
                 None, True, False],
                [self.sm.get_state('sudo_state').pattern, None, None, False, False],
            ])
            d7.process(self.spawn_id, timeout=300)
        else:
            d7 = Dialog([
                ['Do you wish to configure IPv6', 'sendline({})'.format('y'),
                 None, True, False],
                ['Do you wish to router autoconfiguration', 'sendline({})'.format('n'),
                 None, True, False],
                ['Management IP address', 'sendline({})'.format(mgmt_ip6),
                 None, True, False],
                ['Management prefix', 'sendline({})'.format(mgmt_prefix),
                 None, True, False],
                ['Management default gateway', 'sendline({})'.format(mgmt_gateway6),
                 None, False, False],
            ])
            d7.process(self.spawn_id, timeout=180)
            d8 = Dialog([
                ['Are these settings correct', 'sendline({})'.format('y'),
                 None, True, False],
                [self.sm.get_state('sudo_state').pattern, None, None, False, False],
            ])
            d8.process(self.spawn_id, timeout=300)

        self.execute_and_verify(cmd='ifconfig',
                                expected_str=mgmt_ip)
        if mgmt_ip6 is not None:
            self.execute_and_verify(cmd='ifconfig',
                                    expected_str=mgmt_ip6)

        if change_password:
            logger.info('=== Changing default password')
            self.spawn_id.sendline('passwd {}'.format(self.sm.patterns.username))
            d9 = Dialog([
                ['New UNIX password', 'sendline({})'.format(self.sm.patterns.login_password),
                 None, True, False],
                ['Retype new UNIX password', 'sendline({})'.format(self.sm.patterns.login_password),
                 None, True, False],
                ['passwd: password updated successfully', None, None, False, False],
            ])
            try:
                d9.process(self.spawn_id, timeout=120)
            except TimeoutError:
                logger.error('Changing password for {} user has failed'.format(self.sm.patterns.username))
                raise Exception('Error while changing default password for {} user'.format(self.sm.patterns.username))

    def validate_version(self, iso_file_name,private_iso=False):
        """Checks if the installed version matches the version from iso filename.
        Make sure you are in 'sudo_state' before calling this method.

        :param iso_file_name: iso filename under http_link,
               e.g. 'Sourcefire_Defense_Center_M4-6.2.0-362-Autotest.iso'
        :param private_iso: Flag to validate version for private iso
        :return: None

        """

        self.go_to('sudo_state')
        version = self.execute('cat /etc/sf/ims.conf | egrep "SWVERSION"', 30)
        build = self.execute('cat /etc/sf/ims.conf | egrep "SWBUILD"', 30)
        # extract version and build from iso file name
        if private_iso:
            expected_version = re.search('[\d.]+', iso_file_name.split('-')[-2]).group(0)
            expected_build = re.search('\d+', iso_file_name.split('-')[-1]).group(0)
        else:
            expected_version = re.search('[\d.]+', iso_file_name.split('-')[-3]).group(0)
            expected_build = re.search('\d+', iso_file_name.split('-')[-2]).group(0)

        if version.split('=')[1] == expected_version and build.split('=')[1] == expected_build:
            logger.info('>>>>>> Version {}, Build {} match {} {}'.format(version.split('=')[1],
                                                                         build.split('=')[1],
                                                                         expected_version,
                                                                         expected_build))
            logger.info('Installed FMC version validated')
            return True
        else:
            logger.error('Exception: not the same version and build')
            raise RuntimeError(
                '>>>>>> Version {}, Build {} does not match {} {}'.format(version.split('=')[1],
                                                                          build.split('=')[1],
                                                                          expected_version,
                                                                          expected_build))

    def power_cycle(self, power_bar_server, power_bar_port, power_bar_user='admn', power_bar_pwd='admn'):
        """Power cycle the device using power_bar

        :param power_bar_server: comma-separated string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string of power ports on the PDU's
        :param power_bar_user: comma-separated string of usernames for power bar servers
        :param power_bar_pwd:  comma-separated string of passwords for power bar servers
        :return:
        """
        if power_bar_server == '' or power_bar_port == '':
            raise AssertionError("Cannot power cycle. powerbar server or powerbar port info missing")

        power_cycle_all_ports(power_bar_server, power_bar_port, power_bar_user, power_bar_pwd)

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

    def _try_to_goto_prompt(self, prompt, num_of_tries=10, raise_exception=True):
        """ Try to go to given prompt in given number of attempts

        :param prompt: Prompt
        :param num_of_tries: Number of attempts to go to given prompt
        :param raise_exception: Raise exception on failure

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
            if raise_exception:
                raise RuntimeError(msg)

            return 1

        return 0

    def _install_from_iso(self, iso_url, uut_ip, uut_netmask, uut_gateway, mgmt_intf="eth0",
                          usb_loc="/dev/sdb1", timeout=7200):
        """ Install image from given ISO

        :param iso_url: ISO URL
        :param uut_ip:  Device IP
        :param uut_netmask: Device netmask
        :param uut_gateway: Devcie Gateway
        :param mgmt_intf: Management Interface name (default: eth0)
        :param usb_loc: USB location in devcie (default: /dev/sdb1)
        :return: None

        """

        lilo_os_prompt = self.sm.patterns.prompt.lilo_os_prompt

        self.spawn_id.sendline("")
        self.spawn_id.expect(self.sm.patterns.prompt.lilo_os_prompt)

        self.execute("umount /mnt/usb")
        output = self.execute("mount %s /mnt/usb" % usb_loc)
        if '%s is already mounted' % usb_loc in output:
            logger.error("Failed mounting {} on /mnt/usb".format(usb_loc))
            raise RuntimeError("Failed mounting {} on /mnt/usb".format(usb_loc))
        self.execute("/sbin/ifconfig %s %s netmask %s" % (mgmt_intf, uut_ip, uut_netmask))
        self.execute("route add default gw %s" % uut_gateway)

        # Get ISO name, path and server ip from URL path
        url_data = urllib.parse.urlparse(iso_url)
        install_srv = url_data.netloc
        iso_name = os.path.basename(url_data.path)
        iso_path = os.path.dirname(url_data.path)[1:]
        
        self.execute("mkdir /mnt/usb/configs")
        self.execute("""echo "SRV=%s
        dirpath=%s
        TRANS=httpsvr
        choicedevice=%s
        IPCONF=dhcp
        IPFAM=ipv4
        choiceiso=%s
        " > /mnt/usb/configs/default_config.conf""" % (install_srv, iso_path, mgmt_intf, iso_name))

        config_output = self.execute("cat /mnt/usb/configs/default_config.conf")
        if 'No such file or directory' in config_output:
            logger.error('Failed creating default_config file')
            raise RuntimeError('Failed creating default_config file')

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
                self.spawn_id.sendline("wget --no-check-certificate -c %s" % iso_url)
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

        # wait for menu.sh script to be launched
        d = Dialog([
            ['This might take some time', None, None, False, False],
            # needed for older builds (6.1.0)
            ['All data will be destroyed', None, None, False, False],
            # needed for older builds (6.0.0)
            ['The USB device was successfully imaged', None, None, False, False],
        ])
        try:
            d.process(self.spawn_id, timeout=60)
        except Exception as e:
            logger.info("menu script has not started after 1 min. It failed with {}".format(e))
            raise Exception("menu.sh script has not started after 1 min")

        d0 = Dialog([
            ["The system will restart after you press enter.", 'sendline()', None, True, False],
            ['Restore the system.*yes/no.*:', 'sendline(yes)', None, True, False],
            ['Delete license and network settings.*yes/no.*:', 'sendline(no)', None, True, False],
            ['Are you sure.*yes/no.*:', 'sendline(yes)', None, True, False],
            [lilo_os_prompt, None, None, False, False],
            [self.sm.patterns.prompt.lilo_boot_menu_prompt, None, None, False, False],
        ])
        res = d0.process(self.spawn_id, timeout=600)

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
                [self.sm.patterns.prompt.lilo_boot_menu_prompt, None, None, False, False],
                # needed for M3 to redirect the output to the console
                ['\nboot:', 'sendline({})'.format('1'), None, True, False],
                ['.*login:', 'sendline({})'.format(self.sm.patterns.username), None, True, False],
                ['Password:', 'sendline({})'.format(self.sm.patterns.default_password), None, False, False]
            ])
            res = d0.process(self.spawn_id, timeout=timeout)

            if self.sm.patterns.prompt.lilo_boot_menu_prompt in res.match_output:
                logger.info("Device moved back to lilo boot menu")
                return 1
            elif 'Password:' in res.match_output:
                logger.info("Install is done and got firepower login: prompt")
                self._first_login()
                return 0

        logger.error("Unknown state. It should never be here")

        return 2

    def replace_asa_image(self, source_location, pwd, timeout=300):
        """ Not implemented for FmcLine class"""

        raise NotImplementedError

    def _first_login(self):

        d0 = Dialog([
            ['\(current\) UNIX password', 'sendline({})'.format(self.sm.patterns.default_password), None, True, False],
            ['New UNIX password', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
            ['Retype new UNIX password', 'sendline({})'.format(self.sm.patterns.login_password), None, False, False],
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, True, False],
            ['--More--', 'send(\x20)', None, True, False],
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ", 'sendline()', None, False, False],
                ])

        accept_eula_dialog = Dialog([
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, True, False],
            ['--More--', 'send(\x20)', None, True, False],
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ", 'sendline()', None, False, False],
            ['Enter new password', 'sendline({})'.format(self.sm.patterns.login_password), None, True, False],
            ['Confirm new password', 'sendline({})'.format(self.sm.patterns.login_password), None, False, False],
        ])
        try:
            d0.process(self.spawn_id, timeout=90)
            try:
                accept_eula_dialog.process(self.spawn_id, timeout=90)
            except TimeoutError:
                logger.info("=== EULA was not displayed")
            logger.info("=== Successfully completed the first login for fmc")
        except TimeoutError:
            logger.warning('Changing password for {} user was not required at this step'.
                           format(self.sm.patterns.login_username))
            self.spawn_id.sendline()

    def configuration_wizard(self, ipv4_mode, ipv6_mode, ipv4, ipv4_netmask, ipv4_gateway,
                             ipv6, ipv6_prefix, ipv6_gateway, dns_servers, search_domains,
                             ntp_servers):
        """ Handle FMC configuration wizard

        :param ipv4_mode: IPv4 configuration mode - 'static' ('manual') or 'dhcp'
        :param ipv4: IPv4 address of the management interface
        :param ipv4_netmask: IPv4 netmask of the management interface
        :param ipv4_gateway: IPv4 gateway of the management interface
        :param ipv6: IPv6 address of the management interface
        :param ipv6_prefix: IPv6 prefix of the management interface
        :param ipv6_gateway: IPv6 gateway of the management interface
        :param ipv6_mode: IPv6 configuration mode - 'dhcp', 'router' or 'manual'
        :param dns_servers: a comma-separated string of DNS servers
        :param search_domains: a comma-separated string of search domains
        :param ntp_servers: a comma-separated string of NTP servers
        :return: True if network configuration was done, False otherwise
        """
        if ipv4_mode in ["static", "manual"]:
            ipv4_mode_new = "manual"
            ipv4_mode_old = "static"
        else:
            ipv4_mode_old = "dhcp"
            ipv4_mode_new = "dhcp"

        config_dialog = Dialog([
            [self.sm.patterns.prompt.fireos_prompt, 'sendline()', None, False, False],
            [self.sm.patterns.prompt.admin_prompt, 'sendline()', None, False, False],
            [self.sm.patterns.prompt.sudo_prompt, 'sendline()', None, False, False],
            ['Enter a hostname or fully qualified domain name for this system ',
             'sendline({})'.format(self.sm.patterns.fqdn), None, True, False],
            ['Enter a fully qualified hostname for this system ',
             'sendline({})'.format(self.sm.patterns.fqdn), None, True, False],
            ['Configure IPv4 via DHCP or manually', 'sendline({})'.format(ipv4_mode_new),
             None, True, False],
            ['Configure IPv4 via DHCP or static configuration', 'sendline({})'.format(ipv4_mode_old),
             None, True, False],
        ])

        if ipv4_mode is 'static':
            config_dialog.append(['Enter an IPv4 address for the management interface',
                                  'sendline({})'.format(ipv4), None, True, False])
            config_dialog.append(['Enter an IPv4 netmask for the management interface',
                                  'sendline({})'.format(ipv4_netmask), None, True, False])
            config_dialog.append(['Enter the IPv4 default gateway for the management interface',
                                  'sendline({})'.format(ipv4_gateway), None, True, False])

        if ipv6_mode:
            config_dialog.append(['Do you want to configure IPv6', 'sendline(y)', None, True, True])
            config_dialog.append(['Configure IPv6 via DHCP, router, or manually', 'sendline({})'.format(ipv6_mode), None, True, True])
        else:
            config_dialog.append(['Do you want to configure IPv6', 'sendline(n)', None, True, True])

        if ipv6_mode is 'manual':
            config_dialog.append(['Enter the IPv6 address for the management interface',
                                  'sendline({})'.format(ipv6), None, True, False])
            config_dialog.append(['Enter the IPv6 address prefix for the management interface',
                                  'sendline({})'.format(ipv6_prefix), None, True, False])
            config_dialog.append(['Enter the IPv6 gateway for the management interface',
                                  'sendline({})'.format(ipv6_gateway), None, True, False])

        config_dialog.append(['Enter a comma-separated list of DNS servers', 'sendline({})'.format(dns_servers),
                              None, True, False])
        config_dialog.append(['Enter a comma-separated list of search domains', 'sendline({})'.format(search_domains),
                              None, True, False])
        config_dialog.append(['Enter a comma-separated list of NTP servers', 'sendline({})'.format(ntp_servers),
                              None, True, False])
        config_dialog.append(['Are these settings correct', 'sendline(y)', None, True, False])
        config_dialog.append(['Updated network configuration', None, None, True, False])

        response = config_dialog.process(self.spawn_id, timeout=900)

        self.spawn_id.sendline()
        self.go_to('any')

        if 'Updated network configuration' in response.match_output:
            logger.info("Network configuration completed")
            return True

        return False
