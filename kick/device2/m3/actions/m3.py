import logging
import time
import re

logger = logging.getLogger(__name__)

from unicon.eal.expect import Spawn
from unicon.eal.dialogs import Dialog
from .patterns import M3Patterns
from .statemachine import M3Statemachine
from ...fmc.actions import Fmc, FmcLine

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

try:
    from kick.kick_constants import KickConsts
except ImportError:
    from kick.miscellaneous.credentials import KickConsts


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10
MAX_TIME_INSTALL = 7200
SSH_DEFAULT_TIMEOUT = 90


class M3(Fmc):
    def __init__(self, hostname='firepower',
                 login_username='admin',
                 login_password=KickConsts.DEFAULT_PASSWORD,
                 sudo_password=KickConsts.DEFAULT_PASSWORD,
                 cimc_hostname='',
                 *args,
                 **kwargs):
        """Constructor for FMC M3.

        :param hostname: fmc hostname or fqdn e.g. FS2000-01 or FS2000-01.cisco.com
        :param login_username: user name for login
        :param login_password: password for login
        :param fmc_root_password: root password for FMC
        :param cimc_hostname: host name in prompt in cimc scope mode e.g. C220-FCH1948V1N3
        :return: None

        """

        publish_kick_metric('device.m3.init', 1)

        self.patterns = M3Patterns(
            hostname=hostname,
            login_username=login_username,
            login_password=login_password,
            sudo_password=sudo_password,
            cimc_hostname=cimc_hostname)
        self.sm = M3Statemachine(self.patterns)
        self.line_class = M3Line

        self.set_default_timeout(DEFAULT_TIMEOUT)

    def ssh_cimc(self, ip, port,
                 cimc_username='admin',
                 cimc_password='Admin123',
                 timeout=None):
        """This is the method to login to FMC via CIMC Interface.

        :param ip: FMC CIMC IP
        :param port: ssh port for FMC CIMC
        :param cimc_username: ssh username for FMC CIMC
        :param cimc_password: ssh password for FMC CIMC
        :param timeout: timeout for ssh login
        :return: ssh_line

        """

        publish_kick_metric('device.m3.ssh', 1)
        if not timeout:
            timeout = self.default_timeout
        self.spawn_id = Spawn('ssh -o UserKnownHostsFile=/dev/null'\
                              ' -o StrictHostKeyChecking=no '\
                              '-l {} -p {} {}'.format(cimc_username, port, ip))
        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['[Pp]assword:', 'sendline({})'.format(cimc_password),
             None, True, False],
            [self.sm.get_state('mio_state').pattern, None, None, False, False],
        ])
        try:
            d1.process(self.spawn_id, timeout=60)
            self.spawn_id.sendline()
            self.spawn_id.sendline()
        except TimeoutError:
            pass
        ssh_line = self.line_class(self.spawn_id, self.sm, 'ssh_cimc', timeout=timeout)

        logger.debug("Done: connection created by ssh {} {}".format(ip, port))
        return ssh_line

    def reboot_cimc(self, ip, port,
                 cimc_username='admin',
                 cimc_password='Admin123',
                 retries=10, interval=120):
        """This is the method to reboot cimc

        :param ip: FMC CIMC IP
        :param port: ssh port for FMC CIMC
        :param cimc_username: ssh username for FMC CIMC
        :param cimc_password: ssh password for FMC CIMC
        :param retries: polling attempts to check if CIMC is back
        :param interval: polling interval
        :return: True/False to indicate sucess

        """

        self.ssh_cimc(ip, port, cimc_username, cimc_password)
        self.spawn_id.sendline("top")
        self.spawn_id.sendline("scope cimc")
        d1 = Dialog([
            ['/cimc.*#','sendline(reboot)', None, True, False],
            ['Continue?.*', 'sendline(y)', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=30)
        self.spawn_id.sendline()
        self.spawn_id.sendline()
        logger.info("Sleeping for 60 secs..")
        time.sleep(60)
        while retries > 0:
            logger.info("Wait for CIMC to be back. Attempt: {}".format(retries))
            try:
                line = self.ssh_cimc(ip, port, cimc_username, cimc_password)
                if line is not None:
                    line.disconnect()
                    break
            except:
                logger.info("CIMC did not respond")
                time.sleep(interval)
                retries -= 1
        if retries == 0:
            logger.error("CIMC did not come back after reboot")
            return False
        else:
            return True


class M3Line(FmcLine):

    def baseline_fmc_m3(self, iso_map_name, http_link, iso_file_name,
                        mgmt_ip, mgmt_netmask, mgmt_gateway, timeout=None,
                        mgmt_ip6=None, mgmt_prefix=None, mgmt_gateway6=None,
                        change_password=True):
        """Baseline FMC M3 on CIMC connection.

        :param iso_map_name: map name for command map-www, e.g. 'myiso'
        :param http_link: http link for the share, e.g. 'http://172.23.47.63'
        :param iso_file_name: iso filename under http_link, e.g. 'Sourcefire_Defense_Center_M4-6.2.0-362-Autotest.iso'
        :param mgmt_ip: management interface ip address
        :param mgmt_netmask: management interface netmask
        :param mgmt_gateway: management interface gateway
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param mgmt_ip6: management interface IPv6 Address
        :param mgmt_prefix: management interface IPv6 Prefix
        :param mgmt_gateway6: management interface IPv6 Gateway
        :param change_password: Flag to change the password after baseline
        :return: None

        """
        publish_kick_metric('device.m3.baseline', 1)
        # set baseline timeout
        self.set_installation_timeouts(timeout)
        logger.info('Baseline fmc m3 ')
        logger.info('=== Remove network share mapping')
        self.execute('scope vmedia')
        output = self.execute('show mappings | grep CD')
        matched = re.split('\s+', output.split('\r\n')[-1])
        if matched and matched[0] is not '|':
            map_name = matched[0]
            self.execute('unmap {}'.format(map_name), timeout=60)

        logger.info('=== Set map-www')
        map_cmd = 'map-www {} {} {}'.format(iso_map_name, http_link, iso_file_name)
        self.spawn_id.sendline(map_cmd)
        # Set username empty
        d1 = Dialog([
            ['username:', 'sendline()', None, True, False],
            [self.sm.get_state('mio_state').pattern, None, None, False, False],
        ])
        d1.process(self.spawn_id)

        logger.info('=== Validate network share mapping')
        self.execute_and_verify(cmd='show mappings detail',
                                expected_str='Map-Status: OK',
                                interval=10,
                                timeout_total=120,
                                retry_count=10)

        logger.info('=== Validate sol: enabled, baud-rate and com0')
        self.execute('top')
        self.execute('scope sol')
        self.execute_and_verify(cmd='show detail',
                                expected_str='Enabled: yes',
                                cmd_set_config='set enabled yes')
        self.execute_and_verify(cmd='show detail',
                                expected_str='Baud Rate\(bps\): 9600',
                                cmd_set_config='set baud-rate 9600')
        self.execute_and_verify(cmd='show detail',
                                expected_str='Com Port: com0',
                                cmd_set_config='set comport com0')

        logger.info('=== Validate chassis operational profile')
        self.execute('top')
        self.execute('scope chassis')
        self.execute('scope flexflash FlexFlash-0')
        self.execute('scope operational-profile')
        self.execute_and_verify(cmd='show detail',
                                expected_str='Host Accessible VDs: HV',
                                cmd_set_config='set virtual-drives-enabled HV')

        logger.info('=== Validate chassis virtual-drive-count')
        self.execute('top')
        self.execute('scope chassis')
        slot_info = self.execute('show storageadapter')
        slot_list = re.findall('SLOT-.', slot_info)
        for slot in slot_list:
            self.execute('scope storageadapter {}'.format(slot))
            self.execute_and_verify(cmd='show virtual-drive-count',
                                expected_str='Virtual Drive Count: 1')

        logger.info('=== Validate bios: Boot Order and Boot Override Priority')
        self.execute('top')
        self.execute('scope bios')
        self.execute_and_verify(cmd='show detail',
                                expected_str='Boot Order: CDROM,HDD,PXE,FDD,EFI',
                                cmd_set_config='set boot-order cdrom,hdd,pxe,fdd,efi')
        self.execute_and_verify(cmd='show detail',
                                expected_str='Boot Override Priority:\n',
                                cmd_set_config='set boot-override None',
                                matched_whole_line=True)
        self.execute('top')
        self.execute('commit', timeout=60)

        logger.info('=== Run bios: bios-setup-default')
        self.execute('scope bios')
        self.spawn_id.sendline('bios-setup-default')
        d2 = Dialog([
            ['Continue', 'sendline({})'.format('y'), None, False, False],
        ])
        d2.process(self.spawn_id)

        logger.info('=== Run advanced: settings')
        self.execute('scope advanced')
        self.execute('set IntelVT Disabled')
        self.execute('set BaudRate 9600')
        self.execute('set ConsoleRedir COM_0')
        self.execute('set EnhancedIntelSpeedStep Disabled')
        self.execute('top')
        self.spawn_id.sendline('commit')

        logger.info('=== Reboot the system, connect host, waiting ...')
        d3 = Dialog([
            ['Do you want to reboot the system',
             'sendline({})'.format('y'),
             None, False, False],
        ])
        try:
            d3.process(self.spawn_id, timeout=300)
        except:
            logger.info('d3 dialog did not appear')
            # Handle the case there is no such question prompt
            pass
        self.spawn_id.sendline('connect host')
        d3_2 = Dialog([
            ['CISCO Serial Over LAN', 'sendline()', None, False, False]
        ])
        try:
            d3_2.process(self.spawn_id, timeout=30)
        except:
            pass
        d4 = Dialog([
            ['Enter selection', 'sendline({})'.format('2'), None, True, False],
            ['Restore the system?', 'sendline({})'.format('yes'), None, True, False],
            ['Delete license and network settings?', 'sendline({})'.format('no'), None, True, False],
            ['Are you sure?', 'sendline({})'.format('yes'), None, True, False],
            ['Press enter to reboot the system', 'sendline()', None, True, False],
            ['.*login:', 'sendline({})'.format(self.sm.patterns.username),
             None, True, False],
            ['Password:', 'sendline({})'.format(self.sm.patterns.default_password),
             None, False, False],
        ])
        d4.process(self.spawn_id, timeout=self.installation_timeout)

        logger.info('=== Image has been loaded successfully')

        logger.info('=== Validate mysql process')
        self.sm.update_cur_state('admin_state')
        self.validate_mysql_process()

        logger.info('=== Configure network')
        self.configure_network(mgmt_gateway, mgmt_ip, mgmt_netmask,
                               mgmt_ip6, mgmt_prefix, mgmt_gateway6,
                               change_password)

        logger.info('=== Validate version')
        self.validate_version(iso_file_name=iso_file_name)

        logger.info('Installation completed successfully.')

    def baseline_by_branch_and_version(self, site, branch, version, uut_ip, uut_netmask,
                                       uut_gateway, iso_file_type='Restore', timeout=None,
                                       cimc=True, serverIp='', tftpPrefix='', scpPrefix='', docs='', **kwargs):
        """Baseline M3 on CIMC connection by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the local kick server
        and use them to baseline the device.

        :param site: e.g. 'ful', 'ast', 'bgl'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param uut_ip: ip address of management interface
        :param uut_netmask: netmask of management interface
        :param uut_gateway: gateway ip address of mgmt interface
        :param iso_file_type: 'Autotest' or 'Restore'; defaulted to 'Restore'
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param cimc: Flag to baseline using CIMC or serial
        **kwargs:
        :param power_cycle_flag: True power cycle before baseline, False otherwise
        :param pdu_ip: string of IP addresses of the PDU's
        :param pdu_port: string of power port on the PDU's
        :param pdu_user: usernames for power bar servers
        :param pdu_pwd: passwords for power bar servers
        :param mgmt_ip6: management interface IPv6 Address
        :param mgmt_prefix: management interface IPv6 Prefix
        :param mgmt_gateway6: management interface IPv6 Gateway
        :param change_password: Flag to change the password after baseline
        :param ipv4_mode: IPv4 configuration mode - 'static' or 'dhcp';
                         default set to 'static'
        :param ipv6_mode: IPv6 configuration mode - 'dhcp', 'router' or 'manual'
                          default set to 'manual'
        :param dns_servers: a comma-separated string of DNS servers
        :param search_domains: a comma-separated string of search domains
                                default set to 'cisco.com'
        :param ntp_servers: a comma-separated string of NTP servers
        """

        if KICK_EXTERNAL:
            server_ip = serverIp
            tftp_prefix = tftpPrefix
            scp_prefix = scpPrefix
            files = docs
        else:
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 'm3', branch, version,
                                                                               iso=iso_file_type)
        if not files[0]:
            raise Exception('M3 iso file not found on server')

        kwargs['mgmt_ip'] = uut_ip
        kwargs['mgmt_netmask'] = uut_netmask
        kwargs['mgmt_gateway'] = uut_gateway
        kwargs['timeout'] = timeout
        if cimc:
            kwargs['iso_map_name'] = 'myiso'
            kwargs['http_link'] = 'http://{}'.format(server_ip)
            kwargs['iso_file_name'] = '{}/{}'.format(tftp_prefix[len('asa'):], files[0])
            self.baseline_fmc_m3(**kwargs)
        else:
            kwargs['iso_url'] = 'http://{}/{}/{}'.format(server_ip, tftp_prefix[len('asa'):], files[0])
            self.baseline_using_serial(**kwargs)

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

    def baseline_using_serial(self, iso_url, mgmt_ip, mgmt_netmask, mgmt_gateway, mgmt_intf="eth0",
                              timeout=None, power_cycle_flag=False, pdu_ip='', pdu_port='',
                              pdu_user='admn', pdu_pwd='admn',
                              mgmt_ip6=None, mgmt_prefix=None, mgmt_gateway6=None,
                              change_password=True, ipv4_mode='static', ipv6_mode='',
                              dns_servers='', search_domains='', ntp_servers=''):
        """Baseline M3 device through its physical serial port connection.

        :param iso_url: http url of iso image
                http://10.83.65.25/cache/Development/6.2.3-1612/iso/Sourcefire_Defense_Center_M4-6.2.3-1612-Restore.iso
        :param mgmt_ip: management interface ip address
        :param mgmt_netmask: management interface netmask
        :param mgmt_intf: management interface gateway
        :param mgmt_gateway: management interface gateway
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param power_cycle_flag: True power cycle before baseline, False otherwise
        :param pdu_ip: string of IP addresses of the PDU's
        :param pdu_port: string of power port on the PDU's
        :param pdu_user: usernames for power bar servers
        :param pdu_pwd: passwords for power bar servers
        :param mgmt_ip6: management interface IPv6 Address
        :param mgmt_prefix: management interface IPv6 Prefix
        :param mgmt_gateway6: management interface IPv6 Gateway
        :param change_password: Flag to change the password after baseline
        :param ipv4_mode: IPv4 configuration mode - 'static' or 'dhcp'
        :param ipv6_mode: IPv6 configuration mode - 'dhcp', 'router' or 'manual'
        :param dns_servers: a comma-separated string of DNS servers
        :param search_domains: a comma-separated string of search domains
        :param ntp_servers: a comma-separated string of NTP servers
        :return:
        """

        publish_kick_metric('device.m3.baseline', 1)
        # set baseline timeout
        self.set_installation_timeouts(timeout)

        # network configuration flag used to indicate if cli configuration is
        # still needed after baseline
        network_config = False

        if power_cycle_flag:
            self.power_cycle(pdu_ip, pdu_port, pdu_user, pdu_pwd)
            d0 = Dialog([
                ['boot:', None, None, False, False],
            ])
            d0.process(self.spawn_id, timeout=600)
            self._boot_selection(self.spawn_id, self.sm.patterns.prompt.lilo_boot_menu_prompt)
            # self.spawn_id.expect(self.sm.patterns.prompt.lilo_boot_menu_prompt, timeout=120)

            self._move_from_lilo_boot_menu_to_lilo_os()
        else:
            self._try_to_goto_prompt(prompt='any')
            # Raise exception if device is not in below states
            baseline_valid_states = ["prelogin_state", "admin_state", "sudo_state", "lilos_state", "lilobootmenu_state",
                                     "fireos_state"]

            if self.sm.current_state not in baseline_valid_states:
                msg = "Baseline Serial function needs one of the valid state from %s" % baseline_valid_states
                logger.error(msg)
                raise RuntimeError(msg)

            # Bring the system to liloos_state
            if self.sm.current_state is "lilobootmenu_state":
                self._move_from_lilo_boot_menu_to_lilo_os()

            # go to sudo_state
            elif self.sm.current_state in ["admin_state", "prelogin_state", "fireos_state"]:
                self.go_to('sudo_state')

            # reboot the device, select 3-System Restore Mode and enter lilo_boot state
            if self.sm.current_state is 'sudo_state':
                self.spawn_id.sendline("reboot")

                d0 = Dialog([
                    ['reboot: machine restart', None, None, True, False],
                    ['boot:', None, None, False, False],
                ])
                d0.process(self.spawn_id, timeout=600)

                self._boot_selection(self.spawn_id, self.sm.patterns.prompt.lilo_boot_menu_prompt)
                # self.spawn_id.expect(self.sm.patterns.prompt.lilo_boot_menu_prompt, timeout=120)

                # activate console
                self._move_from_lilo_boot_menu_to_lilo_os()

        # Here means device is in LILO OS State
        self.sm.update_cur_state('lilos_state')

        # Try install seq with retry for 5 times
        for i in range(1, 5):
            ret = self._install_from_iso(iso_url=iso_url, uut_ip=mgmt_ip, uut_netmask=mgmt_netmask,
                                         uut_gateway=mgmt_gateway, mgmt_intf=mgmt_intf,
                                         timeout=self.installation_timeout)

            if ret == 0:
                network_config = self.configuration_wizard(ipv4_mode=ipv4_mode, ipv6_mode=ipv6_mode,
                                                           ipv4=mgmt_ip, ipv4_netmask=mgmt_netmask,
                                                           ipv4_gateway=mgmt_gateway, ipv6=mgmt_ip6,
                                                           ipv6_prefix=mgmt_prefix, ipv6_gateway=mgmt_gateway6,
                                                           dns_servers=dns_servers, search_domains=search_domains,
                                                           ntp_servers=ntp_servers)
                break

            # If the device moved back to lilo boot menu. Try to go to lilo os and try install again
            if ret == 1:
                self._move_from_lilo_boot_menu_to_lilo_os()

        # Raise error in all the attempts failed
        if i >= 5:
            msg = "Failed to install M3 using serial for %s times" % i
            logger.error(msg)
            raise RuntimeError(msg)

        time.sleep(60)

        logger.info('=== Validate mysql process')
        self.validate_mysql_process()

        if not network_config:
            logger.info('=== Configure network and change default password')
            self.configure_network(mgmt_gateway, mgmt_ip, mgmt_netmask,
                                   mgmt_ip6, mgmt_prefix, mgmt_gateway6,
                                   change_password)

        logger.info('=== Validate version')
        iso_file_name = iso_url.split('/')[-1]
        self.validate_version(iso_file_name=iso_file_name)

        logger.info('Installation completed successfully.')

    def _boot_selection(self, spawn, prompt):

        spawn.send("\t")
        spawn.expect('boot:')
        spawn.send("\t")
        spawn.expect('boot:')
        spawn.send("System_Restore\r")
        d1 = Dialog([
            ['1. Load with serial console', None, None, True, False],
            ['boot:', 'sendline({})'.format('1'), None, True, False],
            [prompt, None, None, False, False],
        ])
        d1.process(spawn, timeout=300)

