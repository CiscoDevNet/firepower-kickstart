
from ...m4.actions import M4, M4Line

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


import logging

logger = logging.getLogger(__name__)


class M5(M4):
    def __init__(self, hostname='firepower', login_username='admin',
                 login_password=KickConsts.DEFAULT_PASSWORD,
                 sudo_password=KickConsts.DEFAULT_PASSWORD,
                 cimc_hostname='', *args, **kwargs):
        """Constructor for FMC M5.

        :param hostname: fmc hostname or fqdn e.g. FS2000-01 or FS2000-01.cisco.com
        :param login_username: user credentials
        :param login_password: device login password with user name 'admin'
        :param sudo_password: device sudo password for 'root'

        """

        super().__init__(hostname, login_username,
                         login_password, sudo_password, cimc_hostname)
        publish_kick_metric('device.m5.init', 1)

        self.line_class = M5Line


class M5Line(M4Line):
    def __init__(self, spawn_id, sm, type, timeout=None):
        super().__init__(spawn_id, sm, type, timeout)
        self.metric = 'm5'

    def baseline_fmc_m5(self, iso_map_name, http_link, iso_file_name,
                        mgmt_ip, mgmt_netmask, mgmt_gateway, timeout=None,
                        mgmt_ip6=None, mgmt_prefix=None, mgmt_gateway6=None,
                        change_password=True):
        """Baseline M5 through CIMC connection.

        :param iso_map_name: map name for command map-www, e.g. 'myiso'
        :param http_link: http link for the share, e.g. 'http://10.83.65.25'
        :param iso_file_name: iso filename under http_link,
               e.g. '/cache/Development/6.3.0-10558/iso/Sourcefire_Defense_Center-6.3.0-10558-Autotest.iso
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

        super().baseline_fmc_m4(iso_map_name=iso_map_name,
                                http_link=http_link, iso_file_name=iso_file_name,
                                mgmt_ip=mgmt_ip, mgmt_netmask=mgmt_netmask,
                                mgmt_gateway=mgmt_gateway, timeout=timeout,
                                mgmt_ip6=mgmt_ip6, mgmt_prefix=mgmt_prefix,
                                mgmt_gateway6=mgmt_gateway6,
                                change_password=change_password)

        # workaround to enable admin user
        # to be removed when issue is solved
        self._enable_admin_user()

    def _enable_admin_user(self):
        """Temporary workaround to access CIMC with admin user
        :return:
        """
        self.go_to("mio_state")
        self.execute("top")
        self.execute("scope user 1")
        self.execute("set enabled yes")
        self.execute("commit")

    def baseline_by_branch_and_version(self, site, branch, version, uut_ip, uut_netmask,
                                       uut_gateway, iso_file_type='Restore', timeout=None,
                                       mgmt_ip6=None, mgmt_prefix=None, mgmt_gateway6=None,
                                       change_password=True, cimc=True, serverIp='', tftpPrefix='', scpPrefix='', docs='', **kwargs):
        """Baseline of FMC M5 through CIMC connection by branch and version using PXE servers.
        Looks for needed files on devit-engfs, copies them to the local kick server
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
        :param mgmt_ip6: management interface IPv6 Address
        :param mgmt_prefix: management interface IPv6 Prefix
        :param mgmt_gateway6: management interface IPv6 Gateway
        :param change_password: Flag to change the password after baseline
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
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 'm5', branch, version,
                                                                               iso=iso_file_type)
        if not files[0]:
            raise Exception('M5 iso file not found on server')

        kwargs['mgmt_ip'] = uut_ip
        kwargs['mgmt_netmask'] = uut_netmask
        kwargs['mgmt_gateway'] = uut_gateway
        kwargs['mgmt_ip6'] = mgmt_ip6
        kwargs['mgmt_prefix'] = mgmt_prefix
        kwargs['mgmt_gateway6'] = mgmt_gateway6
        kwargs['timeout'] = timeout
        kwargs['change_password'] = change_password
        if cimc:
            kwargs['iso_map_name'] = 'myiso'
            kwargs['http_link'] = 'http://{}'.format(server_ip)
            kwargs['iso_file_name'] = '{}/{}'.format(tftp_prefix[len('asa'):], files[0])
            self.baseline_fmc_m5(**kwargs)
        else:
            kwargs['iso_url'] = 'http://{}/{}/{}'.format(server_ip, tftp_prefix[len('asa'):], files[0])
            self.baseline_using_serial(**kwargs)

    def baseline_using_serial(self, iso_url, mgmt_ip, mgmt_netmask, mgmt_gateway, mgmt_intf="eth0", timeout=None,
                              power_cycle_flag=False, pdu_ip='', pdu_port='',
                              pdu_user='admn', pdu_pwd='admn',
                              mgmt_ip6=None, mgmt_prefix=None, mgmt_gateway6=None,
                              change_password=True, ipv4_mode='static', ipv6_mode='',
                              dns_servers='', search_domains='', ntp_servers=''):
        """Baseline FMC M5 device through its physical serial port connection

        :param iso_url: http url of iso image
                http://10.83.65.25/cache/Development/6.3.0-10581/iso/Sourcefire_Defense_Center-6.3.0-10581-Restore.iso
        :param mgmt_ip: management interface ip address
        :param mgmt_netmask: management interface netmask
        :param mgmt_intf: management interface gateway
        :param mgmt_gateway: management interface gateway
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param power_cycle_flag: True power cylce before baseline, False otherwise
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

        super().baseline_using_serial(iso_url=iso_url, mgmt_ip=mgmt_ip, mgmt_netmask=mgmt_netmask,
                                      mgmt_gateway=mgmt_gateway, mgmt_intf=mgmt_intf, timeout=timeout,
                                      power_cycle_flag=power_cycle_flag, pdu_ip=pdu_ip, pdu_port=pdu_port,
                                      pdu_user=pdu_user, pdu_pwd=pdu_pwd,
                                      mgmt_ip6=mgmt_ip6, mgmt_prefix=mgmt_prefix, mgmt_gateway6=mgmt_gateway6,
                                      change_password=change_password, ipv4_mode=ipv4_mode, ipv6_mode=ipv6_mode,
                                      dns_servers=dns_servers, search_domains=search_domains, ntp_servers=ntp_servers)
