import logging

from ...kp.actions import Kp, KpLine

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True
    pass

logger = logging.getLogger(__name__)


class Wa(Kp):
    def __init__(self, 
                 hostname, 
                 login_username='admin',
                 login_password='cisco123', 
                 sudo_password="cisco123",
                 power_bar_server='',
                 power_bar_port='',
                 power_bar_user='admn',
                 power_bar_pwd='admn',
                 config_hostname='firepower',
                 use_asa=False):
        """Constructor of Wa using KP as the base

        :param hostname: host name in prompt
                e.g. 'BATIT-4200-2-AST'
        :param login_username: user name for login
        :param login_password: password for login
        :param sudo_password: root password for FTD
        :param power_bar_server: IP address of the PDU
        :param power_bar_port: port for device on the PDU
        :param power_bar_user: user for device on the PDU
        :param power_bar_pwd: pwd for device on the PDU
        :param: 'config_hostname': initial hostname of a device BEFORE being set by baseline
                    e.g. Fresh device, no config: 'ciscoasa', 'firepower'
                    e.g. Previously used device, already configured: 'BATIT-4200-2-AST'
        :param use_asa: bool value to indicate using ASA statemachine while interacting with KP.
                        Should be set to 'True' if baselining to/from ASA.
                        
        :return: None

        """
        super().__init__(hostname=hostname,
                         login_username=login_username,
                         login_password=login_username, 
                         sudo_password=sudo_password,
                         power_bar_server=power_bar_server,
                         power_bar_port=power_bar_port,
                         power_bar_user=power_bar_user,
                         power_bar_pwd=power_bar_pwd,
                         config_hostname=config_hostname,
                         use_asa=use_asa)
        self.line_class = WaLine
        logger.info("Done: WA instance (extension of KP) created")


class WaLine(KpLine):
    ################################################################# 
    # ASA Functions
    #################################################################
    def get_asa_bundle_name_template(self, asa_version):
        return 'cisco-asa-fp4200.{}.(SS[AB]|SPA)'.format(asa_version)
        
    def get_asa_bundle_name_pattern(self):
        return 'cisco-asa-fp4200\.([\d\.\-]+)\.(SS[AB]|SPA)'

    ################################################################# 
    # FTD Functions
    #################################################################
    def get_ftd_bundle_name_pattern(self):
        return 'cisco-ftd-fp4200\.([\d\.\-]+)\.(SS[AB]|SPA)'
    
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
        """Baseline Warwick Avenure with FTD image by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the pxe-site
        and use them to baseline the device.

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
        
        # Modified method call to preprare WA images
        pxe_ip, tftp_prefix, scp_prefix, files = \
            prepare_installation_files(site, 'Wa', branch, version)
        
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
    
    def rommon_configure(self, tftp_server, rommon_file,
                         uut_ip, uut_netmask, uut_gateway):
        """In ROMMON mode, set network configurations.

        :param tftp_server: tftp server ip that uut can reach
        :param rommon_file: build file with path,
               e.g. '/netboot/ims/Development/6.2.1-1159/installers/'
                    'fxos-k8-fp4200-lfbff.82.2.1.386i.SSA'
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
                # Modified expectation expectation for WA device
                self.spawn_id.expect(' 0% packet loss', timeout=5)
            except TimeoutError:
                time.sleep(60)
                continue
            else:
                break
        else:
            raise RuntimeError(">>>>>> Ping to {} server not working".format(tftp_server))

