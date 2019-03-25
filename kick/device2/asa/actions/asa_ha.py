"""Copyright (c) 2017 Cisco Systems, Inc.
Name:
    asa_ha.py
Usage:
    Submodule for Legacy ASA HA.
Author:
    raywa
"""

import re
import time

from unicon.eal.dialogs import Dialog

from .constants import ASAHAStates, ASAHALinkNames

class AsaHAActiveStandby():
    """Class ASA active/standby HA
    """
    def __init__(self, asa_instance1, asa_instance2, init_ha=True):
        """Initializer of AsaHAActiveStandby.
        By default, instance1 will be primary and instance2 will be secondary.

        :param asa_instance1: connection instance1 that created by AsaConfig
        :param asa_instance2: connection instance2 that created by AsaConfig
        :return: None

        """
        self.asa_instance1 = asa_instance1
        self.asa_instance2 = asa_instance2
        self.primary = asa_instance1
        self.secondary = asa_instance2
        self.active = None
        self.standby = None

        if init_ha:
            # Configure primary unit
            self.config_as_primary(self.primary)

            folink_info = self.primary.topo.failover.failover_link
            if 'vlan' in folink_info and folink_info.vlan:
                folink_intf = '{hardware}.{vlan}'.format(hardware=folink_info.interface, vlan=folink_info.vlan)
                cmd = "interface %s\nno shutdown\n" % folink_info.interface
                cmd += "interface %s\nvlan %s" % (folink_intf, folink_info.vlan)
                self.primary.config(cmd, ctx = 'system')
                self.secondary.config(cmd, ctx='system')
            else:
                folink_intf = '{hardware}'.format(hardware=folink_info.interface)

            folink_ip = folink_info.ip_addr
            folink_mask = folink_info.netmask
            folink_standby = folink_info.ip_addr_standby
            folink_name = folink_info.get('link_name', ASAHALinkNames.DEFAULT_FAILOVER_LINK.value)
            self.config_folink(self.primary, folink_intf, folink_ip, folink_mask, folink_standby, folink_name)
            
            # Stateful link is optional.
            # Check existence in topo first
            if 'state_link' in self.primary.topo.failover:
                statelink_info = self.primary.topo.failover.state_link
                if 'vlan' in statelink_info and statelink_info.vlan:
                    statelink_intf = '{hardware}.{vlan}'.format(hardware=statelink_info.interface, vlan=statelink_info.vlan)
                    cmd = "interface %s\nno shutdown\n" % statelink_info.interface
                    cmd += "interface %s\nvlan %s" % (statelink_intf, statelink_info.vlan)
                    self.primary.config(cmd, ctx='system')
                    self.secondary.config(cmd, ctx='system')
                else:
                    statelink_intf = '{hardware}'.format(hardware=statelink_info.interface)

                if statelink_intf != folink_intf:
                    state_link_name = statelink_info.get(
                        'link_name', ASAHALinkNames.DEFAULT_STATE_LINK.value)
                    statelink_ip = statelink_info.get('ip_addr', None)
                    statelink_mask = statelink_info.get('netmask', None)
                    statelink_standby = statelink_info.get('ip_addr_standby', None)
                    
                    self.config_statelink(
                        unit=self.primary,
                        link_name=state_link_name,
                        intf=statelink_intf,
                        ip_addr=statelink_ip,
                        ip_netmask=statelink_mask,
                        ip_addr_standby=statelink_standby
                    )
                else:
                    self.config_statelink(
                        unit=self.primary,
                        link_name=folink_name,
                    )

            # Configure secondary unit
            self.config_folink(
                self.secondary, folink_intf, folink_ip, folink_mask, folink_standby)
            
            if 'state_link' in self.secondary.topo.failover:
                if statelink_intf != folink_intf:
                    cmd = 'interface {}'.format(statelink_intf)
                    cmd += '\nno shutdown'
                    self.secondary.config(cmd, exception_on_bad_config=True)
            self.config_as_secondary(self.secondary)

            # Enable HA
            self.enable_failover(self.secondary, check_status=False)
            self.enable_failover(self.primary, check_status=True)

        # Check HA status
        try:
            self.update_failover_roles()
        except RuntimeError:
            warning_msg = """
            \nWARNING:    Unable to determine primary/secondary or active/standby roles. 
            This will impact further operations defined in this module.
            Double check your configuration and use the config methods provided 
            in this module if something is missed. And then run update_failover_roles again.\n
            """
            self.primary.logger.warning(warning_msg)
            pass

    @staticmethod
    def config_as_primary(unit):
        """Configure a unit to be primary

        :param unit: ASA instance to be configured as primary
        :return: None

        """
        cmd = 'failover lan unit primary'
        unit.config(cmd, exception_on_bad_config=True)
    
    @staticmethod
    def config_as_secondary(unit):
        """Configure a unit to be secondary

        :param unit: ASA instance to be configured as secondary
        :return: None

        """
        cmd = 'failover lan unit secondary'
        unit.config(cmd, exception_on_bad_config=True)

    @staticmethod
    def config_folink(unit, intf, ip_addr, ip_netmask, ip_addr_standby, link_name=None):
        """Configure HA failover link

        :param unit: unit that you want to apply the config
        :param intf: physical interface of failover link
        :param ip_addr: Primary IP address of failover link
        :param ip_netmask: Netmask of failover IP
        :param ip_addr_standby: Standby IP address of failover link
        :param link_name: Failover link name to be assigned
        :return: None

        """
        link_name = link_name or ASAHALinkNames.DEFAULT_FAILOVER_LINK.value
        cmd = 'interface {intf}'.format(intf=intf)
        cmd += '\nno shutdown'
        cmd += '\nfailover lan interface {link_name} {intf}'.format(link_name=link_name, intf=intf)
        if ':' in ip_addr:
            cmd += '\nfailover interface ip folink {ip}/{mask} standby {standby}'.\
                format(ip=ip_addr, mask=ip_netmask, standby=ip_addr_standby)
        else:
            cmd += '\nfailover interface ip folink {ip} {mask} standby {standby}'.\
                format(ip=ip_addr, mask=ip_netmask, standby=ip_addr_standby)

        unit.config(cmd, exception_on_bad_config=True)

    @staticmethod
    def config_statelink(
            unit, link_name, intf=None, ip_addr=None, ip_netmask=None, ip_addr_standby=None):
        """Configure HA stateful link
        
        :param link_name: Stateful link name to be assigned
        :param unit: unit that you want to apply the config
        :param intf: physical interface of stateful link
        :param ip_addr: Primary IP address of stateful link
        :param ip_netmask: Netmask of stateful IP
        :param ip_addr_standby: Standby IP address of stateful link
        :return: None

        """
        cmd = ''
        intf = intf or ''

        if intf:
            cmd += 'interface {intf}'.format(intf=intf)
            cmd += '\nno shutdown'
        cmd += '\nfailover link {link_name} {intf}'.format(link_name=link_name, intf=intf)
        if ip_addr and ip_netmask and ip_addr_standby:
            if ':' in ip_addr:
                cmd += '\nfailover interface ip statelink {ip}/{mask} standby {standby}'.\
                    format(ip=ip_addr, mask=ip_netmask, standby=ip_addr_standby)
            else:
                cmd += '\nfailover interface ip statelink {ip} {mask} standby {standby}'.\
                    format(ip=ip_addr, mask=ip_netmask, standby=ip_addr_standby)

        unit.config(cmd, exception_on_bad_config=True)

    def is_failover_formed(self):
        """Determine whether an HA pair is formed by checking if both active and standby units
           are actively in the pair.

        :return: True|False
        """

        output = self.primary.execute('show failover | include host')
        if re.search('- ' + ASAHAStates.ACTIVE.value, output) \
            and re.search('- ' + ASAHAStates.STANDBY.value, output):
            return True
        return False

    def enable_failover(self, unit, check_status=False, timeout=300):
        """Enable failover

        :param unit: asa instance where failover will be enabled
        :param check_status: option to check failover status. False by default
        :return: None

        """
        unit.config('failover')

        if check_status:
            dialog = Dialog([
                ['Beginning configuration replication', None, None, True, False],
                ['End Configuration Replication to mate', 'sendline()', None, False, False],
            ])
            dialog.process(unit.asa_conn.spawn_id, timeout=timeout)

            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.is_failover_formed():
                    break
                time.sleep(10)
            else:
                raise RuntimeError('HA pair not formed in {} sec'.format(timeout))

    def switch_active(self, unit, timeout=180):
        """Switch active/standby units

        :param unit: unit to be switched to active
        :param timeout: timeout for units switching
        :return: None

        """
        unit.config('failover active')

        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_failover_formed():
                break
            time.sleep(5)
        else:
            raise RuntimeError('HA pair not formed after switchover in {} sec'.format(timeout))

        self.update_failover_roles()

    def update_failover_roles(self):
        """Update failver units roles

        Based on output of show failover, this method determines the roles of primary/secondary
        and active/standby units

        :return: None

        """
        show_failover1 = self.asa_instance1.execute('show failover')

        role1 = re.search('This host: (.*) - (.*)', show_failover1)
        role2 = re.search('Other host: (.*) - (.*)', show_failover1)
        primary_found = secondary_found = False
        active_found = standby_found = False

        if role1 and role2:
            # Determine roles on instance 1
            if role1.group(1).strip() == ASAHAStates.PRIMARY.value:
                primary_found = True
                self.primary = self.asa_instance1
            elif role1.group(1).strip() == ASAHAStates.SECONDARY.value:
                secondary_found = True
                self.secondary = self.asa_instance1

            if role1.group(2).strip() == ASAHAStates.ACTIVE.value:
                active_found = True
                self.active = self.asa_instance1
            elif role1.group(2).strip() == ASAHAStates.STANDBY.value:
                standby_found = True
                self.standby = self.asa_instance1

            # Determine roles on instance 2
            if role2.group(1).strip() == ASAHAStates.PRIMARY.value:
                primary_found = True
                self.primary = self.asa_instance2
            elif role2.group(1).strip() == ASAHAStates.SECONDARY.value:
                secondary_found = True
                self.secondary = self.asa_instance2

            if role2.group(2).strip() == ASAHAStates.ACTIVE.value:
                active_found = True
                self.active = self.asa_instance2
            elif role2.group(2).strip() == ASAHAStates.STANDBY.value:
                standby_found = True
                self.standby = self.asa_instance2
        else:
            raise RuntimeError('Unable to determine units roles')

        if not primary_found:
            raise RuntimeError('Unable to find primary unit')
        if not secondary_found:
            raise RuntimeError('Unable to find secondary unit')
        if not active_found:
            raise RuntimeError('Unable to find active unit')
        if not standby_found:
            raise RuntimeError('Unable to find standby unit')

    def get_dataintf_status(self, nameif):
        """Get status of a non HA interface given its logical name

        :param nameif: logical name of the interface
        :return: link status in both active and standby units in a dict

        """
        status = {}
        active, standby = self.active.execute('show failover').split('Other host')
        for line in active.splitlines():
            match = re.search('Interface {}.*: (.*)'.format(nameif), line)
            if match:
                status['active'] = match.group(1)
                break
        for line in standby.splitlines():
            match = re.search('Interface {}.*: (.*)'.format(nameif), line)
            if match:
                status['standby'] = match.group(1)
                break
        return status

class AsaHAActiveActive(AsaHAActiveStandby):
    """Class ASA active/active HA
    """
    def __init__(self, asa_instance1, asa_instance2, init_ha=True):
        """Initializer of AsaHAActiveStandby.
        By default, instance1 will be primary and instance2 will be secondary.

        :param asa_instance1: connection instance1 that created by AsaConfig
        :param asa_instance2: connection instance2 that created by AsaConfig
        :return: None

        """
        self.asa_instance1 = asa_instance1
        self.asa_instance2 = asa_instance2
        self.primary = asa_instance1
        self.secondary = asa_instance2

        if init_ha:
            # Configure primary unit
            self.config_as_primary(self.primary)

            folink_info = self.primary.topo.failover.failover_link
            if 'vlan' in folink_info and folink_info.vlan:
                folink_intf = '{hardware}.{vlan}'.format(hardware=folink_info.interface, vlan=folink_info.vlan)
                cmd = "interface %s\nno shutdown\n" % folink_info.interface
                cmd += "interface %s\nvlan %s" % (folink_intf, folink_info.vlan)
                self.primary.config(cmd, ctx = 'system')
                self.secondary.config(cmd, ctx='system')
            else:
                folink_intf = '{hardware}'.format(hardware=folink_info.interface)

            folink_ip = folink_info.ip_addr
            folink_mask = folink_info.netmask
            folink_standby = folink_info.ip_addr_standby
            folink_name = folink_info.get('link_name', ASAHALinkNames.DEFAULT_FAILOVER_LINK.value)
            self.config_folink(self.primary, folink_intf, folink_ip, folink_mask, folink_standby, folink_name)

            # Stateful link is optional.
            # Check existence in topo first if 'state_link' in self.primary.topo.failover:
            if 'state_link' in self.primary.topo.failover:
                statelink_info = self.primary.topo.failover.state_link
                if 'vlan' in statelink_info and statelink_info.vlan:
                    statelink_intf = '{hardware}.{vlan}'.format(hardware=statelink_info.interface, vlan=statelink_info.vlan)
                    cmd = "interface %s\nno shutdown\n" % statelink_info.interface
                    cmd += "interface %s\nvlan %s" % (statelink_intf, statelink_info.vlan)
                    self.primary.config(cmd, ctx='system')
                    self.secondary.config(cmd, ctx='system')
                else:
                    statelink_intf = '{hardware}'.format(hardware=statelink_info.interface)

                if statelink_intf != folink_intf:
                    state_link_name = statelink_info.get(
                        'link_name', ASAHALinkNames.DEFAULT_STATE_LINK.value)
                    statelink_ip = statelink_info.get('ip_addr', None)
                    statelink_mask = statelink_info.get('netmask', None)
                    statelink_standby = statelink_info.get('ip_addr_standby', None)

                    self.config_statelink(
                        unit=self.primary,
                        link_name=state_link_name,
                        intf=statelink_intf,
                        ip_addr=statelink_ip,
                        ip_netmask=statelink_mask,
                        ip_addr_standby=statelink_standby
                    )
                else:
                    self.config_statelink(
                        unit=self.primary,
                        link_name=folink_name,
                    )

            # Configure secondary unit
            self.config_folink(
                self.secondary, folink_intf, folink_ip, folink_mask, folink_standby)

            if 'state_link' in self.secondary.topo.failover:
                if statelink_intf != folink_intf:
                    cmd = 'interface {}'.format(statelink_intf)
                    cmd += '\nno shutdown'
                    self.secondary.config(cmd, exception_on_bad_config=True)
            self.config_as_secondary(self.secondary)

            # Configure failover groups for active/active
            self.config_failover_groups(self.primary)
            self.config_failover_groups(self.secondary)

            # Enable HA
            self.enable_failover(self.secondary, check_status=False)
            self.enable_failover(self.primary, check_status=True)

            # Join failover groups for each context configured in failover_groups
            for fo_grp in self.primary.topo.failover_groups:
                self.join_failover_group(unit=self.primary, context=fo_grp.ctx, failover_group_idx=fo_grp.idx)

        # Check HA status
        try:
            self.update_failover_roles()
        except RuntimeError:
            warning_msg = """
            \nWARNING:    Unable to determine primary/secondary or active/standby roles. 
            This will impact further operations defined in this module.
            Double check your configuration and use the config methods provided 
            in this module if something is missed. And then run update_failover_roles again.\n
            """
            self.primary.logger.warning(warning_msg)
            pass

    def config_failover_groups(self, unit):
        """Configure 2 failover groups on primary or secondary in active/active configuration

        :param unit: ASA instance to be configured
        :return: None

        """
        cmd = 'failover group 1'
        cmd += '\nprimary'
        cmd += '\npreempt'
        cmd += '\nexit'
        cmd += '\nfailover group 2'
        cmd += '\nsecondary'
        cmd += '\npreempt'
        cmd += '\nexit'
        unit.config(cmd, exception_on_bad_config=True)

    def join_failover_group(self, unit, context, failover_group_idx):
        """Configure to join a failover group for a context in active/active configuration

        :param unit: ASA instance to be configured
        :param context: ASA context
        :param failover_group_idx: 1 or 2 as an example
        :return: None

        """
        unit.config('no failover', ctx='system')
        unit.config('context {}'.format(context), ctx='system')
        unit.config('join-failover-group {}'.format(failover_group_idx))
        unit.config('exit')
        self.enable_failover(unit, check_status=True)

    def is_failover_formed(self):
        """Determine whether an HA pair is formed by checking if both primary and secondary
           are actively in the pair in active/active mode

        :return: True|False
        """

        self.primary.change_to_context(ctx='system')
        output = self.primary.execute('show failover | include Group 1')
        if not re.search(ASAHAStates.ACTIVE.value, output) \
            or not re.search(ASAHAStates.STANDBY.value, output):
            return False
        output = self.primary.execute('show failover | include Group 2')
        if not re.search(ASAHAStates.ACTIVE.value, output) \
            or not re.search(ASAHAStates.STANDBY.value, output):
            return False
        return True

    def validate_failover_groups(self):
        """Determine whether failover groups are formed
           in active/active configuration

        :return: True|False
        """

        flag = False
        unit = self.primary
        unit.change_to_context('system')
        unit.execute('show failover group 1')
        unit.execute('show failover group 2')
        output = unit.execute('show failover group 1 | include State')
        if re.search(ASAHAStates.ACTIVE.value, output) \
            and re.search(ASAHAStates.STANDBY.value, output):
            flag = True
        output = unit.execute('show failover group 2 | include State')
        if re.search(ASAHAStates.ACTIVE.value, output) \
            and re.search(ASAHAStates.STANDBY.value, output):
            flag = True
        return flag

    def update_failover_roles(self):
        """Update failver units roles

        Based on output of show failover, this method determines the roles of primary/secondary
        active/active

        :return: None

        """
        show_failover1 = self.asa_instance1.execute('show failover')

        role1 = re.search('This host: (.*)', show_failover1)
        role2 = re.search('Other host: (.*)', show_failover1)
        primary_found = secondary_found = False

        if role1 and role2:
            # Determine roles on instance 1
            if role1.group(1).strip() == ASAHAStates.PRIMARY.value:
                primary_found = True
                self.primary = self.asa_instance1
            elif role1.group(1).strip() == ASAHAStates.SECONDARY.value:
                secondary_found = True
                self.secondary = self.asa_instance1

            # Determine roles on instance 2
            if role2.group(1).strip() == ASAHAStates.PRIMARY.value:
                primary_found = True
                self.primary = self.asa_instance2
            elif role2.group(1).strip() == ASAHAStates.SECONDARY.value:
                secondary_found = True
                self.secondary = self.asa_instance2

        else:
            raise RuntimeError('Unable to determine units roles')

        if not primary_found:
            raise RuntimeError('Unable to find primary unit')
        if not secondary_found:
            raise RuntimeError('Unable to find secondary unit')


