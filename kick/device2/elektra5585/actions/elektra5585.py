"""Library to load new image on an Elektra 5585 SFR blade.

We require a file server to be co-located with the device. This file
server has both the rommon_image and the pkg_image mounted.
Elektra will first break into rommon, tftp the
rommon_image and boot from it into Elektra boot CLI. Then it will do an HTTP
copy of pkg_image to boot up into a fully functional device. This second
step takes a long time (~30 min), as it will run a lot of scripts.

The file server is a PXE server in each site, defined in gcp_constants.py.

"""
import re
import time
import logging
logger = logging.getLogger(__name__)

from unicon.eal.expect import TimeoutError
from unicon.eal.dialogs import Dialog
from ...general.actions.basic import BasicDevice, BasicLine
from ...general.actions.power_bar import power_cycle_all_ports

try:
    import kick.graphite.graphite as graphite
except ImportError:
    import kick.metrics.metrics as graphite

MAX_RETRY_COUNT = 3


class Elektra5585(BasicDevice):
    def __init__(self, hostname='firepower', login_password='Admin123',
                 sudo_password='Admin123', enable_password='', *args, **kwargs):
        """Constructor for Elektra5585.

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

        graphite.publish_kick_metric('device.elektra5585.init', 1)
        from .patterns import Elektra5585Patterns
        self.patterns = Elektra5585Patterns(hostname, login_password, sudo_password, enable_password)

        # create the state machine that contains the proper attributes.
        from .statemachine import Elektra5585Statemachine
        self.sm = Elektra5585Statemachine(self.patterns)

        # important: set self.line_class so that a proper line can be created
        # by ssh_console(), etc.
        self.line_class = Elektra5585Line


class Elektra5585Line(BasicLine):
    def __init__(self, spawn, sm, type, timeout=None):
        """ Constructor of Elektra5585

        :param spawn: spawn_id of the line
        :param sm: object of statemachine
        :param type: line type, e.g. 'ssh', 'telnet'
        :return: object of the line

        """

        try:
            super().__init__(spawn, sm, type, timeout)
        except:
            # Handle boot loop
            pass
            logger.info('=== Failed to go_to("any") '
                        'try to drop device to rommon.')
            count = 0
            while count < MAX_RETRY_COUNT:
                try:
                    self.rommon_go_to()
                    self.sm.update_cur_state('rommon_state')
                    logger.info('=== Dropped device to rommon.')
                    break
                except:
                    pass
                    count += 1
            assert count < MAX_RETRY_COUNT, '=== Could not drop device ' \
                                            'to rommon, assert ...'

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

        :param power_bar_server: comma-separated string of IP addresses of the PDU's
        :param power_bar_port: comma-separated string of power port on the PDU's
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

        logger.info('Wait for device to be up running ...')
        if wait_until_device_is_on:
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

    def rommon_go_to(self):
        """Go to rommon mode.

        :return: None

        """

        # break into rommon
        d1 = Dialog([
            ['Use SPACE to begin boot immediately.',
             'sendline({})'.format(chr(27)), None, False, False],
        ])
        d1.process(self.spawn_id, timeout=900)
        time.sleep(10)
        logger.info('In rommon mode')

    def rommon_configure(self):
        """In ROMMON mode, set network, tftp info and rommon image For Kenton.

        :return: None

        """

        logger.info('add rommon config')
        es_list = [
            ['rommon', 'ADDRESS={}'.format(self.uut_ip)],
            ['rommon', 'SERVER={}'.format(self.rommon_tftp_server)],
            ['rommon', 'IMAGE={}'.format(self.rommon_image)],
            ['rommon', 'GATEWAY={}'.format(self.uut_gateway)],
            ['rommon', 'PORT=Management0/0'],
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
            ['Overwrite \(y/n\)', 'sendline(y)', None, True, False],
            ['login:', 'sendline()', None, False, False],
        ])
        try:
            d1.process(self.spawn_id, timeout=timeout)
            self.spawn_id.sendline()
        except:
            logger.info("=== Rommon file download failed, raise runtime error. ")
            raise RuntimeError(
                ">>>>>> Download failed. Please check details - "
                "tftp_server: {}, image file: {}".format(self.rommon_tftp_server,
                                                         self.rommon_image))

        logger.info("=== Rommon file was installed successfully.")

    def firepower_boot_configure(self):
        """In boot CLI mode, set device network info, DNS server and domain.

        :return: None

        """

        d1 = Dialog([
            ['login:', 'sendline(admin)', None, True, False],
            ['Password: ', 'sendline({})'.format(self.sm.patterns.default_password),
             None, True, False],
            ['-boot>', 'sendline(setup)', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=30)
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
            ['Do you want to enable the NTP service', 'sendline({})'.format(set_ntp_server),
             None, True, False],
            ['Enter the NTP servers separated by commas', 'sendline({})'.format(self.ntp_server),
             None, True, False],
            ['Do you want to enable the NTP symmetric key authentication', 'sendline(n)',
             None, True, False],
            ['Apply the changes', 'sendline(y)', None, True, False],
            ['Press ENTER to continue...', 'sendline()', None, True, False],
            ['-boot>', 'sendline()', None, False, False],
        ])
        d2.process(self.spawn_id, timeout=120)

    def firepower_install(self):
        """Perform ping test and verify the network connectivity to TFTP server.
        Install Elektra pkg image Enter device network info, hostname, and firewall
        mode.

        :return: None

        """

        for i in range(20):
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
        assert count < self.retry_count, 'elektra installation failed' \
            ', please check elektra package url: "{}"'.format(self.pkg_image)

        d2 = Dialog([
            ['Do you want to continue with upgrade?', 'sendline(y)', None,
             True, True],
            ["Press 'Enter' to reboot the system.", 'sendline()', None, True,
             True],
            ['Use SPACE to begin boot immediately.', 'send(" ")', None, True,
             True],
            ['firepower login: ', 'sendline()', None, False, False],
        ])
        d2.process(self.spawn_id, timeout=3900)

        # Allow install processes to finish
        time.sleep(180)

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
        d4.append(['Enter a fully qualified hostname for this system ',
                   'sendline({})'.format(self.hostname), None, True, False])
        d4.append(['Enter a comma-separated list of DNS servers or',
                   'sendline({})'.format(self.dns_server), None, True, False])
        d4.append(['Enter a comma-separated list of search domains or',
                   'sendline({})'.format(self.search_domains), None, True, False])
        d4.append(['> ', 'sendline()', None, False, False])
        d4.process(self.spawn_id, timeout=900)

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
        package_file = self.pkg_image.split('/')[-1]
        if (build in package_file) and (version in package_file):
            logger.info('>>>>>> show version result:\n{}\nmatches '
                        'elektra package image: {}'.format(response,
                                                           package_file))
            logger.info('Installed elektra version validated')
        else:
            logger.error('Exception: not the same version and build')
            raise RuntimeError('>>>>>> show version result:\n{}\ndoes not match '
                               'elektra package image: {}'.format(response,
                                                                  package_file))

    def baseline_elektra_5585(self, rommon_tftp_server, pkg_image,
                              uut_ip, uut_netmask, uut_gateway, rommon_image, dns_server,
                              hostname='firepower', search_domains='cisco.com',
                              retry_count=MAX_RETRY_COUNT,
                              power_cycle_flag=False, pdu_ip='', pdu_port='',
                              pdu_user='admn', pdu_pwd='admn', ntp_server=None,
                              uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                              manager=None, manager_key=None, manager_nat_id=None, **kwargs):
        """Install rommon image and Elektra pkg image on SFR blade.

        :param rommon_tftp_server: TFTP Server IP Address
        :param pkg_image: Elektra image to be transferred via HTTP,
            e.g. 'http://192.168.0.50/Release/6.2.3-10697/installers/asasfr-sys-6.2.3-10697.pkg'
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param rommon_image: boot image under /tftpboot to be transferred via TFTP,
            e.g. 'netboot/elektra-boot-images/6.2.3/6.2.3-2/asasfr-boot-6.2.3-2.img'
        :param dns_server: DNS server
        :param hostname: hostname to be set
        :param search_domains: search domains delimited by comma,
            defaulted to 'cisco.com'
        :param retry_count: download retry count, defaulted to MAX_RETRY_COUNT
        :param power_cycle_flag: True power cylce before baseline, False otherwise
        :param pdu_ip: PDU IP
        :param pdu_port: PDU Port
        :param pdu_user: PDU admn
        :param pdu_pwd: PDU pwd
        :param ntp_server: NTP server delimited by comma, defaulted to None,
            otherwise the value of ntp_server is - e.g. "ntp.esl.cisco.com"
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param timeout: in seconds; time to wait for fetching the boot image from TFTP server;
                        defaulted to 600s
        :return: None

        """

        logger.info('Starting baseline')
        graphite.publish_kick_metric('device.elektra5585.baseline', 1)
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
        self.manager = manager
        self.manager_key = manager_key
        self.manager_nat_id = manager_nat_id
        tftptimeout = kwargs.get('timeout', 600)

        if not (self.sm.current_state in ['rommon_state', 'boot_state', 'pkglogin_state']):
            if not power_cycle_flag:
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

        if self.sm.current_state is 'pkglogin_state':
            self.go_to('boot_state')

        if self.sm.current_state is 'boot_state':
            logger.info('Device is in boot_state, drop the device to rommon.')
            self.spawn_id.sendline('system reload')
            d1 = Dialog([
                ['Are you sure you want to reload the system',
                 'sendline(y)', None, False, False],
            ])
            d1.process(self.spawn_id, timeout=30)
            self.rommon_go_to()

        logger.info('Rommon configure.')
        self.rommon_configure()

        logger.info('tftpdnld - tftp server: {}, '
                    'rommon image: {} ...'.format(rommon_tftp_server, rommon_image))
        self.rommon_boot(tftptimeout)
        self.go_to('any')
        logger.info('firepower boot configure ...')
        self.firepower_boot_configure()
        logger.info('Install image: {} ...'.format(pkg_image))
        self.firepower_install()
        self.go_to('any')
        if self.manager is not None:
            logger.info('Configure manager')
            self.configure_manager()
        logger.info('Validate version installed')
        self.validate_version()
        logger.info('Installation completed successfully.')
