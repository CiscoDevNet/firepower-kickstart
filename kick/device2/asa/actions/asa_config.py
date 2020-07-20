"""Copyright (c) 2017 Cisco Systems, Inc.
Name:
    asa_config.py
Usage:
    Library for Configuring legacy ASA.
Author:
    raywa
"""

import logging
import re
import time
from collections import defaultdict

import urllib.request
from urllib.parse import urlparse

from .constants import AsaConfigConstants

CURRENT_LOGGER = logging.getLogger(__name__)

class AsaConfig():
    """Class AsaConfig
    """
    def __init__(self, asa_conn, topo, logger=CURRENT_LOGGER, **kwargs):
        """Initializer of AsaConfig

        A valid connection instance, asa_conn, (by ssh/telnet, etc)
        has to be passed to AsaConfig to execute cli commands.

        All ASA related topology info can be passed from input arg 'topo' which can be
        parsed from a data yaml file. See tests/configs.yaml for samples. Mandatory
        Attributes in asa topo: hostname, cmode, fmode

        During the __init__ process, contexts/interfaces will be allocated based
        on given context mode in topo.
        Supported ASA modes: firewall mode: tfw | rfw, context mode: sfm | mfm

        :param asa_conn: ASA connection instance
        :param topo: ASA topology
        :param logger: Logging instance
        :param kwargs: other optional keyword args including:
            (1) clear_config: execute "clear config all" during initialization.
                disable by default.
            (2) logging: enable logging with certain level. disable by default.
            (3) init_config: initial config. disable by default.
        :return: None

        """
        self.asa_conn = asa_conn
        self.topo = topo
        self.logger = logger
        self.clear_config = kwargs.get('clear_config', False)
        self.logging = kwargs.get('logging', (False, None))
        self.init_config = kwargs.get('init_config', True)
        self.clu_intf_mode = kwargs.get('clu_intf_mode', None)

        show_version = asa_conn.execute('show version')
        m_model = re.search('Hardware: +(\S+),', show_version)
        model = m_model.group(1) if m_model else None

        # config context mode
        if model and model != 'ASAv':
            self.asa_conn.change_context_mode(self.topo.cmode)
        self.current_ctx = None if self.topo.cmode == 'sfm' else 'system'

        # clear config all
        if self.clear_config:
            self.clear_config_all(timeout=240)
            self.config('hostname {}'.format(topo.hostname))

        if self.init_config:
            if self.topo.cmode == 'sfm':
                # change firewall mode
                self.asa_conn.change_firewall_mode(self.topo.fmode)

                if self.logging[0]:
                    self.asa_conn.config('logging enable')
                    self.asa_conn.config('logging trap {}'.format(self.logging[1]))
                else:
                    self.asa_conn.config('no logging enable')

                if self.clu_intf_mode:
                    self.asa_conn.config('cluster interface-mode {}'.format(self.clu_intf_mode))
                
                # Config port channel if it's specified in topo
                self.config_port_channels()

                if 'interfaces' in self.topo:
                    allocated_physical_intf = set()
                    for intf in self.topo.interfaces:
                        cmd = ''
                        if intf.hardware not in allocated_physical_intf:
                            cmd += '\ninterface {}\nno shutdown'.format(intf.hardware)
                            allocated_physical_intf.add(intf.hardware)
                        if 'vlan' in intf:
                            cmd += '\ninterface {hardware}.{vlan}'.format(
                                hardware=intf.hardware, vlan=intf.vlan)
                            cmd += '\nvlan {}\nno shutdown'.format(intf.vlan)
                        self.asa_conn.config(cmd)

            elif self.topo.cmode == 'mfm':
                if self.clu_intf_mode:
                    self.asa_conn.config('cluster interface-mode {}'.format(self.clu_intf_mode))

                # Config port channel if it's specified in topo
                self.config_port_channels()

                # create contexts and allocate interfaces in multi mode
                if 'interfaces' in self.topo:
                    allocated_physical_intf = set()
                    for intfs in self.topo.interfaces.values():
                        for intf in intfs:
                            cmd = ''
                            if intf.hardware not in allocated_physical_intf:
                                cmd += '\ninterface {}\nno shutdown'.format(intf.hardware)
                                allocated_physical_intf.add(intf.hardware)
                            if 'vlan' in intf:
                                cmd += '\ninterface {hardware}.{vlan}'.format(
                                    hardware=intf.hardware, vlan=intf.vlan)
                                cmd += '\nvlan {}\nno shutdown'.format(intf.vlan)
                            self.asa_conn.config(cmd)

                # create context. first context in config file will be regarded as admin context
                if 'contexts' in self.topo:
                    for index, ctx in enumerate(self.topo.contexts.split()):
                        context = 'admin-context' if index == 0 else 'context'
                        cmd = '{} {}'.format(context, ctx)
                        cmd += '\ncontext {}'.format(ctx)
                        cmd += '\nconfig-url disk0:/{}.ctx'.format(ctx)
                        self.asa_conn.config(cmd, timeout = 30)
                        
                        # allocate interfaces
                        if 'interfaces' in self.topo:
                            intfs = self.topo.interfaces.get(ctx)
                            if intfs:
                                for intf in intfs:
                                    cmd = 'allocate-interface {}'.format(intf.hardware)
                                    if 'vlan' in intf:
                                        cmd += '.{}'.format(intf.vlan)
                                    self.asa_conn.config(cmd)

                        # change firewall mode
                        self.change_to_context(ctx)
                        self.asa_conn.change_firewall_mode(self.topo.fmode)
                        if self.logging[0]:
                            self.asa_conn.config('logging enable')
                            self.asa_conn.config('logging trap {}'.format(self.logging[1]))
                        else:
                            self.asa_conn.config('no logging enable')
                        self.change_to_context('system')

    def change_to_context(self, ctx=None):
        """Switch to given context in multi mode

        This function should be only used for multi mode.
        No action will be taken in single mode with given input ctx=None

        :param ctx: context to be changed to
        :return: None

        """
        if ctx and ctx != self.current_ctx:
            if ctx == 'system':
                self.asa_conn.enable_execute('changeto system')
            else:
                self.asa_conn.enable_execute('changeto context {ctx}'.format(ctx=ctx))
            self.current_ctx = ctx

    def clear_config_all(self, timeout=60):
        """Clear all config in ASA

        :param timeout: timeout for prompt return

        """
        ctx = None if self.topo.cmode == 'sfm' else 'system'
        self.change_to_context(ctx)
        self.asa_conn.clear_config_all(timeout=timeout)
        if self.topo.cmode == 'mfm':
            for ctx in self.topo.contexts.split():
                if 'Error' not in self.asa_conn.enable_execute('dir {ctx}.ctx'.format(ctx=ctx)):
                    self.asa_conn.delete('{}.ctx'.format(ctx), flag='/noconfirm')

    def execute(self, cmd, ctx=None, timeout=10):
        """Execute a command and get the output in enable state

        ctx should be used only for multi mode. otherwise leave it as None

        :param cmd: command to be executed
        :param ctx: (multi mode only) name of the context under which you want to run the command
        :param timeout: timeout for prompt return
        :return: output from cmd execution

        """
        self.change_to_context(ctx)
        return self.asa_conn.enable_execute(cmd, timeout=timeout)

    def config(self, cmd, ctx=None, timeout=10, exception_on_bad_config=False):
        """Execute a command or a set of commands in config mode
        If a set of commands need to be executed, use '\n' as a separator in a single string.
        Example: asa.config('interface Ten0/8\nno shutdown')

        :param cmd: command to be executed
        :param ctx: (multi mode only) name of the context under which you want to run the command
        :param timeout: timeout for prompt return
        :return: None

        """
        self.change_to_context(ctx)
        
        count = 0
        for line in cmd.split('\n'):
            if count > 200 and count % 200 == 1:
                time.sleep(1)
            self.asa_conn.config(line, timeout=timeout, exception_on_bad_config=exception_on_bad_config)
            count += 1

    def write_memory(self):
        """Write memory

        :return: None

        """
        if self.topo.cmode == 'mfm':
            for ctx in self.topo.contexts.split():
                self.execute('write memory', ctx)
            self.change_to_context('system')
        self.execute('write memory')

    def reload(self):
        """Reload the ASA

        :return: None

        """
        self.write_memory()
        self.asa_conn.reload(write_mem=False)

    def show_version(self):
        """Get ASA version info

        :return: ASA software version and hardware model

        """
        ctx = None if self.topo.cmode == 'sfm' else 'system'
        show_version = self.execute('show version', ctx).replace('\x00', '')
        m_version = re.search('Software Version +(\S+)', show_version)
        m_model = re.search('Hardware: +(\S+),', show_version)
        version = (re.sub(r'[()]', '.', m_version.group(1))).strip('.') if m_version else None
        model = m_model.group(1) if m_model else None
        return version, model

    def config_port_channel(self, pc_num, desc=None, load_balance=None, min_bundle=None, max_bundle=None,\
            span_cluster=False, vss=False, ctx=None, *args):
        """Config a port channel

        :param pc_num: port channel interface number
        :param desc: description of the port-channel
        :param load_balance: load balance method
        :param min_bundle: number of min bundled links
        :param max_bundle: number of max bundled links
        :param span_cluster: config pc to be spanned cluster
        :param vss: Enable vss load-balance
        :param ctx: context name only for multi mode
        :param args: other customized commands
        :return: None

        """
        cmd = 'interface port-channel {pc_num}'.format(pc_num=pc_num)
        if desc:
            cmd += '\ndescription {desc}'.format(desc=desc)
        if load_balance:
            cmd += '\nport-channel load-balance {lb}'.format(lb=load_balance)
        if min_bundle:
            cmd += '\nport-channel min-bundle {min_bund}'.format(min_bund=min_bundle)
        if max_bundle:
            cmd += '\nlacp max-bundle {bundle}'.format(bundle=max_bundle)
        if span_cluster:
            cmd += '\nport-channel span-cluster'
            if vss:
                cmd += ' vss-load-balance'

        for extra_cmd in args:
            cmd += '\n{cmd}'.format(cmd=extra_cmd)

        self.config(cmd, ctx, exception_on_bad_config=True)

    def assign_intf_to_pc(self, intf, pc_num, mode, ctx=None, *args):
        """Assign a physical interface to port channel

        :param intf: physical interface name
        :param pc_num: port channel number
        :param mode: etherchannel mode
        :param ctx: context name only for multi mode
        :param args: other customized commands
        :return: None

        """
        cmd = '\ninterface {intf}'.format(intf=intf)
        cmd += '\nno shutdown'
        cmd += '\nchannel-group {pc_num} mode {mode}'.format(pc_num=pc_num, mode=mode)

        for extra_cmd in args:
            cmd += '\n{cmd}'.format(cmd=extra_cmd)

        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_port_channels(self):
        """Configure all given port channel config under self.topo
        Sample port channel yaml config:

        port_channels:
            - pc_num: 10
              load_balance: dst-ip
              min_bundle: 4
              max_bundle: 8
              span_cluster: True
              vss: True
              assignment:
                  mode: on
                  members: ['Ten0/6', 'Ten0/7']
            - pc_num: 11
              span_cluster: True

        :return: None

        """
        pcs = self.parse_ctx_contents(self.topo.port_channels) if 'port_channels' in self.topo else []

        for pc, ctx in pcs:
            lb = pc.get('load_balance', None)
            min_bundle = pc.get('min_bundle', None)
            max_bundle = pc.get('max_bundle', None)
            span_cluster = pc.get('span_cluster', False)
            vss = pc.get('vss', False)
            desc = pc.get('desc', None)
            pc_custom = pc.get('custom', [])

            self.config_port_channel(
                pc.pc_num, desc=desc, load_balance=lb, min_bundle=min_bundle, max_bundle=max_bundle,
                span_cluster=span_cluster, vss=vss, ctx=ctx, *pc_custom)

            if 'assignment' in pc:
                assgn_custom = pc.assignment.get('custom', [])
                for member in pc.assignment.members:
                    self.assign_intf_to_pc(
                        intf=member, pc_num=pc.pc_num, mode=pc.assignment.mode,
                        ctx=ctx, *assgn_custom)

    def config_ip_interface(self, hardware, nameif=None, sec_level=None, vlan=None, \
        ipv4_addr=None, netmask=None, ipv4_standby=None, ipv6_addr=None, prefix=None, \
        ipv6_standby=None, mac=None, ctx=None):
        """Config an individual interface in routed mode

        :param hardware: physical interface name
        :param nameif: assign name to interface
        :param sec_level: security level
        :param vlan: vlan id if use sub interface
        :param ipv4_addr: IPv4 address
        :param netmask: IPv4 network mask
        :param ipv4_standby: IPv4 standby address
        :param ipv6_addr: IPv6 address
        :param prefix: IPv6 network prefix
        :param ipv6_standby: IPv6 standby address
        :param mac: MAC address
        :param ctx: context name only for multi mode
        :return: None

        """
        cmd = '\ninterface {hardware}'.format(hardware=hardware)
        if vlan:
            cmd += '.{vlan}'.format(vlan=vlan)
        cmd += '\nno shutdown'
        if nameif:
            cmd += '\nnameif {name}'.format(name=nameif)
        if sec_level is not None:
            cmd += '\nsecurity-level {sec_level}'.format(sec_level=sec_level)
        if ipv4_addr:
            cmd += '\nip address {addr} {mask}'.format(addr=ipv4_addr, mask=netmask)
            if ipv4_standby:
                cmd += ' standby {addr}'.format(addr=ipv4_standby)
        if ipv6_addr:
            cmd += '\nipv6 address {addr}/{prefix}'.format(addr=ipv6_addr, prefix=prefix)
            if ipv6_standby:
                cmd += ' standby {addr}'.format(addr=ipv6_standby)
        if mac:
            cmd += '\nmac-address {mac}'.format(mac=mac)

        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_bvi_interface(self, hardware, nameif=None, bridge_group=None, sec_level=None, vlan=None, \
        ipv4_addr=None, mask=None, ipv4_standby=None, \
        ipv6_addr=None, prefix=None, ipv6_standby=None, mac=None, ctx=None):
        """Config an individual interface in transparent mode

        :param hardware: physical interface name
        :param nameif: assign name to interface
        :param sec_level: security level
        :param vlan: vlan id if use sub interface
        :param bridge_group: bridge group id
        :param ip_addr: IPv4 addr of BVI interface
        :param mask: IPv4 netmask
        :param ipv6_addr: IPv6 addr of BVI interface
        :param prefix: IPv6 prefix
        :param mac: MAC address
        :param ctx: context name only for multi mode
        :return: None

        """
        cmd = '\ninterface {hardware}'.format(hardware=hardware)
        if vlan:
            cmd += '.{vlan}'.format(vlan=vlan)
        cmd += '\nno shutdown'
        if nameif:
            cmd += '\nnameif {name}'.format(name=nameif)
        if sec_level is not None:
            cmd += '\nsecurity-level {sec_level}'.format(sec_level=sec_level)
        if bridge_group:
            cmd += '\nbridge-group {bvi}'.format(bvi=bridge_group)

        if ipv4_addr or ipv6_addr:
            cmd += '\ninterface BVI {bvi}'.format(bvi=bridge_group)
            if ipv4_addr:
                cmd += '\nip address {addr} {mask}'.format(addr=ipv4_addr, mask=mask)
                if ipv4_standby:
                    cmd += ' standby {addr}'.format(addr=ipv4_standby)
            if ipv6_addr:
                cmd += '\nipv6 enable'
                cmd += '\nipv6 address {addr}/{prefix}'.format(addr=ipv6_addr, prefix=prefix)
                if ipv6_standby:
                    cmd += ' standby {addr}'.format(addr=ipv6_standby)
        if mac:
            cmd += '\nmac-address {mac}'.format(mac=mac)
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_cluster_individual_mgmt_interface(self, hardware, nameif=None,
        sec_level=None, vlan=None, ipv4_addr=None, netmask=None, ipv6_addr=None, prefix=None, \
        mac=None, cluster_ip_pool=None, ctx=None):
        """Config an management only interface as individual interface in cluster

        :param hardware: physical interface name
        :param nameif: assign name to interface
        :param sec_level: security level
        :param vlan: vlan id if use sub interface
        :param ipv4_addr: IPv4 address
        :param netmask: IPv4 network mask
        :param ipv6_addr: IPv6 address
        :param prefix: IPv6 network prefix
        :param mac: MAC address
        :param cluster_ip_pool: IP pool for cluster individual interface
        :param ctx: context name only for multi mode
        :return: None

        """

        cmd = "show run interface {hardware}".format(hardware=hardware)
        out = self.execute(cmd, ctx)
        found = re.search(r"management-only .*[\r\n]*", out)
        if found:
            manangement_only_mode = found.group().strip('\n\r')
        else:
            manangement_only_mode = None

        cmd_pool = ''
        cmd = '\ninterface {hardware}'.format(hardware=hardware)
        if vlan:
            cmd += '.{vlan}'.format(vlan=vlan)
        cmd += '\nno shutdown'
        if manangement_only_mode and \
           manangement_only_mode == "management-only":
            cmd += '\nno %s' % manangement_only_mode
        cmd += '\nmanagement-only individual'
        if nameif:
            cmd += '\nnameif {name}'.format(name=nameif)
        if sec_level is not None:
            cmd += '\nsecurity-level {sec_level}'.format(sec_level=sec_level)
        if ipv4_addr:
            if cluster_ip_pool.ipv4_pool_range and cluster_ip_pool.ipv4_pool_name:
                cmd_pool += "\nip local pool %s %s-%s mask %s" % (
                                               cluster_ip_pool.ipv4_pool_name,
                                               cluster_ip_pool.ipv4_pool_range[0],
                                               cluster_ip_pool.ipv4_pool_range[1],
                                               netmask
                                              )
                cmd += '\nip address {addr} {mask} cluster-pool {name}'.format(
                        addr=ipv4_addr,
                        mask=netmask,
                        name=cluster_ip_pool.ipv4_pool_name)
            else:
                raise RuntimeError('IPv4 pool is empty')

        if ipv6_addr:
            if cluster_ip_pool.ipv6_pool_range and cluster_ip_pool.ipv6_pool_name:
                cmd_pool += "\nipv6 local pool %s %s/%s %s" % (cluster_ip_pool.ipv6_pool_name,
                                                        prefix,
                                                        cluster_ip_pool.ipv6_pool_start,
                                                        cluster_ip_pool.ipv6_pool_number)
                cmd += '\nipv6 address {addr}/{prefix} cluster-pool {name}'.format(
                        addr=ipv6_addr,
                        prefix=prefix,
                        name = cluster_ip_pool.ipv6_pool_name)
            else:
                raise RuntimeError('IPv4 pool is empty')
        if mac:
            cmd += '\nmac-address {mac}'.format(mac=mac)

        self.config(cmd_pool, ctx, exception_on_bad_config=True)
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_mgmt_interface(self, hardware, nameif=None, sec_level=None, vlan=None, \
        ipv4_addr=None, netmask=None, ipv4_standby=None, ipv6_addr=None, prefix=None, \
        ipv6_standby=None, mac=None, ctx=None):
        """Config a management only interface in HA or standalone mode

        :param hardware: physical interface name
        :param nameif: assign name to interface
        :param sec_level: security level
        :param vlan: vlan id if use sub interface
        :param ipv4_addr: IPv4 address
        :param netmask: IPv4 network mask
        :param ipv4_standby: IPv4 standby address
        :param ipv6_addr: IPv6 address
        :param prefix: IPv6 network prefix
        :param ipv6_standby: IPv6 standby address
        :param mac: MAC address
        :param ctx: context name only for multi mode
        :return: None

        """
        cmd = '\ninterface {hardware}'.format(hardware=hardware)
        if vlan:
            cmd += '.{vlan}'.format(vlan=vlan)
        cmd += '\nno shutdown'
        cmd += '\nmanagement-only'
        if nameif:
            cmd += '\nnameif {name}'.format(name=nameif)
        if sec_level is not None:
            cmd += '\nsecurity-level {sec_level}'.format(sec_level=sec_level)
        if ipv4_addr:
            cmd += '\nip address {addr} {mask}'.format(addr=ipv4_addr, mask=netmask)
            if ipv4_standby:
                cmd += ' standby {addr}'.format(addr=ipv4_standby)
        if ipv6_addr:
            cmd += '\nipv6 address {addr}/{prefix}'.format(addr=ipv6_addr, prefix=prefix)
            if ipv6_standby:
                cmd += ' standby {addr}'.format(addr=ipv6_standby)
        if mac:
            cmd += '\nmac-address {mac}'.format(mac=mac)

        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_intfs(self, contexts=None):
        """Configure all given interfaces under self.topo
        Sample intferface yaml config:

        hardware: TenGigabitEthernet0/8
        security: 100
        nameif: inside1
        bridge_group:
            number: 1
            ipv4_address: 154.0.0.1
            ipv4_netmask: 255.255.255.0

        :param contexts: optional, context list for interface configuration
        :return: None
        """
        intfs = self.parse_ctx_contents(self.topo.interfaces) if 'interfaces' in self.topo else []

        for intf, ctx in intfs:
            if contexts and ctx not in contexts:
                continue

            sec_level = intf.get('security', None)
            vlan = intf.get('vlan', None)
            nameif = intf.get('nameif', None)
            mac = intf.get('mac', None)

            management_only = intf.get('management_only', None)

            if management_only:
                if self.topo.mode == "cluster":
                    cluster_ip_pool = intf.get('cluster_ip_pool', None)
                    if not cluster_ip_pool:
                        raise RuntimeError('ip_pool is not defined')

                    ipv4_addr = intf.get('ipv4_address', None)
                    netmask = intf.get('ipv4_netmask', None)
                    ipv6_addr = intf.get('ipv6_address', None)
                    prefix = intf.get('ipv6_prefix', None)

                    self.config_cluster_individual_mgmt_interface(
                                 intf.hardware,
                                 nameif=nameif,
                                 sec_level=sec_level,
                                 vlan=vlan,
                                 ipv4_addr=ipv4_addr,
                                 netmask=netmask,
                                 ipv6_addr=ipv6_addr,
                                 prefix=prefix,
                                 mac=mac,
                                 cluster_ip_pool=cluster_ip_pool,
                                 ctx=ctx)
                else:
                    ipv4_addr = intf.get('ipv4_address', None)
                    netmask = intf.get('ipv4_netmask', None)
                    ipv4_standby = intf.get('ipv4_standby', None)
                    ipv6_addr = intf.get('ipv6_address', None)
                    prefix = intf.get('ipv6_prefix', None)
                    ipv6_standby = intf.get('ipv6_standby', None)

                    self.config_mgmt_interface(
                                            intf.hardware,
                                            nameif=nameif,
                                            sec_level=sec_level,
                                            vlan=vlan,
                                            ipv4_addr=ipv4_addr,
                                            ipv4_standby=ipv4_standby,
                                            netmask=netmask,
                                            ipv6_addr=ipv6_addr,
                                            prefix=prefix,
                                            ipv6_standby=ipv6_standby,
                                            mac=mac,
                                            ctx=ctx
                                            )
            else:
                if self.topo.fmode == 'rfw':
                    ipv4_addr = intf.get('ipv4_address', None)
                    netmask = intf.get('ipv4_netmask', None)
                    ipv4_standby = intf.get('ipv4_standby', None)
                    ipv6_addr = intf.get('ipv6_address', None)
                    prefix = intf.get('ipv6_prefix', None)
                    ipv6_standby = intf.get('ipv6_standby', None)

                    self.config_ip_interface(intf.hardware, nameif=nameif, sec_level=sec_level,
                        vlan=vlan, ipv4_addr=ipv4_addr, netmask=netmask, ipv4_standby=ipv4_standby,
                        ipv6_addr=ipv6_addr, prefix=prefix, ipv6_standby=ipv6_standby, mac=mac,
                        ctx=ctx)

                elif self.topo.fmode == 'tfw':
                    ipv4_addr = intf.bridge_group.get('ipv4_address', None)
                    mask = intf.bridge_group.get('ipv4_netmask', None)
                    ipv4_standby = intf.bridge_group.get('ipv4_standby', None)
                    ipv6_addr = intf.bridge_group.get('ipv6_address', None)
                    prefix = intf.bridge_group.get('ipv6_prefix', None)
                    ipv6_standby = intf.bridge_group.get('ipv6_standby', None)

                    self.config_bvi_interface(intf.hardware, nameif=nameif,
                        bridge_group=intf.bridge_group.number,
                        sec_level=sec_level, vlan=vlan,
                        ipv4_addr=ipv4_addr, mask=mask, ipv4_standby=ipv4_standby,
                        ipv6_addr=ipv6_addr, prefix=prefix, ipv6_standby=ipv6_standby, mac=mac,
                        ctx=ctx)

    def config_ipv4_route(self, intf_name, network, netmask, gateway, \
        distance=1, track=None, tunneled=False, ctx=None):
        """Config Ipv4 route

        :param intf_name: interface name with associated routes
        :param network: destination network
        :param netmask: desitnation netmask
        :param gateway: gateway ip addr
        :param distance: (Optional) Distance metric for this route
        :param track: (Optional) tracked object number to install route
        :param tunneled: (Optional) Enable the default tunnel gateway option
        :param ctx: context name only for multi mode
        :return: None

        Comments:
            # Create an ipv4 route: route inside1 1.1.1.0 255.255.255.0 1.1.2.1
            >>> configure_ipv4_route('inside1', '1.1.1.0', '255.255.255.0', '1.1.2.1')

        """
        cmd = '\nroute {intf} {nw} {mask} {gw} '.format(
            intf=intf_name, nw=network, mask=netmask, gw=gateway)
        if tunneled:
            cmd += 'tunneled'
        else:
            cmd += '{distance} '.format(distance=distance)
            if track:
                cmd += 'track {track}'.format(track=track)

        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_ipv6_route(self, intf_name, network, prefix, gateway, \
        hop=None, tunneled=False, ctx=None):
        """Config Ipv6 route

        :param intf_name: interface name with associated routes
        :param network: destination network
        :param prefix: desitnation network prefix
        :param gateway: gateway ip addr
        :param ctx: context name only for multi mode
        :return: None

        Comments:
            # Create an ipv6 route: ipv6 route inside1 32::/64 33::1
            >>> configure_ipv6_route('inside1', '32::', 64, '33::1')

        """
        cmd = '\nipv6 route {intf} {nw}/{prefix} {gw} '.format(
            intf=intf_name, nw=network, prefix=prefix, gw=gateway)
        if hop:
            cmd += '{hop}'.format(hop=hop)
        elif tunneled:
            cmd += 'tunnled'
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_routes(self):
        """Configure all given routes under self.topo
        Sample route yaml config:

        ipv4_route:
            - network: 22.0.0.0
              netmask: 255.255.0.0
              gateway: 154.0.0.5
        ipv6_route:
            - network: '2200::'
              prefix: 64
              gateway: 1540::5

        :return: None
        """
        if self.topo.fmode != 'rfw':
            raise RuntimeError('Route can be only configured in routed mode')

        ipv4_routes = ipv6_routes = []
        if self.topo.cmode == 'sfm' and 'interfaces' in self.topo:
            ipv4_routes = [(intf.get('ipv4_route', []), intf.nameif, None) \
                for intf in self.topo.interfaces]
            ipv6_routes = [(intf.get('ipv6_route', []), intf.nameif, None) \
                for intf in self.topo.interfaces]
        elif self.topo.cmode == 'mfm' and 'interfaces' in self.topo:
            ipv4_routes = [(config[0].get('ipv4_route', []), config[0].nameif, config[1]) \
                for config in self.parse_ctx_contents(self.topo.interfaces)]
            ipv6_routes = [(config[0].get('ipv6_route', []), config[0].nameif, config[1]) \
                for config in self.parse_ctx_contents(self.topo.interfaces)]

        for ipv4_route in ipv4_routes:
            routes = ipv4_route[0]
            intf_name = ipv4_route[1]
            ctx = ipv4_route[2]
            for route in routes:
                distance = route.get('distance', 1)
                track = route.get('track', None)
                tunneled = route.get('tunnled', False)
                self.config_ipv4_route(intf_name, route.network, route.netmask, route.gateway, \
                    distance=distance, track=track, tunneled=tunneled, ctx=ctx)

        for ipv6_route in ipv6_routes:
            routes = ipv6_route[0]
            intf_name = ipv6_route[1]
            ctx = ipv6_route[2]
            for route in routes:
                hop = route.get('hop', None)
                tunneled = route.get('tunnled', False)
                self.config_ipv6_route(intf_name, route.network, route.prefix, route.gateway, \
                    hop=hop, tunneled=tunneled, ctx=ctx)

    def config_access_list(self, acl_id, action, dst, protocol='', src='', acl_type='', ctx=None):
        """Config an access list

        :param acl_id: Access list identifier
        :param action: access list action. eg, permit, deny.
        :param protocol: protocol
        :param src: source
        :param dst: destination
        :param acl_type: access list type. it can be extended, standard, webtype, or nothing.
        :return: None

        Comments:
            # create access list: access-list 100 permit ip any any
            >>> config_access_list('100', 'permit', protocol='ip', src='any', dst='any')

        """
        cmd = '\naccess-list {acl_id} '.format(acl_id=acl_id)
        if acl_type == '':
            cmd += '{a} {p} {src} {dst}'.format(a=action, p=protocol, src=src, dst=dst)
        elif acl_type == 'standard':
            cmd += 'standard {a} {dst}'.format(a=action, dst=dst)
        elif acl_type == 'webtype':
            cmd += 'webtype {a} {p} {dst}'.format(a=action, p=protocol, dst=dst)
        elif acl_type == 'extended':
            cmd += 'extended {a} {p} {src} {dst}'.format(a=action, p=protocol, src=src, dst=dst)

        self.config(cmd, ctx, timeout=30, exception_on_bad_config=True)

    def config_access_lists(self, contexts=None):
        """Config all given access lists under self.topo
        Sample data yaml file:

        - access_list: 100
          action: permit
          protocol: tcp
          source: any
          destination: any

        :param contexts: optional, context list
        :return: None
        """
        acls = self.parse_ctx_contents(self.topo.access_list) if 'access_list' in self.topo else []

        for acl, ctx in acls:
            if contexts and ctx not in contexts:
                continue

            protocol = acl.get('protocol', '')
            src = acl.get('source', '')
            acl_type = acl.get('acl_type', '')
            self.config_access_list(acl_id=acl.access_list, action=acl.action, \
                dst=acl.destination, protocol=protocol, src=src, acl_type=acl_type, ctx=ctx)

    def config_access_group(self, acl_id, direction, intf_name='', ctx=None):
        """Config an access group

        :param acl_id: access list identifier
        :param direction: traffic direction
        :param intf_name: interface name to be applied with access group
        :param ctx: context name only for multi mode
        :return: None

        Comments:
            # create access group: access-group 100 in interface inside1
            >>> config_access_group('100', 'in', 'inside1')
            # create a global access group: access-group 100 global
            >>> config_access_group('100', 'global')

        """
        cmd = '\naccess-group {acl_id} '.format(acl_id=acl_id)
        if direction == 'global':
            cmd += 'global'
        else:
            cmd += '{d} interface {intf}'.format(d=direction, intf=intf_name)

        self.config(cmd, ctx, timeout=60, exception_on_bad_config=True)

    def config_access_groups(self, contexts=None):
        """Config all given access groups under self.topo
        Sample yaml config:

        access_group:
            - access_list: 100
              direction: in
              interface: outside1
            - access_list: 100
              direction: in
              interface: outside2

        :param contexts: optional, context list
        :return: None

        """
        acgs = self.parse_ctx_contents(\
            self.topo.access_group) if 'access_group' in self.topo else []

        for acg, ctx in acgs:
            if contexts and ctx not in contexts:
                continue

            intf_name = acg.get('interface', '')
            self.config_access_group(acl_id=acg.access_list, direction=acg.direction, \
                intf_name=intf_name, ctx=ctx)

    def config_class_map(self, name, cm_type='', action='', matches=None, desc='', ctx=None):
        """Configure class map

        :param name: class map name to be configured
        :param desc: (Optional) description
        :param cm_type: (Optional) class map type that can be inspect <protocol>, regex, management
        :param action: (Optional) action to be taken that can be match-any, match-all or None.
        :param ctx: (Optional) context name only for multi mode
        :param matches: (Optional) list of detailed match items.
        :return: None

        Example:
            # Create a class map 'test1' to inspect im that match ip addr 15.0.0.1 255.255.255.255
            >>> match = [{'option':'ip-address', 'item':'15.0.0.1 255.255.255.255'}]
            >>> config_class_map(name='test1', cm_type='inspect im', match=match)

        """
        if cm_type:
            if cm_type == 'regex':
                action = 'match-any'
            cmd = '\nclass-map type {t} {a} {n}'.format(t=cm_type, a=action, n=name)
        else:
            cmd = '\nclass-map {n}'.format(n=name)

        if desc:
            cmd += '\ndescription {d}'.format(d=desc)

        if matches:
            for match in matches:
                cmd += '\nmatch {option} {item}\n'.format(option=match['option'], item=match['item'])
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_class_maps(self):
        """ Config all given class maps under self.topo
        Sample ASA class map topo:

        class_map:
            - name: AppFW
              match:
                  - option: port
                    item: tcp eq www
            - name: ASDM_HIGH_SECURITY_METHODS
              type: inspect http
              action: match-all
              match:
                  - option: not request
                    item: method get
                  - option: not request
                    item: method head

        :return: None

        """
        class_maps = self.parse_ctx_contents(\
            self.topo.class_map) if 'class_map' in self.topo else []

        for class_map, ctx in class_maps:
            cm_type = class_map.get('type', '')
            action = class_map.get('action', '')
            matches = class_map.get('match', [])
            self.config_class_map(
                name=class_map.name, cm_type=cm_type, action=action, matches=matches, ctx=ctx)

    def config_policy_map(self, name, policy_type=None, protocol=None, desc=None, \
        parameters=None, matches=None, classes=None, apply_to=None, ctx=None):
        """Configure ASA Policy Map and Apply to Inspection Class

        :param name: name of the policy map to be configured
        :param policy_type: type of the policy map
        :param protocl: protocl name to be inspected
        :param desc: policy map description
        :param parameters: policy parameters as a dict. eg,
            parameters = {
                'request-queue': 9999999,
                'tunnel-limit': 9999999,
                'timeout': {
                    'pdp-context': 60:00:00,
                    't3-response': 0:00:30
                }
            }
        :param matches: match items in policy map as a list
        :param classes: sub classes under policy map as a list
        :param apply_to: apply-to policy info
        :param ctx: (Optional) context name only for multi mode
        :return: None

        """
        if policy_type:
            cmd = '\npolicy-map type {t} {p} {n}'.format(t=policy_type, p=protocol, n=name)
        else:
            cmd = '\npolicy-map {}'.format(name)
        if desc:
            cmd += '\ndescription {}'.format(desc)

        if parameters:
            cmd += '\nparameters'
            for key, value in parameters.items():
                if key == 'timeout':
                    for t_key, t_value in value.items():
                        cmd += '\ntimeout {k} {v}'.format(k=t_key, v=t_value)
                elif key == 'message-length':
                    for m_key, m_value in value.items():
                        if m_key == 'all':
                            cmd += '\nmessage-length maximum {}'.format(m_value)
                        else:
                            cmd += '\nmessage-length maximum {k} {v}'.format(k=m_key, v=m_value)
                elif key == 'protocol-violation':
                    cmd += '\nprotocol-violation action {}'.format(value)
                else:
                    cmd += '\n{k} {v}'.format(k=key, v=value)
        if matches:
            for match in matches:
                cmd += '\nmatch {opt} {item}'.format(opt=match['option'], item=match['item'])
                if 'action' in match:
                    cmd += '\n{}'.format(match['action'])
        if classes:
            for cls in classes:
                cmd += '\nclass {name}\n{action}'.format(name=cls['name'], action=cls['action'])
        if apply_to:
            cmd += '\npolicy-map {}'.format(apply_to['policy'])
            cmd += '\nclass {}'.format(apply_to['class_map'])
            if policy_type:
                cmd += '\n{t} {p} {n}'.format(t=policy_type, p=protocol, n=name)

        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_policy_maps(self):
        """Config all policy maps under self.topo
        Sample topo for policy map:

        policy_map:
          name: gtpmap
          type: inspect
          protocol: gtp
          apply_to:
            policy: global_policy
            class_map: inspection_default
          description: 'description gtp Inspection Policy'
          parameters:
            request-queue: 9999999
            timeout:
              pdp-context: 60:00:00
              t3-response: 0:00:30
            tunnel-limit: 9999999

        :return: None
        """
        policy_maps = self.parse_ctx_contents(\
            self.topo.policy_map) if 'policy_map' in self.topo else []

        for policy_map, ctx in policy_maps:
            policy_type = policy_map.get('type', None)
            protocol = policy_map.get('protocol', None)
            desc = policy_map.get('description', None)
            parameters = policy_map.get('parameters', None)
            matches = policy_map.get('match', None)
            classes = policy_map.get('class', None)
            apply_to = policy_map.get('apply_to', None)
            self.config_policy_map(\
                name=policy_map.name, policy_type=policy_type, protocol=protocol, desc=desc, \
                parameters=parameters, matches=matches, classes=classes, apply_to=apply_to, ctx=ctx)

    def enable_flow_offload(self, enable, ctx=None):
        """Toggle flow offload for SSP device only

        :param enable: boolean to enable/disable flow offload
        :param ctx: context name only for multi mode
        :return: None

        """
        if self.topo.cmode == 'sfm':
            offload_info = self.execute('show flow-offload info', None)
        elif self.topo.cmode == 'mfm':
            offload_info = self.execute('show flow-offload info', 'system')
        match = re.search('Current running state *: *(\w+)', offload_info)
        current_state = AsaConfigConstants.STATE[match.group(1).lower()]

        if enable != current_state:
            if enable:
                self.config('flow-offload enable', ctx)
            else:
                self.config('no flow-offload enable', ctx)
            self.reload()
        return current_state

    def config_flow_offload(self, class_name=None, policy_map=None, ctx=None):
        """Config flow offload for SSP device only

        :param class_name: class map name to apply offload
        :param policy_map: policy map name to apply offload
        :param ctx: (Optional) context name only for multi mode
        :return: None

        """
        
        cmd = '\npolicy-map {}'.format(policy_map)
        cmd += '\nclass {}'.format(class_name)
        cmd += '\nset connection advanced-options flow-offload\n'
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_flow_offloads(self):
        """Config flow offload from self.topo

        :return: None

        """
        offloads = self.parse_ctx_contents(\
            self.topo.flow_offload) if 'flow_offload' in self.topo else []

        for offload, ctx in offloads:
            self.config_flow_offload(\
                class_name=offload.class_map, policy_map=offload.apply_to, ctx=ctx)

    def config_syslog(self, mgmt_intf, syslog_level, syslog_server_ip, ctx=None):
        """Config ASA syslog

        :param mgmt_inft: Management interface
        :param syslog_level: syslog level
        :param syslog_server_ip: syslog server ip addr
        :param ctx: context name only for multi mode
        :return: None

        """
        cmd = '\nno logging buffered'
        cmd += '\nlogging trap {level}'.format(level=syslog_level)
        cmd += '\nlogging host {intf} {server}'.format(intf=mgmt_intf, server=syslog_server_ip)
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_netflow(self, mgmt_intf, netflow_server_ip, ctx=None):
        """ Config ASA netflow

        :param mgmt_inft: Management interface
        :param syslog_server_ip: netflow server ip addr
        :param ctx: context name only for multi mode
        :return: None

        """
        cmd = '\nflow-export destination {intf} {server} 2055'.format(
            intf=mgmt_intf, server=netflow_server_ip)
        # cmd += 'policy-map global_policy\n'
        # cmd += 'class class-default\n'
        # cmd += 'flow-export event-type all destination %s\n' % netflow_server_ip
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_regex(self, name, pattern, ctx=None):
        """Config regular expression

        :param name: name of the regex to be configured
        :param pattern: regular expression pattern
        :param ctx: (Optional) context name only for multi mode
        :return: None

        """
        cmd = '\nregex {name} {pattern}'.format(name=name, pattern=pattern)
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_regexs(self):
        """Config all given regular expression under self.topo
        Sample yaml config:

        regex:
            - name: url1
              pattern: 006066c.netsolhost.com
            - name: url2
              pattern: 021embratel.tripod.com.br

        :return: None

        """
        regexs = self.parse_ctx_contents(self.topo.regex) if 'regex' in self.topo else []

        for regex, ctx in regexs:
            self.config_regex(name=regex.name, pattern=regex.pattern, ctx=ctx)

    def config_network_object_range(self, name, start_ip, count, desc=None, ctx=None):
        """Config a network object with a range of ip

        :param name: name of the network obj to be configured
        :param start_ip: start ip
        :param count: total number of ip
        :param desc: (Optional) network object description
        :param ctx: (Optional) context name only for multi mode
        :return: None

        """
        cmd = '\nobject network {}'.format(name)
        if desc:
            cmd += '\ndescription {}'.format(desc)
        cmd += '\nrange {start} {end}'.format(start=start_ip, end=self.incr_ip(start_ip, count))
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_network_object_subnet(self, name, network, mask, desc=None, ctx=None):
        """Config a network object with a subnet (IPv4/v6)

        :param name: name of the network obj to be configured
        :param network: subnet. can be either IPv4 or v6
        :param mask: netmask/prefix
        :param desc: (Optional) network object description
        :param ctx: (Optional) context name only for multi mode
        :return: None

        """
        cmd = '\nobject network {}'.format(name)
        if desc:
            cmd += '\ndescription {}'.format(desc)
        if ':' in network:
            cmd += '\nsubnet {nw}/{mask}'.format(nw=network, mask=mask)
        else:
            cmd += '\nsubnet {nw} {mask}'.format(nw=network, mask=mask)
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_network_object_host(self, name, host, desc=None, ctx=None):
        """Config a network object with a single host

        :param name: name of the network obj to be configured
        :param host: single host
        :param desc: (Optional) network object description
        :param ctx: (Optional) context name only for multi mode
        :return: None

        """
        cmd = '\nobject network {}'.format(name)
        if desc:
            cmd += '\ndescription {}'.format(desc)
        cmd += '\nhost {}'.format(host)
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_network_objects(self):
        """Config all given network objects under self.topo
        Sample network objects:

        network_object:
            - name: obj1
              range:
                  start_ip: 1.1.1.1
                  count: 10
            - name: obj2
              subnet:
                ipv4_network: 2.2.2.0
                netmask: 255.255.255.0
            - name: obj3
              host: 3.3.3.3
        """
        objects = self.parse_ctx_contents(\
            self.topo.network_object) if 'network_object' in self.topo else []

        for obj, ctx in objects:
            desc = obj.get('description', None)
            if 'range' in obj:
                self.config_network_object_range(
                    obj.name, obj.range.start_ip, obj.range.count, desc, ctx)
            elif 'subnet' in obj:
                if 'ipv4_network' in obj.subnet:
                    network = obj.subnet.ipv4_network
                    mask = obj.subnet.netmask
                elif 'ipv6_network' in obj.subnet:
                    network = obj.subnet.ipv6_network
                    mask = obj.subnet.prefix
                self.config_network_object_subnet(obj.name, network, mask, desc, ctx)
            elif 'host' in obj:
                self.config_network_object_host(obj.name, obj.host, desc, ctx)

    def config_network_obj_group(self, name, objects=None, hosts=None, ctx=None):
        """Config network object group

        :param name: name of the network object group to be configured
        :param objects: list of names of objects to be added under the object group
        :param hosts: list of hosts to be added under the object group
        :return: None

        """
        cmd = '\nobject-group network {}'.format(name)
        if objects:
            for obj in objects:
                cmd += '\nnetwork-object object {}'.format(obj)

        if hosts:
            for host in hosts:
                count = host.get('count', 1)
                start_ip = host['start_ip']
                for i in range(count):
                    cmd += '\nnetwork-object host {}'.format(self.incr_ip(start_ip, i))

        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_network_obj_groups(self):
        """Config all given network object groups under self.topo
        Sample config:

        network_object_group:
          - name: inside1-0
            hosts:
              - start_ip: 22.0.0.1
                count: 500
          - name: outside1-0
            hosts:
              - start_ip: 32.0.0.1
                count: 500
          - name: test1
            objects:
              - name: obj1
              - name: obj2
              - name: obj3
            hosts:
              - start_ip: 10.0.0.1
                count: 500

        :return: None

        """
        obj_groups = self.parse_ctx_contents(\
            self.topo.network_object_group) if 'network_object_group' in self.topo else []

        for obj_group, ctx in obj_groups:
            objects = obj_group.get('objects', None)
            # if objects:
            #     objects = [object.name for object in objects]
            hosts = obj_group.get('hosts', None)

            self.config_network_obj_group(
                name=obj_group.name, objects=objects, hosts=hosts, ctx=ctx)

    def config_dynamic_pat(self, pat_name, network, mask, in_intf, ex_inft, pool, ctx=None):
        """Config dynamic PAT

        :param pat_name: name of the pat to be configured
        :param subnet: network to be translated
        :param mask: network mask of the network to be translated
        :param in_intf: interface that pat from
        :param ex_inft: interface that pat to
        :param pool: pat pool
        :param ctx: (Optional) context name only for multi mode
        :return: None

        """
        cmd = '\nobject network {name}'.format(name=pat_name)

        if ':' in network:
            cmd += '\nsubnet {nw}/{prefix}'.format(nw=network, prefix=mask)
        else:
            cmd += '\nsubnet {nw} {mask}'.format(nw=network, mask=mask)

        cmd += '\nnat ({in_intf},{ex_inft}) dynamic pat-pool {pool}'.format(
            in_intf=in_intf, ex_inft=ex_inft, pool=pool)
        self.config(cmd, ctx, exception_on_bad_config=True)

    def config_dynamic_pats(self):
        """ Config all given dynamic PAT under self.topo
        Sample yaml:

        dynamic_pat:
            - name: pat-22
              ipv4_network: 22.0.0.0
              netmask: 255.0.0.0
              internal: inside1
              external: outside1
              pool: global-174

        :return: None

        """
        pats = self.parse_ctx_contents(self.topo.dynamic_pat) if 'dynamic_pat' in self.topo else []

        for pat, ctx in pats:
            if 'ipv4_network' in pat:
                network = pat.ipv4_network
                mask = pat.netmask
            elif 'ipv6_network' in pat:
                network = pat.ipv6_network
                mask = pat.prefix
            self.config_dynamic_pat(pat_name=pat.name, network=network, mask=mask, \
                in_intf=pat.internal, ex_inft=pat.external, pool=pat.pool, ctx=ctx)

    def config_virtual_licensing(self, throughput_level, cert_type, name_server,
                                 call_home_url, idtoken_url, ctx=None, max_wait=30, wait_interval=10):
        """ Check licensing and configure if necessary

        :param throughput_level: set license throughput level [100M, 1G, 2G, 10G]
        :param cert_type: smart agent's embedded root certificate can be one of
                          'production' or 'development'
        :param name_server: dns server for domain resolution
        :param call_home_url: call home url
        :param idtoken_url: alpha licensing server idtoken registration key
        :param max_wait: maximum wait time for asa to register (in seconds)
        :param wait_interval: time to wait between license checks
        :return:
        """
        output = self.execute('show license features')
        if 'Unlicensed' not in output:
            return True, 'Licensing already configured'

        cmd = 'call-home\n'
        cmd += 'profile license\n'
        cmd += 'destination address http ' + call_home_url
        self.config(cmd, ctx, exception_on_bad_config=True)

        cmd = 'show run interface Management0/0'
        if 'nameif management' not in self.execute(cmd, ctx):
            cmd = 'interface Management0/0\nnameif management'
            self.config(cmd, ctx, exception_on_bad_config=True)
        output = self.execute('show run dns')
        if name_server not in output:
            cmd = 'dns domain-lookup management\n'
            cmd += 'DNS server-group DefaultDNS\n'
            cmd += 'name-server ' + name_server
            self.config(cmd, ctx, exception_on_bad_config=True)

        url = urlparse(call_home_url)
        cmd = 'ping ' + url.hostname
        replies = re.findall('!', self.execute(cmd, ctx))
        if len(replies) < 3:
            return False, 'Issue connecting to license server'

        cmd = 'license smart\n'
        cmd += 'feature tier standard\n'
        cmd += 'throughput level ' + throughput_level
        self.config(cmd, ctx, exception_on_bad_config=True)

        output = self.execute('show version | inc Image', ctx)
        if 'Release' in output:
            self.execute('debug menu license 25 ' + cert_type)

        try:
            response = urllib.request.urlopen(idtoken_url)
            if response.status == 200:
                idtoken = response.read()
                idtoken = idtoken.decode('utf-8').strip()
            else:
                return False, 'Unable to download idtoken'
        except Exception as e:
            return False, str(e)

        cmd = 'license smart register idtoken {} force'.format(idtoken)
        self.execute(cmd, ctx)

        output = self.execute('show license status', ctx)
        while 'UNREGISTERED' in output and max_wait >= 0:
            time.sleep(wait_interval)
            output = self.execute('show license status', ctx)
            max_wait -= wait_interval
        if 'Status: REGISTERED' in output:
            return True, 'Device successfully registered'
        else:
            return False, output

    def config_ssh(self, ssh_user, ssh_pass, stricthostkeycheck=False,
                   intf='Management0/0', nameif='management', ssh_timeout=5,
                   ssh_version=2, ctx=None):
        """ Configure ssh on host

        :param ssh_user: ssh user
        :param ssh_pass: ssh password
        :param stricthostkeycheck: Enables SSH host key checking for the
                                   on-board Secure Copy (SCP) client
        :param intf: physical interface name to accept ssh connections on
        :param nameif: logical interface name to accept ssh connections on
        :param ssh_timeout: ssh timeout
        :param ssh_version: ssh version
        :param ctx:
        :return:
        """

        cmd = 'username {} password {}'.format(ssh_user, ssh_pass)
        self.config(cmd, ctx, exception_on_bad_config=True)

        cmd = 'interface {}\nnameif {}'.format(intf, nameif)
        self.config(cmd, ctx, exception_on_bad_config=True)

        if stricthostkeycheck:
            cmd = 'ssh stricthostkeycheck\n'
        else:
            cmd = 'no ssh stricthostkeycheck\n'

        ssh_config = self.execute('show run | inc ssh')
        # make sure to not execute the following command if already exists
        ssh_route = 'ssh 0.0.0.0 0.0.0.0 {}'.format(nameif)

        if ssh_route not in ssh_config:
            cmd += 'ssh 0.0.0.0 0.0.0.0 {}\n'.format(nameif)
        cmd += 'ssh timeout {}\n'.format(ssh_timeout)
        cmd += 'ssh version {}\n'.format(ssh_version)
        cmd += 'ssh scopy enable\n' # used for binary upgrades
        cmd += 'aaa authentication ssh console LOCAL\n'
        cmd += 'ssh key-exchange group dh-group1-sha1'
        self.config(cmd, ctx, exception_on_bad_config=True)

    def show_cpu(self):
        """Show ASA CPU

        :return: System cpu usage. For cluster mode, return max cpu usage across all units

        """
        ctx = None if self.topo.cmode == 'sfm' else 'system'
        if self.topo.mode == 'standalone':
            show_cpu = self.execute('show cpu usage', ctx)
            match = re.search('(\d+)%', show_cpu)
            return int(match.group(1)) if match else None
        elif self.topo.mode == 'cluster':
            max_cpu = 0
            show_cpu = self.execute('cluster exec show cpu usage', ctx)\
                .replace('\x00', '').split('\r\n')
            for line in show_cpu:
                if 'CPU utilization' in line:
                    match = re.search('(\d+)%', line)
                    if match:
                        current_cpu = int(match.group(1))
                        max_cpu = current_cpu if current_cpu > max_cpu else max_cpu
                    else:
                        return None
            return max_cpu

    def show_mem(self):
        """Show ASA memory

        :return: System memory usage. In cluster mode, return max memory across all units

        """
        ctx = None if self.topo.cmode == 'sfm' else 'system'
        if self.topo.mode == 'standalone':
            show_mem = self.execute('show memory', ctx)
            match = re.search('(\d+)%', show_mem)
            return 100 - int(match.group(1)) if match else None
        elif self.topo.mode == 'cluster':
            max_mem = 0
            show_mem = self.execute('cluster exec show memory | inc Used', ctx)\
                .replace('\x00', '').split('\r\n')
            for line in show_mem:
                if 'Used memory' in line:
                    match = re.search('(\d+)%', line)
                    if match:
                        current_mem = int(match.group(1))
                        max_mem = current_mem if current_mem > max_mem else max_mem
                    else:
                        return None
            return max_mem

    def show_conns_count(self):
        """Show ASA connections count

        :return: In single mode, return in use and most used conns.
        In multi mode, return total in use and most used conns.
        In cluster mode, return in use, forward, direction, and centralized conns

        """
        ctx = None if self.topo.cmode == 'sfm' else 'system'
        if self.topo.mode == 'standalone':
            if self.topo.cmode == 'sfm':
                show_conn_count = self.execute('show conn count', ctx)
                match = re.search('(\d+) in use, (\d+) most used', show_conn_count)
                if match:
                    return int(match.group(1)), int(match.group(2))
                return None, None
            elif self.topo.cmode == 'mfm':
                show_conn_count = self.execute('show resource usage summary | inc Conns', ctx)\
                    .replace('\x00', '').split('\r\n')
                for line in show_conn_count:
                    match = re.search('Conns *(\d+) *(\d+)', line)
                    if match:
                        return int(match.group(1)), int(match.group(2))
                return 0, 0
        elif self.topo.mode == 'cluster':
            if self.topo.cmode == 'sfm':
                show_conn_count = self.execute('show cluster conn', ctx)
                match = re.search(
                    '(\d+) in use, fwd connection (\d+) in use, dir connection (\d+) in use,'
                    ' centralized connection (\d+) in use', show_conn_count)
                if match:
                    return int(match.group(1)), int(match.group(2)),\
                        int(match.group(3)), int(match.group(4))
                else:
                    return None, None, None, None
            elif self.topo.cmode == 'mfm':
                pass
                # show_conn_count = self.execute('cluster exec '\
                #     'show resource usage summary | inc Conns', ctx)\
                #     .replace('\x00', '').split('\r\n')

                # not supported now

    def show_xlates_count(self):
        """Show ASA Xlates counts

        :return: in use and most used xlates.

        """
        ctx = None if self.topo.cmode == 'sfm' else 'system'
        if self.topo.mode == 'standalone':
            if self.topo.cmode == 'sfm':
                show_xlate_count = self.execute('show xlate count', ctx)
                match = re.search('(\d+) in use, (\d+) most used', show_xlate_count)
                if match:
                    return int(match.group(1)), int(match.group(2))
                else:
                    return None, None
            elif self.topo.cmode == 'mfm':
                show_xlate_count = self.execute('show resource usage summary | inc Xlates', ctx)\
                    .replace('\x00', '').split('\r\n')
                for line in show_xlate_count:
                    match = re.search('Xlates *(\d+) *(\d+)', line)
                    if match:
                        return int(match.group(1)), int(match.group(2))
                    else:
                        return 0, 0
        elif self.topo.mode == 'cluster':
            if self.topo.cmode == 'sfm':
                show_xlate_count = self.execute('show cluster xlate count')
                match = re.search('(\d+) in use \(cluster-wide aggregated\)', show_xlate_count)
                if match:
                    return int(match.group(1)), int(match.group(1))
            elif self.topo.mode == 'mfm':
                pass
                # not supported now

    def show_interface_detail(self, timeout=60):
        """Show ASA interface detail

        :return: Total number of overruns and underruns

        """
        total_overruns = total_underruns = 0
        data_interfaces = defaultdict(set)
        if self.topo.cmode == 'sfm':
            for intf in self.topo.interfaces:
                data_interfaces[None].add(intf.hardware)
                if 'vlan' in intf:
                    data_interfaces[None].add('%s.%s' % (intf.hardware, intf.vlan))
        elif self.topo.fmode == 'mfm':
            for ctx in self.topo.contexts.split():
                if ctx in self.topo.interfaces:
                    intfs = self.topo.interfaces[ctx]
                    for intf in intfs:
                        data_interfaces['system'].add(intf.hardware)
                        if 'vlan' in intf:
                            data_interfaces[ctx].add('%s.%s' % (intf.hardware, intf.vlan))
                            data_interfaces['system'].add('%s.%s' % (intf.hardware, intf.vlan))
                        else:
                            data_interfaces[ctx].add(intf.hardware)

        contexts = [None] if self.topo.cmode == 'sfm' else self.topo.contexts.split()
        if self.topo.cmode == 'mfm':
            contexts.append('system')
        if self.topo.mode == 'standalone':
            for ctx in contexts:
                sh_int = self.execute(
                    'show interface detail', ctx, timeout=timeout).replace('\x00', '')
                overruns, underruns = self._extract_int_stat(sh_int, data_interfaces[ctx])
                total_overruns += overruns
                total_underruns += underruns
        if self.topo.mode == 'cluster':
            for ctx in contexts:
                sh_clu_int = self.execute(
                    'clu exec show interface detail', ctx, timeout=timeout).replace('\x00', '')
                for sh_int in re.split('unit.*:\*{2,}', sh_clu_int):
                    overruns, underruns = self._extract_int_stat(sh_int, data_interfaces[ctx])
                    total_overruns += overruns
                    total_underruns += underruns

        return total_overruns, total_underruns

    def _extract_int_stat(self, sh_int, data_interfaces):
        """Helper function to extract interface info from show_interface_detail
        """
        total_overruns = total_underruns = 0
        matches = [m.start() for m in re.finditer('Interface .*,', sh_int)]
        for index, start in enumerate(matches):
            seg = sh_int[start: matches[index+1]] if index < len(matches)-1 else sh_int[start:]
            intf_name = re.search('Interface *(\S+)', seg).group(1)
            if 'Internal-Data' in seg:
                overruns = underruns = 0
                m_overrun = re.search('(\d+ packets input), \d+ bytes, (\d+) no buffer', seg)
                m_underrun = re.search('(\d+ packets output), \d+ bytes, (\d+) underruns', seg)
                if m_overrun:
                    p_in = m_overrun.group(1)
                    overruns = int(m_overrun.group(2))
                    total_overruns += overruns
                if m_underrun:
                    p_out = m_underrun.group(1)
                    underruns = int(m_underrun.group(2))
                    total_underruns += underruns
                info = 'Interface %s: %s, %s, %s overruns, %s underruns' \
                    % (intf_name, p_in, p_out, overruns, underruns)
                self.logger.info(info)
            elif intf_name in data_interfaces:
                m_in = re.search('(\d+ packets input), \d+ bytes', seg)
                m_out = re.search('(\d+ packets output), \d+ bytes', seg)
                m_drop = re.search('(\d+ packets dropped)', seg)
                intf_p_in = m_in.group(1) if m_in else '0 packets input'
                intf_p_out = m_out.group(1) if m_out else '0 packets output'
                intf_p_drop = m_drop.group(1) if m_drop else '0 packets dropped'
                info = 'Interface %s: %s , %s, %s' \
                    % (intf_name, intf_p_in, intf_p_out, intf_p_drop)
                self.logger.info(info)

        return total_overruns, total_underruns

    def clear_counters(self, *args):
        """Clear ASA counters given counter to be cleared in *args
        Example:
            asa.clear_counters('conn', 'local-host', 'interface')

        :param *args: objects to be cleared
        :return: None

        """
        contexts = self.topo.contexts.split() if self.topo.cmode == 'mfm' else [None]
        if self.topo.mode == 'standalone':
            for ctx in contexts:
                for arg in args:
                    self.execute('clear %s' % arg, ctx, timeout=120)
            if self.topo.cmode == 'mfm':
                if 'asp drop' in args:
                    self.execute('clear asp drop', 'system')
                if 'interface' in args:
                    self.execute('clear interface', 'system')
                if 'resource usage' in args:
                    self.execute('clear resource usage', 'system')
                if 'crash' in args:
                    self.execute('clear crash', 'system')
        elif self.topo.mode == 'cluster':
            for ctx in contexts:
                for arg in args:
                    self.execute('cluster exec clear %s' % arg, ctx, timeout=120)
            if self.topo.cmode == 'mfm':
                if 'asp drop' in args:
                    self.execute('cluster exec clear asp drop', 'system')
                if 'interface' in args:
                    self.execute('cluster exec clear interface', 'system')
                if 'resource usage' in args:
                    self.execute('cluster exec clear resource usage', 'system')
                if 'crash' in args:
                    self.execute('cluster exec clear crash', 'system')

    def parse_ctx_contents(self, configs):
        """Helper function to parse ctx contents
        """
        if self.topo.cmode == 'sfm':
            return [(config, None) for config in configs]
        elif self.topo.cmode == 'mfm':
            output = []
            for ctx, config in configs.items():
                for contents in config:
                    output.append((contents, ctx))
            return output
        else:
            raise RuntimeError('Firewall mode should either be sfm (Single)')

    @staticmethod
    def incr_ip(ip_addr, offset=1):
        """Helper function to increase IP address
        """
        lst_ip = ip_addr.split('.')
        b_1 = format(int(lst_ip[0]), '08b')
        b_2 = format(int(lst_ip[1]), '08b')
        b_3 = format(int(lst_ip[2]), '08b')
        b_4 = format(int(lst_ip[3]), '08b')
        b_ip = b_1+b_2+b_3+b_4
        b_newip = format(int(b_ip, 2) + offset, '032b')
        newd1 = int(b_newip[0:8], 2)
        newd2 = int(b_newip[8:16], 2)
        newd3 = int(b_newip[16:24], 2)
        newd4 = int(b_newip[24:32], 2)
        return '%s.%s.%s.%s' % (newd1, newd2, newd3, newd4)

    def enable_smart_license_features(self, features, timeout=600):
        """Enable smart license features.
        Example:
            asa.enable_smart_license_features(
                                    features=['carrier',
                                              'tier standard',
                                              'strong-encryption'],
                                    timeout = 600)

        :param features: list of features
        :param timeout: wait time until license is 'Authorized'

        :return:
            True" if all features are enabled
            False: if any feature fails

        """
        self.logger.info("Enabling smart license features: %s" % features)
        feature_name_mapping = {
            "tier standard": "Feature tier",
            "strong-encryption": "Strong encryption",
            "carrier": "Carrier",
            "context": "Context"
            }
        if not set(features) <= set(feature_name_mapping.keys()):
           self.logger.error("Feature names not recognized.\
                              \nSupported features are: %s" % feature_name_mapping.keys())
           return False

        for f in features:
            self.config("license smart\nfeature %s" % f, ctx='system')
            retry = 0
            sleep_time = 5
            max_try = timeout/sleep_time
            while retry < max_try:
                out = self.execute("show license entitlement", ctx='system')
                if re.findall("%s:[\r\n]*.*?Enforcement mode: (Authorized|Eval period)" % \
                              feature_name_mapping[f], out, re.S):
                    self.logger.info("Feature '%s' enabled successfully" % f)
                    break
                else:
                    retry += 1
                    time.sleep(5)
            else:
                self.logger.error("Failed to enable smart license feature %s" % f)
                return False

        time.sleep(20)
        self.logger.info("Succeeded enabling smart license features: %s" % features)
        return True
