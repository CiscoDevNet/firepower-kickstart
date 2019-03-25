import logging
import os
import re

try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric
from ..actions.statemachine import WmStateMachine
from ...kp.actions import Kp, KpLine
from ...kp.actions.patterns import KpPatterns

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True
    pass

logger = logging.getLogger(__name__)
MAX_RETRY_COUNT = 3
DEFAULT_TIMEOUT = 60


class Wm(Kp):
    def __init__(self, hostname, login_username='admin',
                 login_password='Admin123', sudo_password='Admin123',
                 *args,
                 **kwargs):
        """
		Wm instance constructor
		:param hostname: hostname of the FXOS
        :param login_username: user name for login
        :param login_password: password for login
        :param sudo_password: root password for FTD
        :kwargs
        :param: 'config_hostname': output of 'show running-config hostname'

		"""

        super(Kp, self).__init__()
        publish_kick_metric('device.wm.init', 1)
        self.set_default_timeout(DEFAULT_TIMEOUT)

        # set hostname, login_username and login_password
        config_hostname = kwargs.get('config_hostname', 'firepower')
        self.patterns = KpPatterns(hostname, login_username, login_password, sudo_password, config_hostname)

        # create the state machine that contains the proper attributes.
        self.sm = WmStateMachine(self.patterns)

        # important: set self.line_class so that a proper line can be created
        # by ssh_console(), etc.
        self.line_class = WmLine
        logger.info("Done: Wm instance created")


class WmLine(KpLine):
    def __init__(self, spawn_id, sm, type, chassis_line=True, timeout=None):
        """Constructor of WmLine instance

		:param spawn_id: spwan connection
		:param sm: state machine instance
		:param type: 'telnet' or 'ssh'
		:param chassis_line: True if ssh console connection is used
                             False if ssh to FTD directly
		:param timeout: in seconds
		"""

        super(KpLine, self).__init__(spawn_id, sm, type, timeout=timeout)
        self.chassis_line = chassis_line
        self.line_type = 'WmLine'
        self.change_password_flag = False

        if self.chassis_line and self.sm.current_state is not 'rommon_state':
            self.init_terminal(determine_state=False)

    def baseline(self, tftp_server, rommon_file,
                 uut_hostname, uut_username, uut_password,
                 uut_ip, uut_netmask, uut_gateway,
                 dns_servers, search_domains,
                 fxos_url, ftd_version, file_server_password="",
                 power_cycle_flag=False,
                 mode='local',
                 uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                 manager=None, manager_key=None, manager_nat_id=None,
                 firewall_mode='routed', timeout=3600, reboot_timeout=300):

        """ Method used to baseline the Westminster device.
		Does the following steps:
		- assigns an ip address from mgmt network to the sensor in rommon mode
		- tftp and boots an fxos image
		- from within FXOS downloads and installs a FTD image

        :param tftp_server: tftp server to get rommon and fxos images
        :param rommon_file: rommon build,
               e.g. 'asa/cache/Development/6.4.0-10138/installers/fxos-k8-fp2k-lfbff.82.5.1.893i.SSB'
        :param uut_hostname: hostname of the FTD
        :param uut_username: User Name to login to FTD
        :param uut_password: Password to login to FTD
        :param uut_ip: Device IP Address to access TFTP Server
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_servers: DNS Servers
        :param search_domains: Search Domains
        :param fxos_url: FXOS+FTD image url,
               e.g. 'tftp://10.89.23.30/asa/cache/Development/6.4.0-10138/installers/
               cisco-ftd-fp1k.6.4.0-10138.SSB'
        :param ftd_version: ftd version, e.g. '6.4.0-10138'
        :param file_server_password: if use scp protocol, this is the password to
               download the image
        :param power_cycle_flag: if True power cycle the device before baseline
        :param mode: the manager mode ('local', 'remote')
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param manager: FMC to be configured for registration
        :param manager_key: Registration key
        :param manager_nat_id: Registration NAT Id
        :param firewall_mode: the firewall mode ('routed', 'transparent', 'ngips')
        :param timeout: in seconds; time to wait for installing the security package;
                        default value is 3600s
        :param reboot_timeout: in seconds; time to wait for system to restart;
                        default value is 300s
        :return: None

        """

        publish_kick_metric('device.wm.baseline', 1)
        super().baseline_fp2k_ftd(tftp_server=tftp_server,
                                  rommon_file=rommon_file, uut_hostname=uut_hostname,
                                  uut_username=uut_username, uut_password=uut_password,
                                  uut_ip=uut_ip, uut_netmask=uut_netmask, uut_gateway=uut_gateway,
                                  dns_servers=dns_servers, search_domains=search_domains,
                                  fxos_url=fxos_url, ftd_version=ftd_version,
                                  file_server_password=file_server_password,
                                  power_cycle_flag=power_cycle_flag, mode=mode,
                                  uut_ip6=uut_ip6, uut_prefix=uut_prefix, uut_gateway6=uut_gateway6,
                                  manager=manager, manager_key=manager_key,
                                  manager_nat_id=manager_nat_id, firewall_mode=firewall_mode, timeout=timeout,
                                  reboot_timeout=reboot_timeout)

    def baseline_by_branch_and_version(self, site, branch, version,
                                       uut_ip, uut_netmask, uut_gateway,
                                       dns_server='', serverIp='', tftpPrefix='',
                                       scpPrefix='', docs='', **kwargs):
        """Baseline Westminster device by specifying branch and version.
		Looks for needed files on devit-engfs server, copies them to the local kick server
		and uses them to baseline the device.

		:param site: e.g. 'ful', 'ast', 'bgl'
		:param branch: branch name, e.g. 'Release', 'Feature', 'Development'
		:param version: software build-version, e,g, 6.4.0-10138
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
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 'wm', branch, version)

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

        self.baseline(**kwargs)
