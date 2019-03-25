import datetime
import logging
import re
import time

from unicon.eal.dialogs import Dialog

logger = logging.getLogger(__name__)

from unicon.eal.expect import TimeoutError
from ...general.actions.basic import BasicDevice, BasicLine

try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric
from ...general.actions.power_bar import power_cycle_all_ports

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True
    pass

MAX_RETRY_COUNT = 3


class Elektra(BasicDevice):
    def __init__(self, hostname='firepower', login_password='Admin123',
                 sudo_password='Admin123', enable_password='', *args, **kwargs):
        """Constructor for Elektra.

        :param hostname: hostname for the device
        :param login_password: device login password with user name 'admin'
        :param sudo_password: device sudo password for 'root'
        :param enable_password: device enable password
        Add *args and **kwargs so that the initiator can be invoked with
        additional (unused) arguments.

        """

        super().__init__()
        publish_kick_metric('device.elektra.init', 1)

        from .patterns import ElektraPatterns
        self.patterns = ElektraPatterns(hostname, login_password, sudo_password, enable_password)

        # create the state machine that contains the proper attributes.
        from .statemachine import ElektraStatemachine
        self.sm = ElektraStatemachine(self.patterns)

        # important: set self.line_class so that a proper line can be created
        # by ssh_console(), etc.
        self.line_class = ElektraLine

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


class ElektraLine(BasicLine):

    def go_to(self, state, timeout=10):
        """
            Override parent go_to function to enable hop_wise flag.
        """
        super().go_to(state, hop_wise=True, timeout=timeout)

    def change_to_context(self, ctx, timeout=None):
        """Multi-context support.

        :param ctx: context name
        :param timeout: timeout to change context
        :return: None

        """

        # always raise exception if specified context is invalid
        self.execute('changeto context {}'.format(ctx), timeout=timeout,
                     exception_on_bad_command=True)

    def change_to_system(self, timeout=None):
        """Multi-context support, change to system context.

        :param timeout: timeout to change context
        :return None

        """

        self.execute('changeto system', timeout=timeout,
                     exception_on_bad_command=True)

    def find_matched_str(self, expected_str, return_data, matched_whole_line=False):
        """find matched line or substring from return_data.

        :param expected_str: expected string for the output of cmd executed
        :param return_data: command output
        :param matched_whole_line: True if want to match the whole line,
                                    otherwise, match the substring
        :return matched_obj: the matched object

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
        """Execute a command, verify the output, set the config if the output
        is not expected, The command will be run and retried for no more than
        retry_count, and no more than timeout_total in seconds Assert if
        expected_str is not found in the output of cmd.

        :param cmd: command to be executed
        :param expected_str: expected string for the output of cmd executed
        :param cmd_set_config: command to be executed if expected_str is not seen,
                                if cmd_set_config is an empty string, the function is waiting only
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
            print('>>>' + return_data + '<<<')
            logger.info('command output: {}'.format(return_data))
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
                logger.info('time elapsed: {} seconds'.format(round(elapsed_time)))
                time.sleep(interval)
            else:
                logger.info('found expected string: {}'.format(expected_str))
                expected = True
                break
        assert expected, "Command: {}, Expected String: {}" \
                          " not found".format(cmd, expected_str)

    def configure_terminal(self):
        """Configure terminal settings.

        :return None

        """

        self.go_to('enable_state')
        self.execute('terminal pager 0')
        self.go_to('config_state')
        self.execute('ssh timeout 60')
        self.execute('terminal width 511')
        self.go_to('enable_state')

    def download_and_set_boot_module(self):
        """Download boot image, and set module to downloaded image.

        :return: None

        """

        asa_boot_image = 'disk0:asaboot.img'
        logger.info('=== Download boot image {} to {}'.format(self.boot_image,
                                                              asa_boot_image))
        command = 'copy /noconfirm {} {}'.format(self.boot_image, asa_boot_image)
        self.execute_and_verify(cmd=command,
                                expected_str='bytes copied in',
                                timeout=120,
                                timeout_total=360,
                                retry_count=self.retry_count)
        logger.info("=== Stop the current recovery process if any")
        output = self.execute('sw-module module sfr recover stop')
        if 'Module sfr cannot have recovery stopped, not in recover state' not in output:
            logger.info('=== Check that current sfr recovery has stopped')
            self.execute_and_verify(cmd='show module sfr details | grep ^Status',
                                    expected_str='    Unresponsive   No Image Present',
                                    timeout=120,
                                    interval=10,
                                    timeout_total=360,
                                    retry_count=50)
        logger.info('=== Set module to {}'.format(asa_boot_image))
        self.execute('sw-module module sfr recover '
                     'configure image {}'.format(asa_boot_image))

        self.spawn_id.sendline('sw-module module sfr recover boot')
        d1 = Dialog([
            ['Recover module sfr', 'sendline()', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=30)

        logger.info('=== Check module sfr status')
        # if sfr status is 'Up', the module recover command has to be reissued
        output = self.execute("show module sfr details | grep ^Status")
        if any(state in output for state in ["Init", "Up"]):
            self.execute_and_verify(cmd='show module sfr details | grep ^Status',
                                    expected_str='    Up',
                                    timeout=120,
                                    interval=10,
                                    timeout_total=360,
                                    retry_count=50)
            self.spawn_id.sendline('sw-module module sfr recover boot')
            d1.process(self.spawn_id, timeout=30)
        # Expect 'Recover', otherwise it is 'Shutting Down'
        self.execute_and_verify(cmd='show module sfr details | grep ^Status',
                                expected_str='    Recover',
                                timeout=120,
                                interval=10,
                                timeout_total=360,
                                retry_count=50)
        self.execute_and_verify(cmd='show module sfr details | grep ^Console session:',
                                expected_str='    Ready',
                                timeout=60,
                                interval=10,
                                timeout_total=360,
                                retry_count=50)

        logger.info('=== Connect sfr console')
        self.spawn_id.sendline()
        # Wait for this error state to be finished:
        # 'ERROR: Failed opening console session with
        # module sfr. Module is in "Recover" state.'
        # 'Please try again later.'
        self.spawn_id.sendline('session sfr console')
        d2 = Dialog([
            ['({}|firepower)#'.format(self.sm.patterns.hostname),
             'sendline({})'.format('session sfr console'), None, True, False],
            ['Escape character sequence is', 'sendline()',
             None, True, False],
            [r'\w+ login:', 'sendline({})'.format(self.sm.patterns.username),
             None, True, False],
            ['Password:', 'sendline({})'.format(self.sm.patterns.login_password),
             None, True, False],
            ['-boot>', 'sendline()', None, False, False],
        ])
        d2.process(self.spawn_id, timeout=600)

    def boot_configure(self):
        """In boot CLI mode, set device network info, DNS server and domain.

        :return: None

        """

        self.spawn_id.sendline('setup')
        self.spawn_id.expect('-boot>')
        set_ntp_server = 'n' if self.ntp_server == None else 'y'
        d2 = Dialog([
            ['Enter a hostname ', 'sendline({})'.format(self.hostname),
             None, True, False],
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
             'sendline({})'.format(self.dns_server), None, True, False],
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
            ['Do you want to enable the NTP symmetric key authentication?', 'sendline(n)', None, True, False],
            ['Apply the changes', 'sendline(y)', None, True, False],
            ['Press ENTER to continue...', 'sendline()', None, False, False],
        ])
        d2.process(self.spawn_id, timeout=120)

    def ftd_install(self):
        """Perform ping test and verify the network connectivity to http server
        Install SFR pkg image Enter device network info, hostname.

        :return: None

        """

        self.spawn_id.sendline('')
        self.spawn_id.expect('-boot>', timeout=20)
      
        for i in range(20):
            self.spawn_id.sendline('ping -c 1 {}'.format(self.http_server))
            try:
                self.spawn_id.expect('64 bytes from', timeout=5)
            except TimeoutError:
                continue
            else:
                break
        else:
            raise RuntimeError(">>>>>> Ping not working")

        d1 = Dialog([
            ['-boot>', 'sendline(system install {})'.format(self.pkg_image),
                None, True, False],
            ['Do you want to continue?', 'sendline(y)', None, True, False],
            ['Upgrade aborted', 'sendline()', None, False, False],
        ])
        count = 0
        while count < self.retry_count:
            try:
                d1.process(self.spawn_id, timeout=300)
                count += 1
                logger.info('captured "Upgrade aborted": {} times'.format(count))
                time.sleep(5)
            except:
                logger.info('did not capture Upgrade aborted within 5 minutes')
                break
        assert count < self.retry_count, 'ftd installation failed' \
            ', please check ftd package url: "{}"'.format(self.pkg_image)

        d2 = Dialog([
            ['Do you want to continue with upgrade?', 'sendline(y)', None,
             True, True],
            ["Press 'Enter' to reboot the system.", 'sendline()', None, True,
             True],
            ['The system is going down for reboot NOW', 'sendline()',
              None, False, True],
            #['{}# '.format(self.hostname), 'sendline()', None, False, True],
        ])
        d2.process(self.spawn_id, timeout=2400)

    def ftd_configure(self):
        """Accept EULA, enter new password and configure network for ftd.

        :return: None

        """

        time.sleep(10)
        for i in range(20):
            self.spawn_id.sendline('')
            try:
                self.go_to('any')
            except:
                continue
            else:
                break
        else:
            raise RuntimeError(">>>>>> Switching back to enable mode failed")

        self.execute_and_verify(cmd='show module sfr details | grep ^Status',
                                expected_str='Up',
                                timeout=360,
                                interval=10,
                                timeout_total=7200,
                                retry_count=360)

        self.spawn_id.sendline('session sfr console\n')
        d1 = Dialog([
            ['firepower login: ', 'sendline({})'.format(self.sm.patterns.username),
             None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.default_password),
             None, True, False],
            ['Press <ENTER> to display the EULA: ', 'sendline()', None, True,
             False],
            ['--More--', 'send(q)', None, True, False],
            ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ",
             'sendline(YES)', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=600)

        d2 = Dialog([
            ['Enter new password:',
             'sendline({})'.format(self.sm.patterns.login_password),
             None, True, True],
            ['Confirm new password:',
             'sendline({})'.format(self.sm.patterns.login_password),
             None, True, False],
            ['Do you want to configure IPv4', 'sendline(y)', None, True, False],
            ['Do you want to configure IPv6', 'sendline(n)', None, True, False],
            ['Configure IPv4 via DHCP or manually', 'sendline(manual)', None,
             True, False],
            ['Enter an IPv4 address for the management interface',
             'sendline({})'.format(self.uut_ip), None, True, False],
            ['Enter an IPv4 netmask for the management interface',
             'sendline({})'.format(self.uut_netmask), None, True, False],
            ['Enter the IPv4 default gateway for the management interface',
             'sendline({})'.format(self.uut_gateway), None, True, False],
            ['Enter a fully qualified hostname for this system ',
             'sendline({})'.format(self.hostname), None, True, False],
            ['Enter a comma-separated list of DNS servers or',
             'sendline({})'.format(self.dns_server), None, True, False],
            ['Enter a comma-separated list of search domains or',
             'sendline({})'.format(self.search_domains), None, True, False],
            ['> ', 'sendline()', None, False, False],
        ])
        d2.process(self.spawn_id, timeout=900)

        logger.info('fully installed.')

    def validate_version(self):
        """Checks if the installed version matches a the version in package
        url.

        :return: None

        """

        self.go_to('any')
        self.go_to('fireos_state')

        # check version
        response = self.execute('show version', 30)
        #print('response=' +  response + '<')
        build = re.findall('Build\s(\d+)', response)[0]
        version = re.findall(r'(Version\s){1}([0-9.]+\d)', str(response))[0][1]
        ftd_package_file = self.pkg_image.split('/')[-1]
        if build in ftd_package_file and version in ftd_package_file:
            logger.info('>>>>>> show version result:\n{}\nmatches '
                        'ftd package image: {}'.format(response,
                                                       ftd_package_file))
            logger.info('Installed ftd version validated')
        else:
            logger.error('Exception: not the same version and build')
            raise RuntimeError('>>>>>> show version result:\n{}\ndoes not match '
                               'ftd package image: {}'.format(response,
                                                              ftd_package_file))

    def baseline_elektra(self, http_server, boot_image, pkg_image,
                         uut_ip, uut_netmask, uut_gateway, dns_server,
                         hostname='firepower', search_domains='cisco.com',
                         retry_count=MAX_RETRY_COUNT, ntp_server=None, **kwargs):
        """Baseline device of Elektra, install boot_image, pkg_image and verify
        image installed.

        :param http_server: http server IP
        :param boot_image: in enable mode, download and install boot_image.
                            for example, boot_image='http://10.89.23.80/netboot/ims/Release/6.2.0-362/
                            installers/asasfr-5500x-boot-6.2.0-2.img'
        :param pkg_image: in boot mode, download and install pkg_image.
                            for example, pkg_image='http://10.89.23.80/netboot/ims/Release/6.2.0-362/
                            installers/asasfr-sys-6.2.0-362.pkg'
        :param uut_ip: UUT IP address
        :param uut_netmask: UUT netmask
        :param uut_gateway: UUT gateway
        :param dns_server: DNS server
        :param hostname: hostname of the device to be set
        :param search_domains: search domains, defaulted to 'cisco.com'
        :param retry_count: download retry count, defaulted to MAX_RETRY_COUNT
        :param ntp_server: NTP server delimited by comma, defaulted to None,
                            otherwise the value of ntp_server is - e.g. "ntp.esl.cisco.com"
        :return: None

        """

        publish_kick_metric('device.elektra.baseline', 1)

        self.http_server = http_server
        self.boot_image = boot_image
        self.pkg_image = pkg_image
        self.uut_ip = uut_ip
        self.uut_netmask = uut_netmask
        self.uut_gateway = uut_gateway
        self.dns_server = dns_server
        self.hostname = hostname
        self.search_domains = search_domains
        self.retry_count = retry_count
        self.ntp_server = ntp_server

        if self.sm.current_state is not 'boot_state':
            logger.info('=== Configure terminal')
            self.configure_terminal()

            logger.info('=== Download and set module to boot_image')
            self.download_and_set_boot_module()

        logger.info('=== Boot configure')
        self.boot_configure()

        logger.info('=== SFR install: {}'.format(self.pkg_image))
        self.ftd_install()

        logger.info('=== FTD configure')
        self.ftd_configure()

        logger.info('=== Validate version')
        self.validate_version()

    def configure_ssh_v2(self, gateway, netmask, user, passwd, activation_key=''):
        """Function to configure ssh version 2
        
        :param gateway:
        :param netmask: the ip netmask to apply to the ip
        :param user: username of the user
        :param passwd: the password for user
        :param activation_key: string containing a Encryption-3DES-AES activation key
               e.g.: '7717d15c 7451cf52 b81171b4 979c3404 c51501b3'
        :return: None
        
        """

        self.go_to('config_state')
        self.spawn_id.sendline('crypto key generate rsa modulus 1024')
        d = Dialog([
            ['Keypair generation process begin. Please wait', None, None, True, False],
            ['Do you really want to replace them?', 'sendline(no)', None, True, False],
            [self.sm.patterns.prompt.config_prompt, None, None, False, False],
        ])
        d.process(self.spawn_id, 30)

        cmd_lines1 = 'ssh {} {} diagnostic\n' \
                     'ssh timeout 60\n' \
                     'route diagnostic 0 0 {} 1\n' \
                     'username {} password {}\n' \
                     'aaa authentication ssh console LOCAL'.format(gateway, netmask, gateway, user, passwd)

        logger.info("Configure ssh")
        self.config(cmd_lines1)

        if activation_key:
            logger.info("Apply ssh activation key")
            self.config('activation-key {}'.format(activation_key), 300, True)
        try:
            self.config('ssh version 2', None, True)
        except Exception as e:
            logger.info('SSH version2 could not be activated')
            raise e

    def baseline_by_branch_and_version(self, site, branch, version, uut_ip, uut_netmask,
                                       uut_gateway, dns_server, serverIp='', tftpPrefix='', scpPrefix='', docs='', **kwargs):
        """Baseline elektra using branch and version
        
        :param site: e.g. 'ful', 'ast', 'bgl'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param \**kwargs:
            :Keyword Arguments, any of below optional parameters:
        :param hostname: hostname of the device to be set; defaulted to firepower
        :param search_domains: search domains, defaulted to 'cisco.com'
        :param retry_count: download retry count, defaulted to MAX_RETRY_COUNT
        :param ntp_server: NTP server delimited by comma, defaulted to None,
                            otherwise the value of ntp_server is - e.g. "ntp.esl.cisco.com"
        :return: None
        """

        if KICK_EXTERNAL:
            server_ip = serverIp
            tftp_prefix = tftpPrefix
            scp_prefix = scpPrefix
            files = docs
        else:
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 'elektra', branch, version)

        try:
            boot_file = [file for file in files if file.endswith('.img')][0]
        except Exception as e:
            raise Exception('Got {} while getting boot image file.'.format(e))
        files.remove(boot_file)
        pkg_file = files[0]

        boot_image = "http://{}/{}/{}".format(server_ip, tftp_prefix[len('asa/'):], boot_file)
        pkg_image = "http://{}/{}/{}".format(server_ip, tftp_prefix[len('asa/'):], pkg_file)

        kwargs['http_server'] = server_ip
        kwargs['boot_image'] = boot_image
        kwargs['pkg_image'] = pkg_image
        kwargs['uut_ip'] = uut_ip
        kwargs['uut_netmask'] = uut_netmask
        kwargs['uut_gateway'] = uut_gateway
        kwargs['dns_server'] = dns_server
        self.baseline_elektra(**kwargs)

    def power_cycle(self, power_bar_server, power_bar_port, power_bar_user='admn', power_bar_pwd='admn'):
        """reboots a device from a Power Data Unit equipment.

        :param power_bar_server: comma-separated string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string of power port on the PDU's
        :param power_bar_user: comma-separated string of usernames for power bar servers
        :param power_bar_pwd: comma-separated string of passwords for power bar servers
        :return: status of power cycle result, True or False

        """

        if power_bar_server == "" or power_bar_port == "":
            return None

        return power_cycle_all_ports(power_bar_server, power_bar_port, power_bar_user, power_bar_pwd)
