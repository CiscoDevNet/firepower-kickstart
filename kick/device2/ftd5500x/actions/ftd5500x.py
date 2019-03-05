"""Library to load new image on a FTD 5500x. The applies to the Kenton
platforms (5506, 5508, 5516), Saleen platforms (5512, 5525, 5545, 5555).

We require a file server to be co-located with the device. This file
server has both the rommon_image (lfbff for Kenton, and cdisk for Saleen)
and the pkg_image mounted. FTD will first break into rommon, tftp the
rommon_image and boot from it into FTD boot CLI. Then it will do an HTTP
copy of pkg_image to boot up into a fully functional device. This second
step takes a long time (~30 min), as it will run a lot of scripts.

The file server is a PXE server in each site, defined in gcp_constants.py.

"""
import logging
import os.path
import re
import time

from kick.miscellaneous.credentials import *

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True

logger = logging.getLogger(__name__)

from unicon.eal.expect import TimeoutError
from unicon.eal.dialogs import Dialog
from unicon.eal.utils import ExpectMatch
from pathlib import PurePosixPath
from ...general.actions.basic import BasicDevice, BasicLine
from kick.device2.general.actions.power_bar import power_cycle_all_ports

try:
    import kick.graphite.graphite as graphite
except ImportError:
    import kick.metrics.metrics as graphite

MAX_RETRY_COUNT = 3
DEFAULT = 'DEFAULT'
EN_PASSWORD = 'en_password'
DEFAULT_ENPASSWORD = 'myenpassword'

class Ftd5500x(BasicDevice):
    def __init__(self, hostname='firepower', login_password='Admin123',
                 sudo_password='Admin123', enable_password='', *args, **kwargs):
        """Constructor for FTD.

        Add *args and **kwargs so that the initiator can be invoked with
        additional (unused) arguments.

        :param hostname: host name as appears in prompt
                e.g. 'BATIT-5508-3-FUL'
        :param login_password: password for login
        :param sudo_password: root password
        :param enable_password: password for privileged exec mode
        :return: None

        """

        super().__init__()

        graphite.publish_kick_metric('device.ftd5500x.init', 1)
        from .patterns import Ftd5500xPatterns
        self.patterns = Ftd5500xPatterns(hostname, login_password, sudo_password, enable_password)

        # create the state machine that contains the proper attributes.
        from .statemachine import Ftd5500xStatemachine
        self.sm = Ftd5500xStatemachine(self.patterns)

        # important: set self.line_class so that a proper line can be created
        # by ssh_console(), etc.
        self.line_class = Ftd5500xLine

    def clear_line(self, line, port, en_password=DEFAULT_ENPASSWORD):
        """Function to clear line.

        :param line: spawn ID for the line of terminal server connection
        :param port: device line port in terminal server to be cleared
        :param en_password: enable password to switch to line configuration mode
        :return: None

        """
        if en_password == DEFAULT_ENPASSWORD:
            en_password = get_password(en_password)

        try:
            line.spawn_id.expect('#')
        except:
            # expect >
            line.spawn_id.sendline('en')
            try:
                line.spawn_id.expect('Password:')
                line.spawn_id.sendline(en_password)
            except:
                pass
        #port = port[-2:]
        #if port[-2] is '0':
        #    port = port[-1]
        line.spawn_id.sendline('clear line {}'.format(port))
        line.spawn_id.expect('[confirm]')
        line.spawn_id.sendline('')
        line.spawn_id.expect('[OK]')
        logger.info('line: {} cleared'.format(port))

    def check_version(self, ftd_line, version, build):
        """Checks if the installed version matches a certain version.

        :param ftd_line: Instance of FTD line used to connect to FTD
        :param version: version to be checked
        :param build: build to be checked
        :return: None

        """
        # ftd_line = self.telnet_console_with_credential(ip, port)
        ftd_line.go_to('any')
        ftd_line.go_to('fireos_state')

        # check version
        response = ftd_line.execute('show version', 30)
        current_build = re.findall('Build\s(\d+)', response)[0]
        current_version = re.findall(r'(Version\s){1}([0-9.]+\d)', str(response))[0][1]
        if current_build == build and current_version == version:
            logger.info('the same version and build')
        else:
            logger.error('not the same version and build')

    def log_checks(self, ftd_line, list_files=['/var/log/messages'],
                   search_strings=['fatal', 'error'], exclude_strings=[], timeout=300):
        """Wrapper function to Get logs for FTD.

        :param ftd_line: Instance of FTD line used to connect to FTD
        :param list_files: List of file paths for files to search in
        :param search_strings: List of keywords to loook for in the logs
        :param exclude_strings: List of keywords to be excluded in the logs
        :param timeout: time to wait for log retrieval in seconds

        e.g.:
            list_files = ['/var/log/boot_1341232','/var/log/boot_*'] \n
            search_strings = ['fatal','error', 'crash'] \n
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
  
    def ssh_vty(self, ip, port, username='admin', password='Admin123',
                timeout=None, line_type='ssh_vty', rsa_key=None):
        return super().ssh_vty(ip, port, username=username, password=password,
                               timeout=timeout, line_type=line_type)


class Ftd5500xLine(BasicLine):
    def __init__(self, spawn, sm, type, timeout=None):
        """ Constructor of Ftd5500x

        :param spawn: spawn_id of the line
        :param sm: object of statemachine
        :param type: line type, e.g. 'ssh', 'telnet'
        :return: object of the line

        """

        try:
            super().__init__(spawn, sm, type, timeout)
        except:
            if self.type is 'ssh_vty':
                raise
            # Handle boot loop
            logger.info("Try to drop device to rommon state.")
            logger.info('=== Failed to go_to("any") '
                        'try to drop device to rommon.')
            try:
                self.rommon_go_to(timeout=300)
                self.sm.update_cur_state('rommon_state')
                logger.info('=== Dropped device to rommon.')
            except:
                logger.info("Failed to go to rommon. Unknown device state.")

    def expert_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """Execute a command in expert mode

        :param cmd: command to be executed in expert state given as a string
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
                on a bad command
        :return: output as string

        """

        self.go_to('expert_state')
        return self.execute(cmd, timeout, exception_on_bad_command)

    def enable_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """Go to enable mode, run the command and return the output.

        :param cmd: command to be executed given as a string
        :param timeout: in seconds
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :return: output as string

        """

        # first, issue "no terminal pager"
        # then run command
        super().enable_execute('no terminal pager')
        return super().enable_execute(cmd, timeout, exception_on_bad_command)

    def wait_until_device_on(self, timeout=600):
        """ Wait a given period of time for device to be on

        :param timeout: wait time for the device to boot up
        :return: None

        """

        # The system will reboot, wait for the following prompts
        d1 = Dialog([
            ['SW-DRBG health test passed', None, None, False, False],
        ])
        d1.process(self.spawn_id, timeout=timeout)

        # sleep 60 seconds to avoid errors
        time.sleep(60)
        self.sm.go_to('any', self.spawn_id)

    def power_cycle(self, power_bar_server, power_bar_port,
                    wait_until_device_is_on=True, timeout=600,
                    power_bar_user='admn', power_bar_pwd='admn'):
        """reboots a device from a Power Data Unit equipment.

        :param power_bar_server: comma-separated string string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string string of power ports on the PDU's
        :param wait_until_device_is_on: True if waits for the device
                                to boot up, False otherwise
        :param timeout: wait time for the device to boot up
        :param power_bar_user: comma-separated string of usernames for power bar servers
        :param power_bar_pwd: comma-separated string of passwords for power bar servers
        :return: status of power cycle result, True or False

        """

        if power_bar_server == "" or power_bar_port == "":
            return None

        result = power_cycle_all_ports(power_bar_server, power_bar_port, power_bar_user, power_bar_pwd)

        if wait_until_device_is_on:
            logger.info('Wait for device to be up and running ...')
            self.wait_until_device_on(timeout=timeout)

        return result

    # the following functions are for device baselining. This only works on
    # a console line (ssh or telnet).
    def expect_and_sendline(self, this_spawn, es_list, timeout=10):
        """takes a list of expect/send actions and perform them one by one.

        es_list looks like:
        [['exp_pattern1', 'send_string1', 30],
         ['exp_pattern2', 'send_string2'],
         ...
        ]

        The third element is for timeout value, and can be ommitted when the
        overall timeout value applies.

        :param this_spawn: the spawn of the line
        :param es_list: pairs of expected output and command to be sent
        :param timeout: default timeout for the command if timeout is not set
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
            time.sleep(3)

    def rommon_go_to(self, timeout=180):
        """Go to rommon mode.

        :return: None

        """

        # break into rommon
        d1 = Dialog([
            ['Use SPACE to begin boot immediately.',
             'sendline({})'.format(chr(27)), None, False, False],
        ])
        d1.process(self.spawn_id, timeout=timeout)
        time.sleep(10)
        logger.info('In rommon mode')

    def rommon_configure(self):
        """In ROMMON mode, set network, tftp info and rommon image For Kenton.

        :return: None

        """

        logger.info('add rommon config')
        es_list = [
            ['rommon', 'ADDRESS={}'.format(self.uut_ip)],
            ['rommon', 'NETMASK={}'.format(self.uut_netmask)],
            ['rommon', 'SERVER={}'.format(self.rommon_tftp_server)],
            ['rommon', 'IMAGE={}'.format(self.rommon_image)],
            ['rommon', 'GATEWAY={}'.format(self.uut_gateway)],
            ['rommon', 'PORT=Management0/0'],
        ]

        self.expect_and_sendline(self.spawn_id, es_list)

    def rommon_configure_saleen(self):
        """In ROMMON mode, set network, tftp info and rommon image For Saleen.

        :return: None

        """

        logger.info('add rommon config')
        es_list = [
            ['rommon', 'address {}'.format(self.uut_ip)],
            ['rommon', 'gateway {}'.format(self.uut_gateway)],
            ['rommon', 'server {}'.format(self.rommon_tftp_server)],
            ['rommon', 'file {}'.format(self.rommon_image)],
        ]
        self.expect_and_sendline(self.spawn_id, es_list)

    def rommon_boot(self, timeout=600):
        """Perform TFTP Boot from ROMMON.

        :return: None

        """

        time.sleep(10)
        logger.info('=== Performing TFTP Boot from ROMMON')
        logger.info('=== Wait for installation to complete, timeout = {}'
                    ' seconds ...'.format(str(timeout)))
        self.spawn_id.sendline('tftpdnld')
        d1 = Dialog([
            ['rommon.*> ', 'sendline(tftpdnld)', None, True, False],
            ['Use SPACE to launch Cisco FTD immediately.',
             'sendline({})'.format(chr(27)), None, True, False],
            ['-boot>', 'sendline()', None, False, False],
            [self.sm.patterns.prompt.enable_prompt, 'sendline()', None, False, False],
            [self.sm.patterns.prompt.disable_prompt, 'sendline()', None, False, False],
        ])
        try:
            d1.process(self.spawn_id, timeout=timeout)
            self.spawn_id.sendline()
            logger.info("=== Rommon file was installed successfully.")
        except:
            logger.info("=== Rommon file download failed, raise runtime error. ")
            raise RuntimeError(
                ">>>>>> Download failed. Please check details - "
                "tftp_server: {}, image file: {}".format(self.rommon_tftp_server,
                                                         self.rommon_image))

        logger.info('In boot CLI mode')
        logger.info("=== Rommon file was installed successfully.")

    def firepower_boot_configure(self):
        """In boot CLI mode, set device network info, DNS server and domain.

        :return: None

        """

        d1 = Dialog([
            ['-boot>', 'sendline(setup)', None, False, False],
        ])
        d1.process(self.spawn_id)
        set_ntp_server = 'n' if self.ntp_server == None else 'y'
        d2 = Dialog([
            ['Enter a hostname ', 'sendline(firepower)', None, True, False],
            ['Do you want to configure IPv4 address on management interface',
             'sendline(y)', None, True, False],
            ['Do you want to enable DHCP for IPv4 address assignment on '
             'management interface', 'sendline(n)', None, True, False],
            ['Enter an IPv4 address', 'sendline({})'.format(self.uut_ip),
             None, True, False],
            ['Enter the netmask', 'sendline({})'.format(self.uut_netmask),
             None, True, False],
            ['Enter the gateway', 'sendline({})'.format(self.uut_gateway),
             None, True, False],
            ['Do you want to configure static IPv6 address on management '
             'interface', 'sendline(n)', None, True, False],
            ['Enter the primary DNS server IP address',
             'sendline({})'.format(self.dns_server.split(',')[0]), None, True, False],
            ['Do you want to configure Secondary DNS Server', 'sendline(n)',
             None, True, False],
            ['Do you want to configure Local Domain Name', 'sendline(n)',
             None, True, False],
            ['Do you want to configure Search domains', 'sendline(y)', None,
             True, False],
            ['Enter the comma separated list for search domains',
             'sendline({})'.format(self.search_domains), None, True, False],
            ['Do you want to enable the NTP service', 'sendline({})'.format(set_ntp_server), None,
             True, False],
            ['Enter the NTP servers separated by commas', 'sendline({})'.format(self.ntp_server), None,
             True, False],
            ['Apply the changes', 'sendline(y)', None, True, False],
            ['Press ENTER to continue...', 'sendline()', None, True, False],
            ['-boot>', 'sendline()', None, False, False],
        ])
        d2.process(self.spawn_id, timeout=120)

    def firepower_install(self):
        """Perform ping test and verify the network connectivity to TFTP server.
        Install FTD pkg image Enter device network info, hostname, and firewall
        mode.

        :return: None

        """

        for i in range(40):
            self.spawn_id.sendline('ping -c 1 {}'.format(self.rommon_tftp_server))
            try:
                self.spawn_id.expect('64 bytes from', timeout=5)
            except TimeoutError:
                time.sleep(60)
                continue
            else:
                break
        else:
            raise RuntimeError(">>>>>> Ping not working")

        d0 = Dialog([
            ['-boot>', 'sendline(system install {})'.format(self.pkg_image),
                None, False, False]
        ])

        d1 = Dialog([
            ['Do you want to continue?', 'sendline(y)', None, True, False],
            ['Upgrade aborted', 'sendline()', None, False, False],
            ['Installation aborted', 'sendline()', None, False, False]
        ])
        count = 0
        while count < self.retry_count:
            try:
                d0.process(self.spawn_id, timeout=20)
                d1.process(self.spawn_id, timeout=60)
                count += 1
                time.sleep(5)
            except:
                break
        assert count < self.retry_count, 'ftd installation failed' \
            ', please check ftd package url: "{}"'.format(self.pkg_image)

        d2 = Dialog([
            ['Do you want to continue with upgrade?', 'sendline(y)', None,
             True, True],
            ["Press 'Enter' to reboot the system.", 'sendline()', None, True,
             True],
            ['Use SPACE to begin boot immediately.', 'send(" ")', None, True,
             True],
            ['Use SPACE to launch Cisco FTD immediately.', 'send(" ")', None,
             True, True],
            ['firepower login: ', 'sendline()', None, False, False],
        ])
        d2.process(self.spawn_id, timeout=3900)

        # Allow install processes to finish
        # Sleep was extended to 5 minutes as part of CSCvi89671
        # TODO: This sleep should be removed once CSCvi89616 is resolved
        time.sleep(300)

        d3 = Dialog([
            ['firepower login: ', 'sendline(admin)', None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.default_password),
             None, True, False],
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, True, False],
            ['--More--', 'send(q)', None, True, False],
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ",
             'sendline(YES)', None, False, False],
        ])
        d3.process(self.spawn_id, timeout=600)

        d4 = Dialog([
            ['firepower login: ', 'sendline(admin)', None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.login_password),
             None, True, False],
            ['Enter new password:', 'sendline({})'.format(self.sm.patterns.login_password),
             None, True, True],
            ['Confirm new password:', 'sendline({})'.format(self.sm.patterns.login_password),
             None, True, False],
            ['Do you want to configure IPv4', 'sendline(y)', None, True, False],
        ])

        if self.uut_ip6 is None:
            d4.append(['Do you want to configure IPv6', 'sendline(n)', None, True, False])
        else:
            d4.append(['Do you want to configure IPv6', 'sendline(y)', None, True, False])
        d4.append(['Configure IPv4 via DHCP or manually', 'sendline(manual)', None,
                   True, False])
        d4.append(['Enter an IPv4 address for the management interface',
                   'sendline({})'.format(self.uut_ip), None, True, False])
        d4.append(['Enter an IPv4 netmask for the management interface',
                   'sendline({})'.format(self.uut_netmask), None, True, False])
        d4.append(['Enter the IPv4 default gateway for the management interface',
                   'sendline({})'.format(self.uut_gateway), None, True, False])
        if self.uut_ip6 is not None:
            d4.append(['Configure IPv6 via DHCP, router, or manually',
                       'sendline(manual)', None, True, False])
            d4.append(['Enter the IPv6 address for the management interface',
                       'sendline({})'.format(self.uut_ip6), None, True, False])
            d4.append(['Enter the IPv6 address prefix for the management interface',
                       'sendline({})'.format(self.uut_prefix), None, True, False])
            d4.append(['Enter the IPv6 gateway for the management interface',
                       'sendline({})'.format(self.uut_gateway6), None, True, False])
        d4.append(['Enter a fully qualified hostname for this system',
                   'sendline({})'.format(self.hostname), None, True, False])
        d4.append(['Enter a comma-separated list of DNS servers or',
                   'sendline({})'.format(self.dns_server), None, True, False])
        d4.append(['Enter a comma-separated list of search domains or',
                   'sendline({})'.format(self.search_domains), None, False, False])
        d4.process(self.spawn_id, timeout=900)

        d5 = Dialog([
            ['Configure (firewall|deployment) mode', 'sendline({})'.format(self.firewall_mode),
             None, True, False]
        ])

        if self.mode == 'local':
            d5.append(['Manage the device locally?', 'sendline(yes)', None, True, False])
        else:
            d5.append(['Manage the device locally?', 'sendline(no)', None, True, False])
        d5.append(['Successfully performed firstboot initial configuration steps',
                   'sendline()', None, True, False])
        d5.append(['> ', 'sendline()', None, False, False])
        d5.process(self.spawn_id, timeout=600)

        logger.info('fully installed.')

    def configure_manager(self):
        """Configure manager to be used for registration

        :return: None

        """

        self.go_to('fireos_state')
        if self.manager_nat_id is None:
            response = self.execute('configure manager add {} {}'.format(self.manager,
                                                                         self.manager_key),
                                    120)
        else:
            response = self.execute('configure manager add {} {} {}'.format(self.manager,
                                                                            self.manager_key,
                                                                            self.manager_nat_id),
                                    120)
        success = re.search('Manager successfully configured', response)
        if success is None:
            logger.error('Exception: failed to configure the manager')
            raise RuntimeError('>>>>>> configure manager failed:\n{}\n'.format(response))

    def validate_version(self):
        """Checks if the installed version matches the version in package url

        :return: None

        """

        self.go_to('fireos_state')

        # check version
        response = self.execute('show version', 30)
        if not response:
            response = self.execute('show version', 30)
        build = re.findall('Build\s(\d+)', response)[0]
        version = re.findall(r'(Version\s){1}([0-9.]+\d)', str(response))[0][1]
        ftd_package_file = self.pkg_image.split('/')[-1]
        if (build in ftd_package_file) and (version in ftd_package_file):
            logger.info('>>>>>> show version result:\n{}\nmatches '
                        'ftd package image: {}'.format(response,
                                                       ftd_package_file))
            logger.info('Installed ftd version validated')
        else:
            logger.error('Exception: not the same version and build')
            raise RuntimeError('>>>>>> show version result:\n{}\ndoes not match '
                               'ftd package image: {}'.format(response,
                                                              ftd_package_file))

    def rommon_to_new_image(self, rommon_tftp_server, pkg_image,
                            uut_ip, uut_netmask, uut_gateway, rommon_image, dns_server,
                            hostname='firepower', search_domains='cisco.com',
                            is_device_kenton=True, retry_count=MAX_RETRY_COUNT,
                            power_cycle_flag=False, pdu_ip='', pdu_port='',
                            pdu_user='admn', pdu_pwd='admn', ntp_server=None,
                            mode='local',
                            uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                            manager=None, manager_key=None, manager_nat_id=None,
                            firewall_mode='routed', timeout=600, **kwargs):
        """Install rommon image and FTD pkg image on ASA.

        :param rommon_tftp_server: TFTP Server IP Address
        :param pkg_image: FTD image to be transferred via HTTP,
            e.g. 'http://192.168.0.50/Release/6.0.0-1005/installers/ftd-6.0.0-1005.pkg'
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param rommon_image: boot image under /tftpboot to be transferred via TFTP,
            e.g. 'asa/Release/6.0.0-1005/installers/ftd-boot-99.1.3.194.lfbff'
        :param dns_server: DNS server
        :param hostname: hostname to be set
        :param search_domains: search domains delimited by comma,
            defaulted to 'cisco.com'
        :param is_device_kenton: True if device is Kenton, False if device is Saleen
        :param retry_count: download retry count, defaulted to MAX_RETRY_COUNT
        :param power_cycle_flag: True power cylce before baseline, False otherwise
        :param pdu_ip: PDU IP
        :param pdu_port: PDU Port
        :param pdu_user: PDU admn
        :param pdu_pwd: PDU pwd
        :param ntp_server: NTP server delimited by comma, defaulted to None,
            otherwise the value of ntp_server is - e.g. "ntp.esl.cisco.com"
        :param mode: the manager mode (local, remote)
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param firewall_mode: the firewall mode (routed, transparent, ngips)
        :param timeout: in seconds; time to wait for fetching the boot image from TFTP server;
                        defaulted to 600s
        :return: None

        """

        logger.info('Starting baseline')
        graphite.publish_kick_metric('device.ftd5500x.baseline', 1)
        self.rommon_tftp_server = rommon_tftp_server
        self.pkg_image = pkg_image
        self.uut_ip = uut_ip
        self.uut_netmask = uut_netmask
        self.uut_gateway = uut_gateway
        self.uut_ip6 = uut_ip6
        self.uut_prefix = uut_prefix
        self.uut_gateway6 = uut_gateway6
        self.rommon_image = rommon_image
        self.dns_server = dns_server
        self.hostname = hostname
        self.search_domains = search_domains
        self.retry_count = retry_count
        self.ntp_server = ntp_server
        self.mode = mode
        self.firewall_mode=firewall_mode
        self.manager = manager
        self.manager_key = manager_key
        self.manager_nat_id = manager_nat_id
        if not (self.sm.current_state in ['rommon_state', 'boot_state']):
            if not power_cycle_flag:
                if self.sm.current_state is 'disable_state':
                    logger.info('Device is in disable state. Go to enable and reload ...')
                    self.go_to('enable_state')
                    self.spawn_id.sendline('reload noconfirm')
                elif self.sm.current_state in ['enable_state', 'config_state']:
                    logger.info('Device is in enable or config state. Reloading ...')
                    self.spawn_id.sendline('reload noconfirm')
                else:
                    logger.info('Reboot the device ...')
                    self.go_to('sudo_state')
                    self.spawn_id.sendline('reboot')
            else:
                logger.info('Power cycle the device ...')
                self.power_cycle(pdu_ip, pdu_port, wait_until_device_is_on=False, power_bar_user=pdu_user,
                                 power_bar_pwd=pdu_pwd)
            try:
                self.spawn_id.expect('Use (.*?BREAK.*?|.*?ESC.*?) to interrupt boot', timeout=120)
            except TimeoutError:
                RuntimeError(">>>>>> Failed to stop rebooting")
            logger.info('Drop the device to rommon.')
            self.rommon_go_to()

        if self.sm.current_state is 'boot_state':
            logger.info('Device is in boot_state, drop the device to rommon.')
            self.spawn_id.sendline('system reload')
            d1 = Dialog([
                ['Are you sure you want to reload the system',
                 'sendline(y)', None, False, False],
            ])
            d1.process(self.spawn_id, timeout=30)
            self.rommon_go_to()

        if is_device_kenton:
            logger.info('Device is Kenton. Rommon configure.')
            self.rommon_configure()
        else:
            logger.info('Device is Saleen. Rommon configure.')
            self.rommon_configure_saleen()

        logger.info('tftpdnld - tftp server: {}, '
                    'rommon image: {} ...'.format(rommon_tftp_server, rommon_image))
        self.rommon_boot(timeout=timeout)
        self.go_to('any')
        logger.info('firepower boot configure ...')
        self.firepower_boot_configure()
        logger.info('FTD image install - image: {} ...'.format(pkg_image))
        self.firepower_install()
        self.go_to('any')
        if self.manager is not None and self.mode != 'local':
            logger.info('Configure manager')
            self.configure_manager()
        logger.info('Validate version installed')
        self.validate_version()
        logger.info('Installation completed successfully.')

    def enable_configure(self, timeout=20):
        """Used to enable configure terminal

        :param timeout: time to wait for the output of a command;
                        default is 30s
        :return: None

        """
        d = Dialog([
            ['-boot>', 'sendline()', None, False, False],
            [self.sm.patterns.prompt.enable_prompt, 'sendline()', None, False, False],
            [self.sm.patterns.prompt.disable_prompt, 'sendline()', None, False, False],
            ['login', 'sendline({})'.format(self.sm.patterns.username), None, True, False],
            ['(p|P)assword:', 'sendline({})'.format(self.sm.patterns.login_password), None, False, False],
        ])

        d1 = Dialog([
            ['Would you like to enable anonymous error reporting to help improve', 'sendline(N)',
             None, True, False],
            [self.sm.patterns.prompt.config_prompt, 'sendline()', None, False, False],
        ])

        try:
            self.go_to('any')
        except:
            logger.info("Device is rebooting")
            d.process(self.spawn_id, timeout=600)
            self.go_to('any')

        self.go_to('enable_state')
        time.sleep(0.5)
        logger.info("=== Configure terminal ")
        self.spawn_id.sendline('conf t')
        time.sleep(0.5)
        if 'Invalid input detected' in self.spawn_id.read():
            self.spawn_id.sendline()
            time.sleep(0.5)
            self.spawn_id.expect(self.sm.patterns.prompt.enable_prompt)
            output = self.execute('show running-config | grep Serial Number', 15)
            sn = re.findall(r'Serial Number:\s(\w+)', output)[0]
            new_sn = '1111222233334444' + sn
            self.sudo_execute('echo -n {}| md5sum > /mnt/disk0/enable_configure'.format(new_sn), timeout)
            self.go_to('config_state')
            d1.process(self.spawn_id, timeout=30)

    def set_boot_image(self, tftp_server, boot_image, timeout=20):
        """Function for setting the new boot system image

        :param tftp_server: tftp server ip
                e.g: '192.168.0.50'
        :param boot_image: the name of the boot image given with its absolute path
               e.g. asa/asa952-2-smp-k8.bin for saleen or asa/asa962-21-lfbff-k8.SPA for Kenton
               asa962-21-lfbff-k8.SPA
        :param timeout: defaulted to 20s
        :return: None

        """

        self.go_to('config_state')
        # remove previous images
        output = self.execute('show running-config boot system')
        if output:
            images = re.findall(r'disk0:/.*', output)
            logger.info('Removing previous boot system images')
            if images:
                for i in images:
                    self.execute('no boot system {}'.format(i), timeout)

        logger.info('Copying the new ASA image to the ASA, placing the image in disk0')
        asa_boot_image = PurePosixPath(boot_image).name or boot_image
        command = 'copy /noconfirm tftp://{}/{} disk0:{}'.format(tftp_server, boot_image, asa_boot_image)
        self.spawn_id.sendline(command)
        d1 = Dialog([
            ['Do you want to over write?', 'sendline()', None, True, False],
            ['Accessing tftp', None, None, True, True],
            ['Digital signature successfully validated', None, None, True, False],
            ['bytes copied in .* secs', 'sendline()', None, False, False],
            ['Error', None, None, False, False],
            [self.sm.patterns.prompt.config_prompt, 'sendline()', None, False, False],
        ])
        resp = d1.process(self.spawn_id, timeout=1200)
        if isinstance(resp, ExpectMatch):
            if 'Error' in resp.match_output:
                logger.error('An error appeared while downloading the image, '
                             'please check the name of the boot image and its path')
                raise RuntimeError('An error appeared while downloading the boot image, '
                                   'please check your file path')

        logger.info('Setting new boot system image')
        self.execute('boot system disk0:/{}'.format(asa_boot_image, timeout))
        self.spawn_id.sendline('write memory')
        d2 = Dialog([
            #[self.sm.patterns.prompt.config_prompt, 'sendline(write memory)', None, True, False],
            ['Building configuration', None, None, True, False],
            ['[OK]', 'sendline()', None, True, False],
            [self.sm.patterns.prompt.config_prompt, None, None, False, False],
        ])
        d2.process(self.spawn_id, timeout=60)

    def configure_mgmt_interface(self, ip, netmask, gateway, tftp_server, mgmt_port='Management1/1'):
        """

        :param ip: ip address of the management interface
        :param netmask: netmask of the network
        :param gateway: gateway ip address
        :param tftp_server: ip address of tftp server
        :param mgmt_port: name of the management port; if not provided, defaulted to 'Management1/1'
        :return: None
        """

        self.go_to('config_state')
        es_list = [
            [self.sm.patterns.prompt.config_prompt, 'conf t'],
            [self.sm.patterns.prompt.config_prompt, 'int {}'.format(mgmt_port)],
            [self.sm.patterns.prompt.config_prompt, 'ip address {} {}'.format(ip, netmask)],
            [self.sm.patterns.prompt.config_prompt, 'nameif diagnostic'],
            [self.sm.patterns.prompt.config_prompt, 'no shutdown'],
            [self.sm.patterns.prompt.config_prompt, 'no cts manual'],
            [self.sm.patterns.prompt.config_prompt, 'security-level 100'],
            [self.sm.patterns.prompt.config_prompt, 'exit'],
            [self.sm.patterns.prompt.config_prompt, 'route diagnostic 0 0 {} 1'.format(gateway)],
            [self.sm.patterns.prompt.config_prompt, 'ping {}'.format(tftp_server)],
        ]
        self.expect_and_sendline(self.spawn_id, es_list, 20)

    def convert_to_elektra(self, rommon_tftp_server,
        uut_ip, uut_netmask, uut_gateway, asa_image, dns_server,
        hostname='firepower', search_domains='cisco.com',
        is_device_kenton=True, retry_count=MAX_RETRY_COUNT,
        power_cycle_flag=False, pdu_ip='', pdu_port='', mgmt_port='Management1/1', timeout=600):
        """Install rommon image and FTD pkg image on ASA.

        :param rommon_tftp_server: TFTP Server IP Address
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param asa_image: asa boot image to be transferred via TFTP,
            e.g. 'asa/asa952-2-smp-k8.bin' for saleen or 'asa/asa952-2-lfbff-k8.SPA' for Kenton
        :param dns_server: DNS server
        :param hostname: hostname to be set
        :param search_domains: search domains delimited by comma,
            defaulted to 'cisco.com'
        :param is_device_kenton: True if device is Kenton, False if device is Saleen
        :param retry_count: download retry count, defaulted to MAX_RETRY_COUNT
        :param power_cycle_flag: True power cylce before baseline, False otherwise
        :param pdu_ip: PDU IP
        :param pdu_port: PDU Port
        :param mgmt_port: name of the management port; if not provided, defaulted to 'Management1/1'
        :param timeout: in seconds; time to wait for fetching the boot image from TFTP server;
                       defaulted to 600s
        :return: None

        """
        self.rommon_tftp_server = rommon_tftp_server
        self.uut_ip = uut_ip
        self.uut_netmask = uut_netmask
        self.uut_gateway = uut_gateway
        self.rommon_image = asa_image
        self.dns_server = dns_server
        self.hostname = hostname
        self.search_domains = search_domains

        if self.sm.current_state is 'rommon_state':
            logger.info('Reboot the device ...')
            self.spawn_id.sendline('reboot')

        if self.sm.current_state is 'boot_state':
            logger.info('Device is in boot_state, reload the device')
            self.spawn_id.sendline('system reload')
            d1 = Dialog([
                ['Are you sure you want to reload the system',
                 'sendline(y)', None, False, False],
            ])
            d1.process(self.spawn_id, timeout=30)

        logger.info('=== Enable configure')
        self.enable_configure()

        logger.info("=== Configure manamgement interface")
        self.configure_mgmt_interface(uut_ip, uut_netmask, uut_gateway, rommon_tftp_server, mgmt_port)

        logger.info("=== Set the new boot image")
        self.set_boot_image(self.rommon_tftp_server, asa_image)

        logger.info('=== Reboot the device ...')
        self.go_to('config_state')
        self.spawn_id.sendline('reload')
        d = Dialog([
            ['Proceed with reload?', 'sendline()', None, True, False],
            ['Rebooting', None, None, False, False],
        ])
        d.process(self.spawn_id, timeout=180)

        logger.info('==== Drop the device to rommon.')
        self.rommon_go_to()

        if is_device_kenton:
            logger.info('Device is Kenton. Rommon configure.')
            self.rommon_configure()
        else:
            logger.info('Device is Saleen. Rommon configure.')
            self.rommon_configure_saleen()

        logger.info('tftpdnld - tftp server: {}, '
                    'rommon image: {} ...'.format(rommon_tftp_server, asa_image))
        self.rommon_boot(timeout=timeout)

        logger.info("=== Configure management interface")
        self.go_to('any')
        self.configure_mgmt_interface(uut_ip, uut_netmask, uut_gateway, rommon_tftp_server, mgmt_port)
        logger.info("=== You have converted successfully the device to Elektra")
 
    def baseline_by_branch_and_version(self, site, branch, version,
                                       uut_ip, uut_netmask, uut_gateway, dns_server, serverIp='', tftpPrefix='', scpPrefix='', docs='', **kwargs):
        """Baseline ftd using branch and version
        
        :param site: e.g. 'ful', 'ast'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param \**kwargs:
            :Keyword Arguments, any of below optional parameters:
        :param hostname: hostname to be set; defaulted to 'firepower'
        :param search_domains: search domains delimited by comma,
            defaulted to 'cisco.com'
        :param is_device_kenton: True if device is Kenton, False if device is Saleen
        :param retry_count: download retry count, defaulted to MAX_RETRY_COUNT
        :param power_cycle_flag: True power cylce before baseline, False otherwise
        :param pdu_ip: PDU IP
        :param pdu_port: PDU Port
        :param pdu_user: PDU admn
        :param pdu_pwd: PDU pwd
        :param ntp_server: NTP server delimited by comma, defaulted to None,
            otherwise the value of ntp_server is - e.g. "ntp.esl.cisco.com"
        :param mode: the manager mode (local, remote)
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param firewall_mode: the firewall mode (routed, transparent, ngips)
        :param timeout: in seconds; time to wait for fetching the boot image from TFTP server;
                        defaulted to 600s
        :return: None
        """

        is_device_kenton = kwargs.get('is_device_kenton', True)

        if KICK_EXTERNAL:
            server_ip = serverIp
            tftp_prefix = tftpPrefix
            files = docs
        else:
            device_type = 'kenton' if is_device_kenton else 'saleen'
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, device_type, branch, version)

        rommon_file_extension = '.lfbff' if is_device_kenton else '.cdisk'
        rommon_file = [file for file in files if file.endswith(rommon_file_extension)]

        files.remove(rommon_file[0])
        pkg_image = "http://{}/{}/{}".format(server_ip, tftp_prefix[len('asa/'):], files[0])
        rommon_image = os.path.join(tftp_prefix, rommon_file[0])

        kwargs['rommon_tftp_server'] = server_ip
        kwargs['pkg_image'] = pkg_image
        kwargs['rommon_image'] = rommon_image
        kwargs['uut_ip'] = uut_ip
        kwargs['uut_netmask'] = uut_netmask
        kwargs['uut_gateway'] = uut_gateway
        kwargs['dns_server'] = dns_server

        self.rommon_to_new_image(**kwargs)
