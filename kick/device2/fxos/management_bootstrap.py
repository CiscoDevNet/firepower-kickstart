import logging

from unicon.eal.dialogs import Dialog

logger = logging.getLogger(__name__)


class ManagementBootstrap:
    def __init__(self, handle, ipv4_address=None, ipv4_netmask=None, ipv4_gateway=None, ipv6_address=None,
                 ipv6_prefix=None, ipv6_gateway=None, registration_key=None, password=None, firepower_manager_ip=None,
                 firewall_mode=None, fqdn=None, dns_servers=None, search_domains=None, permit_expert_mode=None,
                 management_type=None):
        """
        :param handle: SSH connection handle
        """
        self.handle = handle
        self.ipv4_address = ipv4_address
        self.ipv4_netmask = ipv4_netmask
        self.ipv4_gateway = ipv4_gateway
        self.ipv6_address = ipv6_address
        self.ipv6_prefix = ipv6_prefix
        self.ipv6_gateway = ipv6_gateway
        self.registration_key = registration_key
        self.password = password
        self.firepower_manager_ip = firepower_manager_ip
        self.firewall_mode = firewall_mode
        self.fqdn = fqdn
        self.dns_servers = dns_servers
        self.search_domains = search_domains
        self.permit_expert_mode = permit_expert_mode
        self.management_type = management_type

    def configure(self, slot, app_name):
        logger.info('Configuring App mgmt details in mgmt-bootstrap')
        self.handle.execute('enter mgmt-bootstrap {}'.format(app_name))
        self.configure_ipv4(slot=slot, app_name=app_name, ipv4_address=self.ipv4_address,
                            ipv4_netmask=self.ipv4_netmask, ipv4_gateway=self.ipv4_gateway, scope=False, commit=False)
        self.configure_ipv6(slot=slot, app_name=app_name, ipv6_address=self.ipv6_address,
                            ipv6_prefix=self.ipv6_prefix, ipv6_gateway=self.ipv6_gateway, scope=False, commit=False)
        self.configure_bootstrap_keys_secret(app_name=app_name, registration_key=self.registration_key,
                                             password=self.password, scope=False, commit=False)
        self.configure_bootstrap_keys(app_name=app_name, firepower_manager_ip=self.firepower_manager_ip,
                                      firewall_mode=self.firewall_mode, fqdn=self.fqdn, dns_servers=self.dns_servers,
                                      search_domains=self.search_domains, scope=False, commit=False,
                                      permit_expert_mode=self.permit_expert_mode, management_type=self.management_type)
        logger.info('Configured App mgmt details in mgmt-bootstrap')

    def configure_ipv4(self, slot, app_name, ipv4_address=None, ipv4_netmask=None, ipv4_gateway=None, scope=True,
                       commit=True):
        logger.info('Configuring IPv4 details in mgmt-bootstrap')
        if ipv4_address or ipv4_netmask or ipv4_gateway:
            if scope:
                self.handle.execute('enter mgmt-bootstrap {}'.format(app_name))
            self.handle.execute('enter {} {} firepower'.format('ipv4', slot))
            if ipv4_gateway:
                self.handle.execute('set gateway {}'.format(ipv4_gateway))
            if ipv4_address and ipv4_netmask:
                self.handle.execute('set ip {} {} {}'.format(ipv4_address, 'mask', ipv4_netmask))
            elif ipv4_address or ipv4_netmask:
                raise Exception("You need to provide both ipv4_address and ipv4_netmask")
            if commit:
                output = self.handle.execute('commit-buffer')
                if 'Error' in output:
                    logger.info("Failed while configuring IPv4 with error: {}".format(output))
                    raise Exception("Failed while configuring IPv4")
            self.handle.execute('exit')
        logger.info('Completed IPv4 configuration in mgmt-bootstrap')

    def configure_ipv6(self, slot, app_name, ipv6_address=None, ipv6_prefix=None, ipv6_gateway=None, scope=True,
                       commit=True):
        logger.info('Configuring IPv6 details in mgmt-bootstrap')
        if ipv6_address or ipv6_prefix or ipv6_gateway:
            if scope:
                self.handle.execute('enter mgmt-bootstrap {}'.format(app_name))
            self.handle.execute('enter {} {} firepower'.format('ipv6', slot))
            if ipv6_gateway:
                self.handle.execute('set gateway {}'.format(ipv6_gateway))
            if ipv6_address and ipv6_prefix:
                self.handle.execute('set ip {} {} {}'.format(ipv6_address, 'prefix-length', ipv6_prefix))
            elif ipv6_address or ipv6_prefix:
                raise Exception("You need to provide both ipv6_address and ipv6_prefix")
            if commit:
                output = self.handle.execute('commit-buffer')
                if 'Error' in output:
                    logger.info("Failed while configuring IPv6 with error: {}".format(output))
                    raise Exception("Failed while configuring IPv6")
            self.handle.execute('exit')
        logger.info('Completed IPv6 configuration in mgmt-bootstrap')

    def configure_bootstrap_keys_secret(self, app_name, registration_key=None, password=None, scope=True, commit=True):
        logger.info('Configuring bootstrap key secret in mgmt-bootstrap')
        if registration_key or password:
            if scope:
                self.handle.execute('enter mgmt-bootstrap {}'.format(app_name))
            if registration_key:
                self._enter_secret_value("REGISTRATION_KEY", registration_key)
            if password:
                self._enter_secret_value("PASSWORD", password)
            if commit:
                output = self.handle.execute('commit-buffer')
                if 'Error' in output:
                    logger.info("Failed while configuring bootstrap key with error: {}".format(output))
                    raise Exception("Failed while configuring bootstrap key")
        logger.info('Completed bootstrap key secret configuration in mgmt-bootstrap')

    def _enter_secret_value(self, type, value):
        self.handle.execute('enter bootstrap-key-secret {}'.format(type))
        configuration_dialog = Dialog([
            ['Enter a value', 'sendline({})'.format(value), None, True, True],
            ['Confirm the value:', 'sendline({})'.format(value), None, False, False],
        ])
        target_state = self.handle.sm.current_state
        self.handle.run_cmd_dialog('set value', configuration_dialog, target_state=target_state)
        self.handle.execute('exit')

    def configure_bootstrap_keys(self, app_name, firepower_manager_ip=None,
                                 firewall_mode=None, fqdn=None, dns_servers=None, search_domains=None, scope=True,
                                 commit=True, permit_expert_mode=None, management_type=None):
        logger.info('Configuring bootstrap key in mgmt-bootstrap')
        if any([firepower_manager_ip, firewall_mode, fqdn, dns_servers, search_domains, permit_expert_mode,
                management_type]):
            if scope:
                self.handle.execute('enter mgmt-bootstrap {}'.format(app_name))
            self._enter_value("FIREPOWER_MANAGER_IP", firepower_manager_ip)
            self._enter_value("FIREWALL_MODE", firewall_mode)
            self._enter_value("FQDN", fqdn)
            self._enter_value("DNS_SERVERS", dns_servers)
            self._enter_value("SEARCH_DOMAINS", search_domains)
            self._enter_value("PERMIT_EXPERT_MODE", permit_expert_mode)
            self._enter_value("MANAGEMENT_TYPE", management_type)
            if commit:
                output = self.handle.execute('commit-buffer')
                if 'Error' in output:
                    logger.info("Failed while configuring bootstrap key with error: {}".format(output))
                    raise Exception("Failed while configuring bootstrap key")
        logger.info('Completed bootstrap key configuration in mgmt-bootstrap')

    def _enter_value(self, type, value):
        if value is not None:
            self.handle.execute('enter bootstrap-key {}'.format(type))
            self.handle.execute('set value {}'.format(value))
            self.handle.execute('up')


class ManagementClusterBootstrap(ManagementBootstrap):

    def __init__(self, handle, ip_config=None, registration_key=None, password=None,
                 firepower_manager_ip=None, firewall_mode=None, fqdn=None, dns_servers=None, search_domains=None,
                 permit_expert_mode=None, management_type=None):
        """
        :param handle: SSH connection handle
        """
        self.handle = handle
        self.ip_config = ip_config
        self.registration_key = registration_key
        self.password = password
        self.firepower_manager_ip = firepower_manager_ip
        self.firewall_mode = firewall_mode
        self.fqdn = fqdn
        self.dns_servers = dns_servers
        self.search_domains = search_domains
        self.permit_expert_mode = permit_expert_mode
        self.management_type = management_type

    def configure(self, slot, app_name):
        logger.info('Configuring App mgmt details in mgmt-bootstrap for Intra chassis cluster')
        self.handle.execute('enter mgmt-bootstrap {}'.format(app_name))
        if ',' in slot:
            slot_list = slot.strip("\"").split(',')
            for app_slot in slot_list:
                if app_slot in self.ip_config:
                    if 'ipv4' in self.ip_config[app_slot]:
                        self.configure_ipv4(slot=app_slot, app_name=app_name,
                                            ipv4_address=self.ip_config[app_slot]['ipv4'].get("ip"),
                                            ipv4_netmask=self.ip_config[app_slot]['ipv4'].get("netmask"),
                                            ipv4_gateway=self.ip_config[app_slot]['ipv4'].get("gateway"),
                                            scope=False, commit=False)
                    if 'ipv6' in self.ip_config[app_slot]:
                        self.configure_ipv6(slot=app_slot, app_name=app_name,
                                            ipv6_address=self.ip_config[app_slot]['ipv6'].get("ip"),
                                            ipv6_prefix=self.ip_config[app_slot]['ipv6'].get("prefix"),
                                            ipv6_gateway=self.ip_config[app_slot]['ipv6'].get("gateway"),
                                            scope=False, commit=False)

        self.configure_bootstrap_keys_secret(app_name=app_name, registration_key=self.registration_key,
                                             password=self.password, scope=False, commit=False)
        self.configure_bootstrap_keys(app_name=app_name, firepower_manager_ip=self.firepower_manager_ip,
                                      firewall_mode=self.firewall_mode, fqdn=self.fqdn, dns_servers=self.dns_servers,
                                      search_domains=self.search_domains, scope=False, commit=False,
                                      permit_expert_mode=self.permit_expert_mode, management_type=self.management_type)
        logger.info('Configured App mgmt details in mgmt-bootstrap')
