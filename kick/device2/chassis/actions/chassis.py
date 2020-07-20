from unicon.eal.dialogs import Dialog
from unicon.core.errors import StateMachineError

import re
import logging
import time
import datetime
import collections
import subprocess
import os.path

from kick.device2.general.actions.power_bar import power_cycle_all_ports
from kick.device2.general.actions.basic import BasicDevice, BasicLine
from .patterns import ChassisPatterns
from .statemachine import ChassisStateMachine

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

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

ChassisInitCmds = '''
    top
    terminal length 0
    terminal width 511
'''
MAX_RETRY_COUNT = 3


class Chassis(BasicDevice):
    def __init__(self, chassis_data, *args, **kwargs):
        """
        Chassis instance constructor
        :param chassis_data: dictionary describing the setup for the chassis
        """
        publish_kick_metric('device.chassis.init', 1)

        self.patterns = ChassisPatterns(
            chassis_data['custom']['chassis_login']['username'],
            chassis_data['custom']['chassis_login']['password'],
            chassis_data['custom']['chassis_network']['hostname'],
            chassis_data['custom']['chassis_software'][
                'application_generic'].get('hostname', 'ftd_hostname_not_set')
        )

        # create the state machine that contains the proper attributes.
        hostname = "({}|firepower)".format(
            chassis_data['custom']['chassis_network'].get(
                'hostname', 'chassis_hostname_not_set'))
        self.sm = ChassisStateMachine(self.patterns, hostname, chassis_data)

        # line_class has to be also initialized
        self.line_class = ChassisLine
        self.ssh_vty_line = None
        self.ssh_console_line = None
        self.telnet_console_line = None
        logger.info("Done: Chassis instance created.")
        super().__init__()

    @staticmethod
    def extract_chassis_data_device_configuration(device_configuration):
        """
        Method used to obtain the chassis dictionary from the device
        configuration loaded from the testbed
        :param device_configuration: the device configuration object loaded
        from the testbed
        :return: the chassis data dictionary
        """
        chassis_dict = dict()
        chassis_dict.update({'connections': device_configuration.connections})
        chassis_dict.update({'custom': device_configuration.custom})
        chassis_dict['custom']['chassis_network'].update(
            {'interfaces': device_configuration.interfaces})
        return chassis_dict

    def ssh_vty(self, ip, port, username='admin', password='Admin123',
                timeout=None, line_type='ssh', rsa_key=None):
        self.ssh_vty_line = super().ssh_vty(
            ip, port, username=username, password=password, timeout=timeout,
            line_type='ssh_vty')
        return self.ssh_vty_line

    def ssh_console(self, ip, port, username='vppuser', password='vppuser',
                    timeout=None, en_password='vppuser'):
        self.ssh_console_line = super().ssh_console(
            ip, port, username=username, password=password, timeout=timeout,
            en_password=en_password)
        return self.ssh_console_line

    def telnet_console_with_credential(self, ip, port, username='vppuser',
                                       password='vppuser', timeout=None,
                                       en_password='vppuser'):
        self.telnet_console_line = super().telnet_console_with_credential(
            ip, port, username, password, timeout, en_password)
        return self.telnet_console_line


class ChassisLine(BasicLine):
    def __init__(self, spawn, sm, type, timeout=None):
        super().__init__(spawn, sm, type, timeout)
        self.line_type = 'ChassisLine'
        self.power_bar_server = []
        self.power_bar_port = []
        self.power_bar_user = []
        self.power_bar_pwd = []
        self.init_terminal()

    def init_terminal(self):
        """Initialize terminal size."""
        try:
            self.go_to('mio_state', timeout=60)
        except StateMachineError as exc:
            logger.error(
                'Cannot initialize MIO terminal in Chassis: {}'.format(
                    str(exc)),
                exc_info=True)
            return

        self.execute_lines(ChassisInitCmds)

    def wait_until_device_on(self, timeout=600):
        """Waits until device is on

        :param timeout: wait time for the device to boot up
        :return None

        """

        # The system will reboot, wait for the following prompts
        d1 = Dialog([
            ['vdc 1 has come online', None, None, False, False],
            ['SW-DRBG health test passed', None, None, False, False],
        ])
        d1.process(self.spawn_id, timeout=timeout)

        d1 = Dialog([
            ['{} login: '.format(self.sm.patterns.chassis_hostname),
             'sendline({})'.format(self.sm.patterns.chassis_username),
             None, True, False],
            ['Password:',
             'sendline({})'.format(self.sm.patterns.chassis_password), None,
             True, False],
            ['.*Successful login attempts for user.*', None, None, False,
             False],
        ])
        d1.process(self.spawn_id, timeout=60)

        # sleep 120 seconds to avoid errors like:
        # FPR4120-1-A# scope system
        # Software Error: Exception during execution:
        # [Error: Timed out communicating with DME]
        # after chasis is upgraded, device is rebooted
        time.sleep(120)
        self.execute_lines('\n')
        self.init_terminal()

    def _get_download_status(self, image_name):
        """Gets the status of download

        :param image_name: the name of the image. it should look like:
        fxos-k9.2.0.1.68.SPA
        :return: status as 'Downloaded' or 'Downloading'

        """
        output = self.execute('show download-task {} detail | grep State'
                              ''.format(image_name))
        r = re.search('State: (\w+)', output)
        status = 'Unknown'
        if r:
            status = r.group(1)
            logger.info("download status: {}".format(status))
        return status

    def _wait_till_download_complete(self, file_url, wait_upto=1800):
        """Waits until download completes

        :param file_url: should look like one of the following:
            scp://root@10.30.5.104:/auto/stg/automation/ci/ssp/branch/
            abbey_road/sthangad/qpb/sr2/fxos-k9.2.0.1.68.SPA
            tftp://172.23.47.63/cisco-ftd.6.2.0.296.SPA.csp
        :param wait_upto: how long to wait for download to complete in seconds
        :return: None

        """
        if file_url.startswith("scp"):
            try:
                r = re.search('(\w+)://(\w+)@[\w.\-]+:([\w\-./]+):([\w\-./]+)',
                              file_url)
                assert r, "unknown file_url: {}".format(file_url)
                full_path = r.group(4)
            except:
                r = re.search('(\w+)://(\w+)@[\w.\-]+:([\w\-./]+)', file_url)
                assert r, "unknown file_url: {}".format(file_url)
                full_path = r.group(3)
        elif file_url.startswith("tftp"):
            r = re.search('(\w+)://[\w.\-]+/([\w\-./]+)', file_url)
            assert r, "unknown file_url: {}".format(file_url)
            full_path = r.group(2)
        else:
            raise RuntimeError("Incorrect file url download protocol")

        image_name = os.path.basename(full_path)
        start_time = datetime.datetime.now()
        elapsed_time = 0
        download_status = ""
        while elapsed_time < wait_upto:
            logger.info("sleep 10 seconds for download to complete")
            time.sleep(10)
            download_status = self._get_download_status(image_name)
            if download_status == 'Downloaded':
                logger.info("download completed for {}".format(image_name))
                return download_status
            elif download_status == "Downloading":
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
            elif download_status == "Failed":
                return download_status
        raise RuntimeError("download took too long: {}".format(image_name))

    def is_bundle_on_chassis(self, fxos_url):
        """Checks to see if the update bundle is already on the chasis.

        :param fxos_url: address of fxos package
        :return: None

        """

        self.go_to('mio_state')
        existing_packages = self.get_fxos_packages()
        image_name = os.path.basename(fxos_url)
        if image_name in [package.name for package in existing_packages]:
            return True
        return False

    def get_fxos_packages(self):
        """Get packages currently downloaded on the box.
        return: the list of packages available on the box.
        """

        self.go_to('mio_state')
        self.execute_lines('top\nscope firmware')

        output = self.execute('show package', timeout=30)
        find_hyphens = [m.end() for m in re.finditer('-{2,}', output)]

        start = find_hyphens[-1] if find_hyphens else 0
        output = output[start:].strip()

        package_list = []
        Package = collections.namedtuple('Package', ['name', 'version'])
        if output:
            for line in output.split('\n'):
                package_name, package_version = line.split()
                package_list.append(
                    Package(name=package_name, version=package_version))
        return package_list

    def is_fxos_image_on_device(self, fxos_url):
        self.go_to('mio_state')
        image_name = os.path.basename(fxos_url)
        fxos_query = self.execute_lines('top\nscope firmware\nshow package')
        if image_name in fxos_query:
            return True
        return False

    def is_app_image_on_device(self, image_url):
        self.go_to('mio_state')
        image_name = os.path.basename(image_url)
        app_version = re.search(r'\d+\.\d+\.\d+\.\d+', image_name).group(0)
        apps = self.execute_lines('top\nscope ssa\nshow app')
        found = re.search(r'\s+.*?\s*%s\s+' % re.escape(app_version), apps)
        if found:
            return True
        return False

    def download_csp(self, csp_url, file_server_password=""):
        """Download image of application for QP and BS.

        :param csp_url: csp url to download the image
            e.g. scp://pxe@172.23.47.63:/tftpboot/cisco-ftd.6.2.0.297.SPA.csp
        :param file_server_password: sftp server password

        """
        self.go_to('mio_state')
        image_name = os.path.basename(csp_url)
        app_version = re.search(r'\d+\.\d+\.\d+\.\d+', image_name).group(0)
        apps = self.execute_lines('top\nscope ssa\nshow app')
        found_entry = re.search(r'\s+.*?\s*%s\s+' % re.escape(app_version),
                                apps)
        if found_entry:
            logger.info('Found CSP application already registered and '
                        'downloaded on the device.')
            return

        self.execute_lines('top\nscope ssa\nscope app-software')

        retry_count = MAX_RETRY_COUNT

        while retry_count > 0:

            self.spawn_id.sendline('download image {}'.format(csp_url))

            d1 = Dialog([
                ['continue connecting (yes/no)?', 'sendline(yes)', None, True,
                 False],
                ['Password:', 'sendline({})'.format(file_server_password),
                 None, True, False],
                [self.sm.get_state('mio_state').pattern, None, None, False,
                 False],
            ])
            d1.process(self.spawn_id)

            status = self._wait_till_download_complete(csp_url)

            if status == "Failed":
                retry_count -= 1
                if retry_count == 0:
                    raise RuntimeError(
                        "Download failed after {} tries. Please check "
                        "details again: {}".format(MAX_RETRY_COUNT, csp_url))
                logger.info("Download failed. Trying to download {} "
                            "more times".format(retry_count))
            elif status == "Downloaded":
                return

    def parse_firmware_monitor(self):
        """"show firmware Monitor gives something like this: FPRM: Package-
        Vers: 1.1(4.95) Upgrade-Status: Ready.

          Fabric Interconnect A:
            Package-Vers: 2.0(1.68)
            Upgrade-Status: Upgrading

          Chassis 1:
            Server 1:
                Package-Vers: 2.0(1.68)
                Upgrade-Status: Upgrading

        :return: namedtuple

        """

        cmd_lines = """
            top
            scope system
            show firmware monitor
        """

        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)
        fprm = output.find('FPRM:')
        fabric = output.find('Fabric Interconnect A:')
        chassis = output.find('Chassis 1:')

        fprm_section = output[fprm:fabric]
        fprm = self._parse_firmware_monitor_version_status(fprm_section)
        fabric_section = output[fabric:chassis]
        fabric = self._parse_firmware_monitor_version_status(fabric_section)
        chassis_section = output[chassis:]
        chassis = self._parse_firmware_monitor_version_status(chassis_section)

        logger.debug(
            'fprm={}, fabric={}, chassis={}'.format(fprm, fabric, chassis))
        FirmwareMonitor = collections.namedtuple('FirmwareMonitor',
                                                 ['fprm', 'fabric', 'chassis'])
        firmware_monitor = FirmwareMonitor(fprm=fprm, fabric=fabric,
                                           chassis=chassis)

        return firmware_monitor

    def _parse_firmware_monitor_version_status(self, output):
        """
        :param output: should look like:
          FPRM:
            Package-Vers: 1.1(4.95)
            Upgrade-Status: Ready
        :return: version_status

        """

        VersionStatus = collections.namedtuple('VersionStatus', ['version',
                                                                 'status'])
        r = re.search("Package-Vers: ([^\r\n]+)", output)
        if not r:
            version_status = VersionStatus(version='Unknown', status='Unknown')
            return version_status
        v = r.group(1)
        r = re.search("Upgrade-Status: ([^\r\n]+)", output)
        s = r.group(1)
        version_status = VersionStatus(version=v, status=s)
        return version_status

    def get_port_channel_list(self):
        """
        Get port channel list from eth-up/fabric a
        Sample output:

        Port Channel:
            Port Channel Id Name             Port Type          Admin State Oper State       State Reason
            --------------- ---------------- ------------------ ----------- ---------------- ------------
            48              Port-channel48   Cluster            Disabled    Admin Down       Administratively down

        Returns:
            port_channel_list element with named tuple
        """
        cmd_lines = '''
            top
            scope eth-up
            scope fabric a
            show port-channel
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)
        prompt = self.sm.get_state(self.sm.current_state).pattern
        match = re.search(prompt, output)
        if match:
            end = match.span()[0]
            output = output[:end].strip()

        PortChannel = collections.namedtuple('PortChannel', [
            'id', 'name', 'port_type', 'admin_state', 'operational_state'])
        port_channels_list = []
        if output:
            start = [m.end() for m in re.finditer('-{2,}', output)][-1]
            output = output[start:].strip()
            for line in output.split('\n'):
                line = re.split(r'\s{2,}', line.strip())
                pc_id = line[0]
                pc_name = line[1]
                port_type = line[2]
                admin_state = line[3]
                oper_state = line[4]
                port_channels_list.append(PortChannel(id=pc_id, name=pc_name,
                                                      port_type=port_type,
                                                      admin_state=admin_state,
                                                      operational_state=oper_state))

        return port_channels_list

    def get_port_channel_member(self, pc_id):
        """
        Get port channel member ports given port channel id
        Sample output:

        Member Port:
            Port Name       Membership         Oper State       State Reason
            --------------- ------------------ ---------------- ------------
            Ethernet1/1     Down               Admin Down       Administratively down
            Ethernet1/2     Down               Admin Down       Administratively down
            Ethernet1/3     Down               Admin Down       Administratively down
            Ethernet1/4     Down               Admin Down       Administratively down
            Ethernet1/5     Down               Admin Down       Administratively down
            Ethernet1/6     Down               Admin Down       Administratively down
            Ethernet1/7     Down               Admin Down       Administratively down
            Ethernet1/8     Down               Admin Down       Administratively down

        Returns:
            member_ports_list element with named tuple
        """
        self.go_to('mio_state')
        cmd_lines = '''
            top
            scope eth-up
            scope fabric a
            scope port-channel %s
            show member-port
        ''' % pc_id
        output = self.execute_lines(cmd_lines)
        prompt = self.sm.get_state(self.sm.current_state).pattern
        match = re.search(prompt, output)
        if match:
            end = match.span()[0]
            output = output[:end].strip()

        MemberPort = collections.namedtuple('MemberPort', [
            'name', 'membership', 'operational_state'])
        member_ports_list = []
        if output:
            start = [m.end() for m in re.finditer('-{2,}', output)][-1]
            output = output[start:].strip()
            for line in output.split('\n'):
                line = re.split(r'\s{2,}', line.strip())
                name = line[0]
                membership = line[1]
                oper_state = line[2]
                member_ports_list.append(MemberPort(name=name,
                                                    membership=membership,
                                                    operational_state=oper_state))

        return member_ports_list

    def get_logical_device_list(self):
        """Get the list of logical device objects Scope: ssa; Command: show
        logical-device detail.

        # output should look like this:
        # Logical Device:
              Name: 9300-1-cluster
              Description:
              Slot ID: 1,2,3
              Mode: Clustered
              Oper State: Ok
              Template Name: ftd
              Error Msg:
              Switch Configuration Status: Ok
              Resource Profile Name:
              Resource Profile DN:
        :return: logical_device_list

        """

        cmd_lines = '''
            top
            scope ssa
            show logical-device detail
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)

        LogicalDevice = collections.namedtuple('LogicalDevice', [
            'name', 'slot_id', 'mode', 'operational_state', 'template_name', 'error_msg'])
        logical_device_list = []

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Name':
                vname = a_value
                continue
            if a_name == 'Slot ID':
                vslot = a_value
                continue
            if a_name == 'Mode':
                vmode = a_value
                continue
            if a_name.find('Oper') is not -1:
                # Capture 'Operational' and 'Oper'
                if a_name.find('State') is not -1:
                    voper = a_value
                    continue
            if a_name == 'Template Name':
                vtemp = a_value
                continue
            if a_name == "Error Msg":
                verr_msg = a_value
                logical_device = LogicalDevice(name=vname,
                                               slot_id=vslot,
                                               mode=vmode,
                                               operational_state=voper,
                                               template_name=vtemp,
                                               error_msg=verr_msg)
                logical_device_list.append(logical_device)
                logger.info(str(logical_device_list))
                continue

        return logical_device_list

    def get_app_instance_list(self):
        """
        Get the list of application instance objects
        Scope: ssa; Command: show app-instance detail
        FP9300-2-A /ssa # show app-instance detail
        App Name: ftd
        Slot ID: 1
        Admin State: Enabled
        Oper State: Online
        Running Version: 6.2.0.362
        Startup Version: 6.2.0.362
        Cluster State: In Cluster
        Cluster Role: Slave
        Current Job Type: Start
        Current Job Progress: 100
        Current Job State: Succeeded
        Clear Log Data: Available
        Error Msg:
        Hotfixes:
        Externally Upgraded: No
        ...

        :return app_instance_list

        """

        cmd_lines = '''
            top
            scope ssa
            show app-instance detail
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)

        AppInstance = collections.namedtuple('AppInstance', [
            'application_name', 'identifier', 'deploy_type', 'slot_id',
            'admin_state',
            'operational_state', 'running_version', 'startup_version',
            'cluster_oper_state'])
        app_instance_list = []

        identifier = ''
        deploy_type = ''
        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name.startswith('App'):
                # Capture both App Name for new version and Application Name for older version
                vname = a_value
                continue
            if a_name == 'Identifier':
                identifier = a_value
            if a_name == 'Deploy Type':
                deploy_type = a_value
            if a_name == 'Slot ID':
                vslot = a_value
                continue
            if a_name == 'Admin State':
                vadmin = a_value
                continue
            if a_name.startswith('Oper'):
                # Capture 'Operational' and 'Oper'
                if a_name.find('State') is not -1:
                    voper = a_value
                    continue
            if a_name == 'Running Version':
                vrunning = a_value
                continue
            if a_name == 'Startup Version':
                vstartup = a_value
                continue
            if a_name == 'Cluster State':
                # Frangelico and afterwards
                vcluster_s = a_value
                continue
            if a_name == 'Cluster Role':
                # Frangelico and afterwards
                vcluster_r = a_value
                app_instance = AppInstance(application_name=vname,
                                           identifier=identifier,
                                           deploy_type=deploy_type,
                                           slot_id=vslot,
                                           admin_state=vadmin,
                                           operational_state=voper,
                                           running_version=vrunning,
                                           startup_version=vstartup,
                                           cluster_oper_state='{} {}'.format(
                                               vcluster_s, vcluster_r))
                app_instance_list.append(app_instance)
                logger.info(str(app_instance_list))
                continue
            if a_name == 'Cluster Oper State':
                # Everclear
                vcluster_oper_s = a_value
                app_instance = AppInstance(application_name=vname,
                                           identifier=identifier,
                                           deploy_type=deploy_type,
                                           slot_id=vslot,
                                           admin_state=vadmin,
                                           operational_state=voper,
                                           running_version=vrunning,
                                           startup_version=vstartup,
                                           cluster_oper_state=vcluster_oper_s)
                app_instance_list.append(app_instance)
                logger.info(str(app_instance_list))
                continue

        return app_instance_list

    def get_equipped_slot_list(self):
        """Get the list of equipped slot list

        Scope: top
        Command: show server status detail

        # output should look like this:
        # show server status detail
        Server 1/1:
            Slot Status: Equipped
            Equipped Conn Path: A
            Equipped Conn Status: A
            Equipped Managing Instance: A
            Availability: Unavailable
            Admin State: In Service
            Overall Status: Ok
            Oper Qualifier: N/A
            Discovery: Complete
            Current Task:
            Check Point: Discovered

        Server 1/2:
            Slot Status: Equipped
            Equipped Conn Path: A
            Equipped Conn Status: A
            Equipped Managing Instance: A
            Availability: Unavailable
            Admin State: In Service
            Overall Status: Ok
            Oper Qualifier: N/A
            Discovery: Complete
            Current Task:
            Check Point: Discovered

        Server 1/3:
            Slot Status: Empty
            Equipped Conn Path: Unknown
            Equipped Conn Status: Unknown
            Equipped Managing Instance:
            Availability:
            Admin State:
            Overall Status:
            Oper Qualifier:
            Discovery:
            Current Task:
            Check Point:
        :return: slot_list

        """

        cmd_lines = '''
            top
            show server status detail
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)

        slot_list = []

        slot_id = 1
        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Slot Status':
                if a_value == 'Equipped':
                    slot_list.append('{}'.format(slot_id))
                slot_id += 1
        logger.info('======= equipped slot list is {}'.format(str(slot_list)))
        return slot_list

    def get_all_slot_list(self):
        """Get the list of all slots (populated or not)

        Scope: top
        Command: show server status detail

        # output should look like this:
        # show server status detail
        Server 1/1:
            Slot Status: Equipped
            Equipped Conn Path: A
            Equipped Conn Status: A
            Equipped Managing Instance: A
            Availability: Unavailable
            Admin State: In Service
            Overall Status: Ok
            Oper Qualifier: N/A
            Discovery: Complete
            Current Task:
            Check Point: Discovered

        Server 1/2:
            Slot Status: Equipped
            Equipped Conn Path: A
            Equipped Conn Status: A
            Equipped Managing Instance: A
            Availability: Unavailable
            Admin State: In Service
            Overall Status: Ok
            Oper Qualifier: N/A
            Discovery: Complete
            Current Task:
            Check Point: Discovered

        Server 1/3:
            Slot Status: Empty
            Equipped Conn Path: Unknown
            Equipped Conn Status: Unknown
            Equipped Managing Instance:
            Availability:
            Admin State:
            Overall Status:
            Oper Qualifier:
            Discovery:
            Current Task:
            Check Point:
        :return: slot_list

        """

        cmd_lines = '''
            top
            show server status detail
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)

        slot_list = []

        slot_id = 1
        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Slot Status':
                slot_list.append('{}'.format(slot_id))
                slot_id += 1
        logger.info('======= all slot list is {}'.format(str(slot_list)))
        return slot_list

    def get_app_list(self):
        """Get the list of application objects
        Scope: ssa; Command: show app.

        # output should look like this:
        # Application:
        # Name       Version    Description Author     Deploy Type CSP Type    Is Default App
        # ---------- ---------- ----------- ---------- ----------- ----------- --------------
        # asa        9.6.1      N/A         cisco      Native      Application No
        # asa        9.6.1.109  N/A         cisco      Native      Application Yes
        # ftd        6.0.1.1213 N/A         cisco      Native      Application Yes

        :return: the list of apps found

        """

        cmd_lines = '''
            top
            scope ssa
            show app
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        # consume the lines before the dashed lines:
        r = re.search('\s+Is Default App', output)
        if not r:
            return []  # nothing found
        output = output[r.span()[1]:].strip()
        r = re.search('(\-+ ){6}\-+', output)
        if not r:
            return []
        output = output[r.span()[1]:].strip()

        App = collections.namedtuple('App', ['name', 'version', 'description',
                                             'author', 'deploy_type',
                                             'csp_type', 'is_default_app'])
        app_list = []

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            r = re.search('^(\w+)\s+([\d\.]+)\s+([\w/]+)\s+(\w+)\s+(\w+)\s+'
                          '(\w+)\s+(\w+)', line)
            if not r:
                continue
            app = App(name=r.group(1),
                      version=r.group(2),
                      description=r.group(3),
                      author=r.group(4),
                      deploy_type=r.group(5),
                      csp_type=r.group(6),
                      is_default_app=r.group(7),
                      )
            app_list.append(app)

        return app_list

    def get_resource_profiles_list(self):
        """Get the list of resource profile objects
        Scope: ssa; Command: show resource-profile.

        # output should look like this:
        Profile Name       App Name   App Version  Is In Use  Security Model  CPU Logical Core Count RAM Size (MB)  Default Profile Profile Type Description
        ------------------ ---------- ------------ ---------- --------------- ---------------------- -------------- --------------- ------------ -----------
        sensor1_profile    N/A        N/A          No         all                                  6            N/A No              Custom
        sensor1_resource_profile    N/A        N/A          No         all                                  6            N/A No              Custom
        sensor2_profile    N/A        6.2.3.12          No         all                                  8            N/A No              Custom
        sensor2_resource_profile    N/A        N/A          No         all                                 10            N/A No              Custom
        test_resource_profile   N/A        N/A          No         all                                 10            N/A No              Custom test_desc

        :return: the list of resource profiles found
        """

        cmd_lines = '''
            top
            scope ssa
            show resource-profile
        '''
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        # consume the lines before the dashed lines:
        r = re.search('\s+Description', output)
        if not r:
            return []  # nothing found
        output = output[r.span()[1]:].strip()
        r = re.search('(\-+ ){9}\-+', output)
        if not r:
            return []
        output = output[r.span()[1]:].strip()

        Profile = collections.namedtuple(
            'ResourceProfile', ['profile_name', 'app_name', 'app_version',
                                'is_in_use', 'security_model',
                                'cpu_logical_core_count', 'ram_size',
                                'default_profile', 'profile_type',
                                'description'])
        profile_list = []

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            r = re.search('^(\w+)\s+([\w/]+)\s+([\w/\d.]+)\s+(\w+)\s+(\w+)\s+'
                          '([\w/\d]+)\s+([\w/]+)\s+(\w+)\s+(\w+)\s*(\w+)?',
                          line)
            if not r:
                continue
            profile = Profile(
                profile_name=r.group(1),
                app_name=r.group(2),
                app_version=r.group(3),
                is_in_use=r.group(4),
                security_model=r.group(5),
                cpu_logical_core_count=r.group(6),
                ram_size=r.group(7),
                default_profile=r.group(8),
                profile_type=r.group(9),
                description='' if r.group(10) is None else r.group(10))
            profile_list.append(profile)

        return profile_list

    def wait_till(self, stop_func, stop_func_args, wait_upto=300,
                  sleep_step=10):
        """Wait till stop_func returns True.

        :param wait_upto: in seconds
        :param stop_func: when stop_func(stop_func_args) returns True,
            break out.
        :param stop_func_args: see above.
        :param sleep_step: sleeps this long (in seconds between each call to
            stop_func(stop_func_args).
        :return

        """

        start_time = datetime.datetime.now()
        elapsed_time = 0

        while elapsed_time < wait_upto:
            result = stop_func(*stop_func_args)
            logger.debug('wait_till result is:')
            logger.debug(result)
            logger.debug('elapsed_time={}'.format(elapsed_time))
            if result:
                return
            else:
                logger.debug("sleep 10 seconds and test again")
                time.sleep(10)
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
        raise RuntimeError("{}({}) took too long to return True" \
                           "".format(stop_func, stop_func_args))

    def _get_slot_operational_state(self, slot_id):
        """Get operational state for slot_id, e.g. Online.

        :param slot_id: the slot id
        :return: operational state

        """

        cmd_lines = """
            top
            scope ssa
            scope slot {}
            show detail | grep Oper
            """.format(slot_id)
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines)

        r = re.search("Oper(.*) State: ([a-zA-Z0-9_ ]+)", output)

        return r.group(2)

    def is_slot_online(self, slot_id):
        """Check if the slot of slot_id is online.

        :param slot_id: module slot ID
        :return: True if operational state is Online, False otherwise

        """

        return self._get_slot_operational_state(slot_id) == 'Online' or \
               self._get_slot_operational_state(slot_id) == 'Not Available'

    def wait_till_slot_online(self, slot_id, wait_upto=600):
        """Wait till module of slot_id is Online.

        :param slot_id: module slot ID
        :param wait_upto: wait time in seconds
        :return: None

        """
        self.wait_till(self.is_slot_online, (slot_id,), wait_upto=wait_upto)

    def delete_all_logical_devices(self):
        """Delete all logical devices.

        :return: None
        """

        alist = self.get_logical_device_list()
        if alist == None or len(alist) == 0:
            logger.debug('no logical device found, nothing to do.')
        for a in alist:
            cmd_lines = """
                  top
                  scope ssa
                  delete logical-device {}
                  commit-buffer
            """.format(a.name)
            logger.info('logical device {} is to be deleted ...'.format(a.name))

            self.go_to('mio_state')
            self.execute_lines(cmd_lines, exception_on_bad_command=True)

            logger.info('logical-device {} deleted'.format(a.name))

        alist = self.get_logical_device_list()
        assert (alist == None or len(alist) == 0), \
            "Cannot delete all logical-device"

    def delete_all_app_instances(self):
        """Delete all application instances.

        :return: None
        """

        app_instance_list = self.get_app_instance_list()
        if app_instance_list == None or len(app_instance_list) == 0:
            logger.info('no app-instance found, nothing to do.')

        for a in app_instance_list:
            cmd_lines = """
                  top
                  scope ssa
                  scope slot {}
                  delete app-instance {} {}
                  commit-buffer
            """.format(a.slot_id, a.application_name, a.identifier)
            self.go_to('mio_state')
            self.execute_lines(cmd_lines, timeout=30,
                               exception_on_bad_command=True)

            logger.info('Slot {}: app-instance {} {} deleted'.format(a.slot_id,
                                                                     a.application_name,
                                                                     a.identifier))

        app_instance_list = self.get_app_instance_list()
        assert (app_instance_list == None or
                len(app_instance_list) == 0), "Cannot delete all app-instance"

    def get_bundle_package_version(self, bundle_package_name):
        """Get bundle package version from the bundle package name.

        :param bundle_package_name: bundle package name, e.g. fxos-k9.2.1.1.64.SPA
        :return: bundle package version: e.g. 2.1(1.64)

        """

        cmd_lines = """
            top
            scope firmware
            show package | grep {}
        """.format(bundle_package_name)
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)

        r = re.search("{}\s+([\w.()]+)".format(bundle_package_name), output)
        # Check whether the package exists in show package
        # If not extract the version from bundle_package_name
        if not r:
            l = bundle_package_name.split('.')
            version = '{}.{}({}.{})'.format(l[1], l[2], l[3], l[4])
            return version

        return r.group(1)

    def create_app_instance(self, app_data, wait_upto=30):
        """
        Method creates an app instance. The method does not wait until the app
        is installed, it waits just until the app appears to be created in
        the show app instance list.
        :param app_data: the dictionary describing the app instance taken
        from the testbed
        :param wait_upto: the wait time for the app to appear in the list
        :return: None
        """
        self.go_to('mio_state')

        app_name = app_data['application_name']
        deploy_type = app_data['deploy_type'] if app_data.get(
            'deploy_type', None) else 'native'
        app_identifier = app_data['application_identifier']
        slot = app_data['slot']
        startup_version = app_data.get('startup_version', None)

        set_resource_profile = ''
        if app_data.get('resource_profile', None):
            set_resource_profile += """
                set resource-profile {}
            """.format(app_data['resource_profile'])

        app_instance_config = """
            top
            scope ssa
            scope slot {}
            create app-instance {} {}
            {}
            set deploy-type {}
        """.format(str(slot), app_name, app_identifier, set_resource_profile,
                   deploy_type)
        if startup_version:
            app_instance_config += """
                set startup-version {}
            """.format(app_data['startup_version'].replace('-', '.').strip())

        app_instance_config += """
            commit-buffer
        """
        self.execute_lines(app_instance_config, exception_on_bad_command=True)

        self.wait_till(self.is_app_created,
                       (app_name, app_identifier, slot), wait_upto=wait_upto)

    def is_app_created(self, app_name, app_identifier, slot):
        """
        Method is used to check if an app is created. The method only checks
        the app has been created as an object on the device. It does not check
        if the app is installed or has become online.
        :param app_name: the application name (e.g. ftd)
        :param app_identifier: the application identifier (e.g. sensor1)
        :param slot: the slot on which the app was created
        :return: True if the app was created, False otherwise
        """
        app_instance_list = self.get_app_instance_list()
        if app_instance_list is not None and len(app_instance_list) > 0:
            app_instance = \
                [a for a in app_instance_list if int(a.slot_id) == int(slot)
                 and (a.identifier == app_identifier and
                      a.application_name == app_name)]
            if len(app_instance) == 1:
                return True
        return False

    def create_logical_device(self, slot, lg_data, chassis_network,
                              application_name='ftd', wait_upto=30):
        """
        Creates a logical device bootstrap object on the device.
        Method does now check if the logical device has launched an app.
        :param slot: the slot on which the logical device will be created
        :param lg_data: the dictionary describing the logical device (from the
        testbed)
        :param chassis_network: the dictionary describing the chassis network (
        from the testbed)
        :param application_name: the application name (e.g. ftd)
        :param wait_upto: the time to wait for the logical device object to
        be created
        :return: None
        """
        self.go_to('mio_state')

        lg_config = """
             top
             scope ssa
             create logical-device {} {} {} standalone
        """.format(lg_data['name'], application_name, slot)

        for port in lg_data['external_port_links']:
            interface = self._get_interface_object_from_chassis_data(
                port, chassis_network)
            if interface is None:
                raise RuntimeError('Cannot identify port %s' % port)
            lg_config += """
                enter external-port-link {} {} ftd
                set description "Created by automation"
                exit
            """.format(
                interface.subtype.replace('-', '_') + '_' + port.replace(
                    '/', '-').replace('.', '_'),
                port)

        lg_config += """

            enter mgmt-bootstrap ftd
        """

        for bs_key in lg_data.get('bootstrap_keys', []):
            lg_config += """
                create bootstrap-key {}
                set value {}
                exit
            """.format(
                bs_key.upper(),
                lg_data['bootstrap_keys'][bs_key])

        lg_config += """

                enter ipv4 {} firepower
                set ip {} mask {}
                set gateway {}
                exit
            """.format(
            str(slot),
            lg_data['ipv4']['ip'],
            lg_data['ipv4']['netmask'],
            lg_data['ipv4']['gateway'])
        self.execute_lines(lg_config, exception_on_bad_command=True)

        if lg_data.get('bootstrap_keys_secret', None):
            for bs_secret_key, value in lg_data['bootstrap_keys_secret'].items():
                self.execute_lines("enter bootstrap-key-secret {}".format(bs_secret_key.upper()))
                self.set_value(value)
                self.execute_lines("exit")

        self.execute_lines("""commit-buffer""", exception_on_bad_command=True)

        self.wait_till(self.is_logical_device_created, (lg_data['name'],),
                       wait_upto=wait_upto)

        self.check_all_logical_devices_configuration()

    def is_logical_device_created(self, lg_name):
        """
        Method wait for the logical device object to be created on the device.
        The method checks if the name of the logical device appears in the
        show logical device list.
        :param lg_name: the logical device name
        :return:
        """
        ld_list = self.get_logical_device_list()
        if ld_list is not None and len(ld_list) > 0:
            ld = [l for l in ld_list if l.name == lg_name]
            if len(ld) == 1:
                return True
        return False

    def wait_for_app_creation(self, slot, app_name, app_identifier,
                              in_cluster_mode, wait_upto=300):
        """
        Waits for application to be created on the slot
        :param slot: the slot id
        :param app_name:  the application name (ex. ftd)
        :param app_identifier: the application identifier (ex. sensor1)
        :param in_cluster_mode: parameter specifying wether the device is in
        clustered mode or not
        :param wait_upto: the wait time for the application to be created
        :return:
        """
        self.wait_till_slot_online(slot)
        self.wait_till_app_instance_ready(slot, app_name,
                                          app_identifier,
                                          in_cluster_mode,
                                          wait_upto)

    def bounce_app_instance(self, slot_num, app_instance_name,
                            app_identifier=None):
        """
        When user create an app instance, sometimes they need to bounce it,
        meaning to disable it, then enable it. It cannot be done right away,
        and needs to handle a wait.

        For example, the following will be seen:

        FPR4120-6-Rack10-A /ssa/slot/app-instance* # disable
        FPR4120-6-Rack10-A /ssa/slot/app-instance* # commit-buffer
        FPR4120-6-Rack10-A /ssa/slot/app-instance # enable
        FPR4120-6-Rack10-A /ssa/slot/app-instance* # commit-buffer
        Error: Update failed: [Logical Device is being provisioned. Please
             wait for the application instance to be started.]
        <after a few minutes>
        FPR4120-6-Rack10-A /ssa/slot/app-instance* # commit-buffer
        FPR4120-6-Rack10-A /ssa/slot/app-instance #

        :param slot_num: the slot id
        :param app_instance_name: the app name
        :param app_identifier: for container mode the app identifier
        :return: None
        """
        disable_cmds = """
            top
            scope ssa
            scope slot {}
            enter app-instance {} {}
            disable
            commit-buffer
        """.format(slot_num, app_instance_name, app_identifier)
        self.execute_lines(disable_cmds, timeout=60,
                           exception_on_bad_command=True)

        enable_cmds = """
            top
            scope ssa
            scope slot {}
            enter app-instance {} {}
            enable
            commit-buffer
        """.format(slot_num, app_instance_name, app_identifier)

        # try every 10 seconds, up to 10 min
        for _ in range(60):
            r = self.execute_lines(enable_cmds, exception_on_bad_command=True)
            if 'Please wait for the application instance to be started.' in r:
                logger.debug('app is busy, can not enable')
                time.sleep(10)
                continue
            else:
                logger.debug('app is enabled')
                break
        else:
            raise RuntimeError('Can not enable app after 10 min')

    def delete_app_instance(self, slot, app_name, app_identifier):
        """Deletes application instance

        :param cmd_lines: multi-line commands to delete the app instance.
          It should look like this:
                  scope slot 1
                  delete app-instance ftd sensor1
                  commit-buffer
        :param slot: the slot id
        :param app_name: the application name (ftd)
        :param app_identifier: the application identifier (sensor1)
        :return: None

        """
        # run cmd_lines to delete it.
        self.go_to('mio_state')
        self.execute_lines("""
            scope slot {}
            delete app-instance {} {}
            commit-buffer""".format(slot, app_name, app_identifier),
                           exception_on_bad_command=True)

        # check that it is deleted
        app_instance_list = self.get_app_instance_list()
        app_instance = [a for a in app_instance_list if
                        int(a.slot_id) == int(slot) and
                        a.application_name == app_name and
                        a.identifier == app_identifier]
        assert len(app_instance) == 0, \
            "app_instance {} {} not deleted in slot {}".format(
                app_name, app_identifier, slot)

    def delete_logical_devices_and_app_instances(self, slot_id):
        """Deletes logical device and app instance by slot_id

        :param slot_id: slot_id for SSP; QP: 1; BS: 1, 2, or 3
        :return: None

        """

        logical_devices = self.get_logical_device_list()
        if logical_devices is None or len(logical_devices) == 0:
            logger.info('No logical device found, nothing to delete.')

        for a in logical_devices:
            if a.mode == "Clustered":
                self.delete_all_logical_devices()
                self.delete_all_app_instances()
                self.assign_all_interfaces_to_data_type()
                return
            if int(a.slot_id) == int(slot_id):
                cmd_lines = """
                      top
                      scope ssa
                      delete logical-device {}
                      commit-buffer
                """.format(a.name)
                logger.info(
                    'logical device {} is to be deleted ...'.format(a.name))

                self.go_to('mio_state')
                self.execute_lines(cmd_lines, timeout=30,
                                   exception_on_bad_command=True)

                logger.info('logical-device {} deleted'.format(a.name))

        self.get_logical_device_list()

        app_instance_list = self.get_app_instance_list()
        if app_instance_list is None or len(app_instance_list) == 0:
            logger.info('No app-instance found, nothing to delete')

        for a in app_instance_list:
            cmd_lines = """
                  top
                  scope ssa
                  scope slot {}
                  delete app-instance {} {}
                  commit-buffer
            """.format(a.slot_id, a.application_name, a.identifier)
            if int(a.slot_id) == int(slot_id):
                self.go_to('mio_state')
                self.execute_lines(cmd_lines, timeout=30,
                                   exception_on_bad_command=True)
                logger.info(
                    'Slot {}: app-instance {} {} deleted'.format(a.slot_id,
                                                                 a.application_name,
                                                                 a.identifier))

        app_instance_list = self.get_app_instance_list()
        app_instance_list = [a for a in app_instance_list
                             if a.slot_id == slot_id]
        assert app_instance_list is not None and len(app_instance_list) == 0, \
            'Could not delete all the app instances from slot {}.'.format(
                slot_id)

    def delete_app_instance_by_slot(self, logical_device_name, slot_id,
                                    application_name, application_identifier):
        """
        :param logical_device_name: logical device name, e.g. sensor1
        :param slot_id: slot id, e.g. 1, 2, or 3
        :param app_instance: app instance name, e.g. ftd or asa
        :param app_identifier: the application identifier, e.g. sensor1
        :return: None
        """
        self.go_to('mio_state')
        cmd_lines = """
            top
            scope ssa
            delete logical-device {}
            commit-buffer
        """.format(logical_device_name)
        self.execute_lines(cmd_lines, exception_on_bad_command=True)

        cmd_lines = """
            scope slot {}
            delete app-instance {} {}
            commit-buffer
        """.format(slot_id, application_name, application_identifier)
        self.execute_lines(cmd_lines, exception_on_bad_command=True)

        # check that it is deleted
        app_instance_list = self.get_app_instance_list()
        app_instance = [a for a in app_instance_list if
                        a.application_name == application_name and
                        a.identifier == application_identifier and
                        int(a.slot_id) == int(slot_id)]
        assert len(app_instance) == 0, "app_instance {} not deleted in slot " \
                                       "{}".format(app_instance, slot_id)

    def assign_all_interfaces_to_data_type(self):
        """Assign port-type to data for all interfaces

        :return: None

        """
        cmd_lines = """
            top
            scope eth-uplink
            scope fabric a
            show interface detail
        """
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Port Name':
                hardware = a_value
                cmd_lines2 = """
                    scope interface {}
                    set port-type data
                    ex
                """.format(hardware)
                self.execute_lines(cmd_lines2, exception_on_bad_command=True,
                                   timeout=30)
        self.execute('commit-buffer', timeout=10,
                     exception_on_bad_command=True)
        self.execute_lines(cmd_lines, timeout=60)

    def assign_all_aggr_interfaces_to_data_type(self):
        """
        Deletes all subinterfaces defined on the interfaces inside the aggregate interfaces present on the device.
        After this it resets all aggr interfaces to the data type.
        :return:
        """
        aggr_ifaces = self.get_aggr_interfaces_list()
        # delete subinterfaces
        for aggr_iface in aggr_ifaces:
            for iface in aggr_iface.InterfacesList:
                for subiface in iface.SubInterfacesList:
                    logger.info('Deleting aggregate interface subinterface {}.{}'.format(
                        iface.PortName, subiface.SubInterfaceId))
                    cmd_lines = """
                        top
                        scope eth-uplink
                        scope fabric a
                        enter aggr-interface {}
                    """.format(aggr_iface.PortName)
                    self.go_to('mio_state')
                    self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)
                    cmd_lines = """enter interface {}""".format(iface.PortName)
                    self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)
                    cmd_lines = """delete subinterface {}""".format(subiface.SubInterfaceId)
                    self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)
                    self.execute_lines("""commit-buffer""", timeout=60, exception_on_bad_command=True)
                    self.execute_lines("""exit""", timeout=60, exception_on_bad_command=True)

        # reset interfaces
        for aggr_iface in aggr_ifaces:
            cmd_lines = """
                top
                scope eth-uplink
                scope fabric a
                enter aggr-interface {}
            """.format(aggr_iface.PortName)
            self.go_to('mio_state')
            self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)
            for iface in aggr_iface.InterfacesList:
                logger.info('Reseting aggregate interface {} to data type'.format(aggr_iface.PortName))
                cmd_lines = """enter interface {}""".format(iface.PortName)
                self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)
                self.execute_lines("""set port-type data""", timeout=60, exception_on_bad_command=True)
                self.execute_lines("""commit-buffer""", timeout=60, exception_on_bad_command=True)
                self.execute_lines("""exit""", timeout=60, exception_on_bad_command=True)
        return aggr_ifaces

    def get_aggr_interfaces_list(self):
        """
        Get list of aggregate interfaces
        :return: List of aggregate interfaces instances
        """
        logger.info('Reading existing aggregate interfaces from device ...')
        cmd_lines = """
            top
            scope eth-uplink
            scope fabric a
            show aggr-interface detail
        """
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)

        AggrInterface = collections.namedtuple('AggrInterface', ['PortName', 'ConfigState', 'InterfacesList'])
        Interface = collections.namedtuple('Interface', ['PortName', 'PortType', 'SubInterfacesList'])
        SubInterface = collections.namedtuple('SubInterface', ['SubInterfaceId', 'SubInterfaceName', 'PortType'])
        aggr_ifaces = []

        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name.startswith('Port Name'):
                port_name = a_value
                continue
            if a_name.startswith('Config State'):
                config_state = a_value
                aggr_ifaces.append(AggrInterface(port_name, config_state, list()))
                continue

        for aggr_iface in aggr_ifaces:
            cmd_lines = """
                top
                scope eth-uplink
                scope fabric a
                enter aggr-interface {}
                show interface detail
            """.format(aggr_iface.PortName)
            self.go_to('mio_state')
            output = self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)

            for line in output.split('\n'):
                line = line.strip()
                if line == '':
                    continue
                logger.debug('line=' + line)
                if line.find(':') == -1:
                    continue
                name_value = line.split(':')
                a_name = name_value[0].strip()
                a_value = name_value[1].strip()
                if a_name.startswith('Port Name'):
                    port_name = a_value
                    continue
                if a_name.startswith('Port Type'):
                    port_type = a_value
                    aggr_iface.InterfacesList.append(Interface(port_name, port_type, list()))
                    continue

        for aggr_iface in aggr_ifaces:
            cmd_lines = """
                top
                scope eth-uplink
                scope fabric a
                enter aggr-interface {}
            """.format(aggr_iface.PortName)
            self.go_to('mio_state')
            self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)
            for iface in aggr_iface.InterfacesList:
                cmd_lines = """
                    enter interface {}
                    show subinterface detail
                    exit
                """.format(iface.PortName)
                self.go_to('mio_state')
                output = self.execute_lines(cmd_lines, timeout=60, exception_on_bad_command=True)

                for line in output.split('\n'):
                    line = line.strip()
                    if line == '':
                        continue
                    logger.debug('line=' + line)
                    if line.find(':') == -1:
                        continue
                    name_value = line.split(':')
                    a_name = name_value[0].strip()
                    a_value = name_value[1].strip()
                    if a_name.startswith('Sub-If Id'):
                        subiface_id = a_value
                        continue
                    if a_name.startswith('Sub-Interface Name'):
                        port_name = a_value
                        continue
                    if a_name.startswith('Port Type'):
                        port_type = a_value
                        iface.SubInterfacesList.append(SubInterface(subiface_id, port_name, port_type))
                        continue
        logger.info('Discovered aggregate interfaces on device: {}'.format(aggr_ifaces))
        return aggr_ifaces

    def is_firmware_monitor_ready(self, version):
        """Check whether the bundle package is installed successfully.

        :param version: version string of the bundle package
                        e.g. 2.1(1.64)
        :return: True if fprm, fabric, chassis are in Ready status

        """

        firmware_monitor = self.parse_firmware_monitor()

        fprm = firmware_monitor.fprm
        if fprm.version != version or fprm.status != 'Ready':
            return False

        fabric = firmware_monitor.fabric
        if fabric.version != version or fabric.status != 'Ready':
            return False

        chassis = firmware_monitor.chassis
        # Handle chassis.version contains multiple versions properly
        # The first version should match argument version
        version_list = chassis.version.split(',')
        if version not in version_list or chassis.status != 'Ready':
            return False

        return True

    def wait_till_firmware_monitor_ready(self, version, timeout=1500):
        """Waits until the bundle package is installed successfully.

        :param version: version string of the bundle package
                        e.g. 2.1(1.64)
        :param timeout: timeout for wait_till()
        :return: None

        """

        # set terminal width bigger
        self.init_terminal()
        self.wait_till(self.is_firmware_monitor_ready, (version,),
                       wait_upto=timeout)

    def upgrade_bundle_package(self, bundle_package_name):
        """Upgrade bundle package.

        :param bundle_package_name: e.g. fxos-k9.2.1.1.64.SPA
        :return: None

        """
        version = self.get_bundle_package_version(bundle_package_name)
        if self.is_firmware_monitor_ready(version):
            # the bundle package has already been installed
            logger.info("fxos bundle package {} has been installed, " \
                        "nothing to do".format(bundle_package_name))
            return False
        cmd_lines = """
            top
            scope firmware
            scope auto-install
        """
        self.execute_lines(cmd_lines, timeout=10)
        try:
            self.spawn_id.sendline(
                "install platform platform-vers {}".format(version))

            # Handle the first question
            d1 = Dialog([
                ['Do you want to proceed', 'sendline(yes)', None, False, False],
            ])
            d1.process(self.spawn_id, timeout=30)
        except:
            logger.error(
                "Invalid FXOS platform software package {}".format(version))
            return False

        # Check whether system will reboot
        will_system_reboot = False
        d2 = Dialog([
            [
                'INFO: There is no service impact to install this FXOS platform software',
                None, None, False, False],
        ])
        d1 = Dialog([
            [r'.*Do you want to.*', 'sendline(yes)', None, False, False],
        ])
        try:
            # Some fxos versions have an additional dialog
            d1.process(self.spawn_id, timeout=30)
        except:
            pass

        try:
            d2.process(self.spawn_id, timeout=10)
            logger.info('\nSystem will not reboot.')
            # Handle the second question
            d1 = Dialog([
                ['Do you want to proceed', 'sendline(yes)', None, False, False],
            ])
            d1.process(self.spawn_id, timeout=10)
        except:
            # d2.process(self.spawn_id, timeoutwill_system_reboot = True=10)
            logger.info('\nSystem will reboot ...')
            will_system_reboot = True

        # If system will reboot, will wait for the following prompts
        if will_system_reboot:
            # Handle older fxos image with rebooting info printed to the console
            logger.info('==== Waiting for messages in rebooting ...')

            d1 = Dialog([
                ['{} login: '.format(self.sm.patterns.chassis_hostname),
                 'sendline({})'.format(self.sm.patterns.chassis_username),
                 None, True, False],
                ['Password:',
                 'sendline({})'.format(self.sm.patterns.chassis_password), None,
                 True, False],
                ['.*Successful login attempts for user.*', None, None, True,
                 False],
                ['Sending all processes the KILL signal', None, None, True,
                 False],
                ['Please stand by while rebooting the system', None, None, True,
                 False],
                ['Use SPACE to begin boot immediately', 'send(" ")', None, True,
                 False],
                ['Manager image digital signature verification successful',
                 None, None, True, False],
                ['System is coming up', None, None, True, False],
                ['Finished bcm_attach...', None, None, True, False],
                ['vdc 1 has come online', None, None, False, False],
                [r'Connection to .* closed.', None, None, False, False],
            ])
            d1.process(self.spawn_id, timeout=1800)

            logger.info('==== Reconnect after reboot...')
            # Wait for reboot to finish and reconnect
            time.sleep(480)
            self.monitor_installation(version=version, timeout=2400)

            # set disconnect timeout to maximum
            self.set_default_auth_timeouts()
            return True
        return True

    def monitor_installation(self, version, timeout=1500):
        """ Check if installation is finished and if the version is correct

        :param version: version string of the bundle package
                        e.g. 2.1(1.64)
        :param timeout: Timeout in case the installation takes too long
        :return: None

        """

        # Go to mio_state
        self.spawn_id.sendline()
        self.go_to('any')
        self.go_to('mio_state')

        # Wait for upgrade of fxos to finish
        logger.info('==== Check installation progress..')
        self.wait_till_firmware_monitor_ready(version, timeout=timeout)

    def switch_to_module(self, slot_id, app_identifier=None):
        """Method used to switch between the modules

        :param slot_id: the slot Id to connect to
        :param deploy_type: the deploy type of the app (container or native)
        :param app_identifier: the app identifier (in case of container deploy)
        :return:
        """
        self.set_current_slot(slot_id)
        self.set_current_application(app_identifier)

        self.go_to('fireos_state', timeout=240)

    def set_value(self, value):
        """
        Needed to add cluster password as below:

        FPR4120-6-Rack10-A /ssa/logical-device* # enter mgmt-bootstrap ftd
        FPR4120-6-Rack10-A /ssa/logical-device/mgmt-bootstrap* # enter bootstrap-key-secret PASSWORD
        FPR4120-6-Rack10-A /ssa/logical-device/mgmt-bootstrap/bootstrap-key-secret* # set value
        Value:
        FPR4120-6-Rack10-A /ssa/logical-device/mgmt-bootstrap/bootstrap-key-secret* # exit

        :param value: the value
        :return: None
        """
        logger.info('=== Set value')
        self.spawn_id.sendline('set value')
        d = Dialog([
            ['(V|v)alue:', 'sendline({})'.format(value), None, True, False],
            [self.sm.get_state('mio_state').pattern, None, None, False,
             False]
        ])
        d.process(self.spawn_id)

    def set_key(self, key):
        """
        Needed to add cluster password as below:

        FPR4120-6-Rack10-A# scope ssa
        FPR4120-6-Rack10-A /ssa # enter logical-device ftd-logic ftd 1 clustered
        FPR4120-6-Rack10-A /ssa/logical-device # enter cluster-bootstrap
        PR4120-6-Rack10-A /ssa/logical-device/cluster-bootstrap # set key
        Key:
        FPR4120-6-Rack10-A /ssa/logical-device/cluster-bootstrap* # commit-buffer

        :param key: the key

        :return: None
        """
        logger.info('=== Set security key')
        self.spawn_id.sendline('set key')
        d1 = Dialog([
            ['[K|k]ey:', 'sendline({})'.format(key), None, True, False],
            [self.sm.get_state('mio_state').pattern, None, None, False,
             False],
        ])
        d1.process(self.spawn_id, timeout=30)

    def set_power_bar(self, chassis_power_data):
        """
        Sets the chassis power bar information
        :param chassis_power_data: a dictionary of the form
        {
            'power_bar_server': '<the ip of the power bar server>',
            'power_bar_port': '<the power port to which the chassis is
            connected>',
            'power_bar_user': '<the username credential for the power
            bar server>'
            'power_bar_password': '<the password credential for the power bar
            server>'
        }
        :return:
        """
        self.power_bar_server = chassis_power_data.get('power_bar_server', '')
        self.power_bar_port = chassis_power_data.get('power_bar_port', '')
        self.power_bar_user = chassis_power_data.get('power_bar_user', '')
        self.power_bar_pwd = chassis_power_data.get('power_bar_password', '')

    def power_cycle(self, wait_until_device_is_on=True, timeout=60):
        """
        Cycle power to off an then to on for the chassis using the already
        set power bar server information
        :param wait_until_device_is_on: wait for device to boot up
        :param timeout: the max. time to wait for device boot up
        :return:
        """

        result = power_cycle_all_ports(self.power_bar_server, self.power_bar_port, self.power_bar_user,
                                       self.power_bar_pwd)

        logger.info('Wait for device to be up running ...')
        if wait_until_device_is_on:
            self.wait_until_device_on(timeout=timeout)

        return result

    def set_current_slot(self, slot):
        """
        Sets the id of the current active slot used by the state machine
        :param slot: the slot id
        :return: None
        """
        self.sm.current_slot = str(slot)

    def get_current_slot(self):
        """
        Gets the id of the current active slot used by the state machine
        :return: the slot id
        """
        return self.sm.current_slot

    def set_current_application(self, application_identifier):
        """
        Sets the id of the current active application used by the state machine
        :param slot: the application identifier
        :return: None
        """
        self.sm.current_application = application_identifier

    def get_current_application(self):
        """
        Gets the id of the current active application used by the state machine
        :return: None
        """
        return self.sm.current_application

    def go_to(self, state, timeout=30):
        to_state = state
        try:
            super().go_to(to_state, hop_wise=True, timeout=timeout)
        except StateMachineError as e:
            # trying to handle session disconnect situations
            # see more details in the member function documentation
            self.__handle_session_disconnect_for_ftd_states(
                destination_state=to_state, state_machine_exception=e,
                timeout=timeout)

    def __handle_session_disconnect_for_ftd_states(self,
                                                   destination_state,
                                                   state_machine_exception,
                                                   timeout=10):
        """
            The following implementation tries to bring back the user to the
            state he was in on the ftd hosted over the chassis if the chassis
            fxos disconnects the current session.

            Example: The user goes in a specific ftd state (let's say expert)
            and does work there in his test script. Maybe after this he does
            some other work and as time passes at some point (depending on the
            chassis fxos default-auth settings) the chassis detects that the
            session timeout has expired and disconnects the user from the
            current session and takes him to the login screen. The user then
            wants to do some work on the ftd again and expects that he is
            in the last state that he was in before. And surprise, he was
            disconnected in the mean time. We thus try to relogin and take
            him back to the prevoius state he was in. This is valid only for
            ftd application states and only valid for ftds running on top of
            chassis hardware.

            :param destination_state: the state the user wants to go to
            :param state_machine_exception: the exception that helps us
            determine what happened (if a session disconnect happened)
            :param timeout: the timeout from the parent function used for
            state transitions

            If we are in any other state machine error that is caused by
            another reason different from a session disconnect the function
            does not handle it and throws the original error to the user.

            The function determines the states that are taken into account
            for this session disconnect behavior by interrogating the state
            machine ftd_states member defined in the ssp state machine.
        """
        if re.match('Failed.*bring.*to.*state.*', str(state_machine_exception)):
            if self.sm.ftd_states and self.sm.current_state not in \
                    self.sm.ftd_states:
                raise state_machine_exception
            i = 0
            # see if logout occurred and bring login prompt to focus
            while i < 3:
                try:
                    self.spawn_id.sendline()
                    if self.spawn_id.expect('[l|L]ogin: $', timeout=5):
                        break
                except:
                    pass
                i += 1
            if i >= 3:
                # something other than a logout occured
                raise state_machine_exception
            self.sm.update_cur_state('prelogin_state')
            try:
                super().go_to('mio_state', hop_wise=True,
                              timeout=timeout)
            except:
                pass
            super().go_to('any', hop_wise=True, timeout=timeout)
            super().go_to(destination_state, hop_wise=True, timeout=timeout)
        else:
            raise state_machine_exception

    def disconnect(self):
        """Disconnect the Device."""
        if self.spawn_id is not None:
            if self.type == 'ssh':
                self.go_to('mio_state')
        super().disconnect()

    def is_app_instance_ready(self, slot_id, application_name,
                              app_identifier, in_cluster_mode):
        """
        Checks whether the app instance is ready
        :param slot_id: the slot id
        :param application_name: the application name (ftd)
        :param app_identifier: the application identifier (sensor1)
        :param in_cluster_mode: device is in cluster mode or not
        :return: True or False
        """
        logger.info(
            "=========== Wait for app_instance: {} {} at slot: {} to be "
            "Enabled and Online ===========".format(
                application_name, app_identifier, slot_id))
        app_instance_list = self.get_app_instance_list()
        if app_instance_list == None or len(app_instance_list) == 0:
            logger.info('return False in is_app_instance_ready when '
                        'app_instance_list is empty')
            return False
        app_instance = [a for a in app_instance_list if
                        a.application_name == application_name and
                        a.identifier == app_identifier and
                        int(a.slot_id) == int(slot_id)]
        assert len(app_instance) == 1, "Found {} app instances for app {} {} " \
                                       "in slot {}".format(len(app_instance),
                                                           application_name,
                                                           app_identifier,
                                                           slot_id)
        app_instance = app_instance[0]

        if app_instance.operational_state == "Install Failed":
            raise RuntimeError('Install Failed.')

        if in_cluster_mode:
            # if the slot is not populated with hardware skip for cluster mode
            if app_instance.operational_state == "Not Available":
                return True
            else:
                if (app_instance.admin_state == 'Enabled' and
                            app_instance.operational_state == 'Online' and
                        (app_instance.cluster_oper_state == "In Cluster" or
                                 'Master' in app_instance.cluster_oper_state or
                                 'Slave' in app_instance.cluster_oper_state)):
                    return True
        else:
            if app_instance.admin_state == 'Enabled' and \
                            app_instance.operational_state == 'Online':
                return True
        logger.info('return False in is_app_instance_ready when admin_state '
                    'is not Enabled or operational_state is not Online')
        return False

    def wait_till_app_instance_ready(self, slot_id, application_name,
                                     app_identifier, in_cluster_mode,
                                     wait_for_app_to_start):
        """
        Waits until the application instance is ready
        :param slot_id: the slot id
        :param application_name: the application name (ftd)
        :param app_identifier: the application identifier (sensor1)
        :param in_cluster_mode: device is in clustered mode or not
        :param wait_for_app_to_start: the max. time to wait for the app
        to start
        :return:
        """
        self.wait_till(
            self.is_app_instance_ready,
            (slot_id, application_name, app_identifier, in_cluster_mode),
            wait_upto=wait_for_app_to_start)

    def download_fxos(self, fxos_url, file_server_password="", http_url=""):
        """Download image of FXOS.

        :param fxos_url: fxos url to download the image, you can also use your
        own container instead (see example)
            e.g. scp://pxe@172.23.47.63:/tftpboot/fxos-k9.2.1.1.64.SPA
            e.g. scp://root@container_ip:container_port:/tmp/fxos-k9.2.1.1.64.SPA
        :param file_server_password: sftp server password
        :param http_url: Url with the destination of the fxos file. In case
            such is provided, it will first download it to the container,
            then continue normally with the scp download

        """

        bundle_package_name = fxos_url.split("/")[-1].strip()
        version = self.get_bundle_package_version(bundle_package_name)
        if self.is_firmware_monitor_ready(version):
            # the bundle package has already been installed
            logger.info("fxos bundle package {} has been installed, " \
                        "nothing to do".format(bundle_package_name))
            return

        if self.is_bundle_on_chassis(fxos_url):
            return

        retry_count = MAX_RETRY_COUNT
        while retry_count > 0:

            if "http://" in http_url:
                try:
                    subprocess.call("wget {} -P {}".format(http_url, "/tmp/"),
                                    shell=True)
                    logger.info(
                        "Download on container complete. Starting "
                        "SCP to chassis.")
                except:
                    raise logger.error(
                        "Issue downloading the fxos file to the container.")

            d1 = Dialog([
                ['{} login: '.format(self.sm.patterns.chassis_hostname),
                 'sendline({})'.format(self.sm.patterns.chassis_username),
                 None, True, False],
                ['Password:',
                 'sendline({})'.format(self.sm.patterns.chassis_password), None,
                 True, False],
                ['.*Successful login attempts for user.*', None, None, False,
                 False],
            ])

            server_timeout = True
            try:
                d1.process(self.spawn_id)
            except:
                server_timeout = False

            if server_timeout:
                logger.info(
                    "Download took to long and you were disconnected "
                    "from the device. Reconnecting.")
                self.spawn_id.sendline("scope firmware")

            self.spawn_id.sendline('download image {}'.format(fxos_url))
            time.sleep(5)

            d1 = Dialog([
                ['continue connecting (yes/no)?', 'sendline(yes)', None, True,
                 False],
                ['Password:', 'sendline({})'.format(file_server_password),
                 None, True, False],
                [self.sm.get_state('mio_state').pattern, None, None, False,
                 False],
            ])
            d1.process(self.spawn_id)

            status = self._wait_till_download_complete(fxos_url)

            if status == "Failed":
                retry_count -= 1
                if retry_count == 0:
                    raise RuntimeError(
                        "Download failed after {} tries. Please check "
                        "details again: {}".format(
                            MAX_RETRY_COUNT,
                            fxos_url))
                logger.info(
                    "Download failed. Trying to download {} more times".format(
                        retry_count))
            elif status == "Downloaded":
                logger.info("Download on chassis complete!")
                return

    def is_slot_reinitialized(self, slot_id):
        """
        Checks if slot has finished reinitializing

        :param slot_id: the slot id
        :return: True or False
        """
        show_slot_detail_cmd = """
            top
            scope ssa
            show slot {} detail
        """.format(slot_id)
        slot_status = self.execute_lines(show_slot_detail_cmd, timeout=30)

        check_slot_online = "Oper State: Online"
        check_failed_operational = "Oper State: Not Available"
        if 'Operational State' in slot_status:
            check_slot_online = "Operational State: Online"
            check_failed_operational = "Operational State: Not Available"

        check_format_done = "Disk State: Ok"
        if 'Disk Format Status' in slot_status:
            check_format_done = "Disk Format Status: 100%"

        return (check_slot_online in slot_status and
                check_format_done in slot_status) or \
                check_failed_operational in slot_status

    def reinitialize_slots(self, slot_ids, timeout=900):
        """
        Starts the reinitializing of the slot

        :param slot_id: the list of slot id to be reinitialized
        :param timeout: the time to wait for the reinitialization to finish
        :return: None
        """
        for slot_id in slot_ids:
            reinitialize_slot_cmd = """
                top
                scope ssa
                scope slot {}
                reinitialize
                commit-buffer
            """.format(slot_id)
            self.execute_lines(reinitialize_slot_cmd,
                               exception_on_bad_command=True)
        time.sleep(10)
        for slot_id in slot_ids:
            self.wait_till(self.is_slot_reinitialized, (slot_id,),
                           wait_upto=timeout)

    def set_default_auth_timeouts(self):
        """
            Set default value to disable logout from the chassis. Timeouts
            are set to zero for disable. The session must be exited and
            re-logged in for the changes to be applied.
        """
        commands = """
            top
            scope security
            scope default-auth
            set absolute-session-timeout 0
            set con-absolute-session-timeout 0
            set con-session-timeout 0
            commit-buffer
            show detail
            top
            exit
        """
        try:
            self.execute_lines(commands, timeout=30)
        except TimeoutError as e:
            pass
        self.sm.update_cur_state('prelogin_state')
        self.go_to('mio_state')

    def configure_chassis_network(self, chassis_network_data):
        """
        Configure the chassis network
        :param chassis_network_data: a dict describing the chassis network
        information (see testbed format for details)
        """
        if chassis_network_data['interfaces'].get('chassis_mgmt', None):
            chassis_network_config = """
                top
                scope fabric a
                show detail
                set out-of-band ip {} netmask {} gw {}
                commit-buffer
            """.format(
                chassis_network_data['interfaces']['chassis_mgmt'].ipv4_ip,
                chassis_network_data['interfaces']['chassis_mgmt'].ipv4_netmask,
                chassis_network_data['interfaces']['chassis_mgmt'].ipv4_gateway
            )
            logger.info("""command lines for chassis network ip config
                        {}
                """.format(chassis_network_config))
            self.execute_lines(chassis_network_config,
                               exception_on_bad_command=True)
        if chassis_network_data.get('dns_servers', None):
            chassis_network_config = """
                top
                scope system
                scope services
            """
            for dns in chassis_network_data['dns_servers'].split(','):
                chassis_network_config += """
                    create dns {}
                """.format(dns)
            chassis_network_config += """
                commit-buffer
            """
            logger.info("""command lines for chassis network dns servers config
                    {}
                """.format(chassis_network_config))
            self.execute_lines(chassis_network_config)
        if chassis_network_data.get('search_domain', None):
            chassis_network_config = """
                top
                scope system
                scope services
                set domain-name {}
                commit-buffer
            """.format(
                chassis_network_data['search_domain']
            )
            logger.info("""command lines for chassis network search domain config
                {}
            """.format(chassis_network_config))
            self.execute_lines(chassis_network_config)

    def configure_aggr_interface(self, aggr_interface):
        """
        Configure an aggregate interface on the chassis
        :param aggr_interface: a dict describing the interface information (see testbed format for details)
        """
        logger.info('Configuring aggregate interface {}'.format(aggr_interface.hardware))
        aggr_interface_config = """
            top
            scope eth-uplink
            scope fabric a
            scope aggr-interface {}
            scope interface {}
            set port-type {}
            enable
            exit
            commit-buffer
        """.format(re.search('Ethernet\d+/\d+', aggr_interface.hardware).group(0),
                   aggr_interface.hardware,
                   aggr_interface.subtype)
        self.execute_lines(aggr_interface_config, exception_on_bad_command=True)

        if hasattr(aggr_interface, 'subinterfaces') and isinstance(
                aggr_interface.subinterfaces, list):
            for subinterface in aggr_interface.subinterfaces:
                logger.info('Configuring aggregate interface subinterface {}.{}'.format(
                    aggr_interface.hardware, subinterface['id']))
                subinterface_config = """
                    top
                    scope eth-uplink
                    scope fabric a
                    scope aggr-interface {}
                    scope interface {}
                    create subinterface {}
                    set vlan {}
                    set port-type {}
                    exit
                    commit-buffer
                """.format(re.search('Ethernet\d+/\d+', aggr_interface.hardware).group(0),
                           aggr_interface.hardware,
                           str(subinterface['id']),
                           str(subinterface['vlan_id']),
                           str(subinterface.get('subtype', 'data')))
                self.execute_lines(subinterface_config,
                                   exception_on_bad_command=False)

    def configure_interface(self, interface):
        """
        Configure an interface on the chassis
        :param interface: a dict describing the interface
        information (see testbed format for details)
        """
        interface_config = """
            top
            scope eth-uplink
            scope fabric a
            scope interface {}
            set port-type {}
            enable
            exit
            commit-buffer
        """.format(interface.hardware, interface.subtype)
        self.execute_lines(interface_config, exception_on_bad_command=True)

        if hasattr(interface, 'subinterfaces') and isinstance(
                interface.subinterfaces, list):
            for subinterface in interface.subinterfaces:
                subinterface_config = """
                    top
                    scope eth-uplink
                    scope fabric a
                    scope interface {}
                    create subinterface {}
                    set vlan {}
                    set port-type {}
                    exit
                    commit-buffer
                """.format(interface.hardware,
                           str(subinterface['id']),
                           str(subinterface['vlan_id']),
                           str(subinterface.get('subtype', 'data')))
                self.execute_lines(subinterface_config,
                                   exception_on_bad_command=False)

    def configure_chassis_interfaces(self, chassis_network_data):
        """
        Configure the chassis interfaces
        :param chassis_network_data: a dict describing the chassis network
        information (see testbed format for details)
        """
        port_channels = [chassis_network_data['interfaces'][iface]
                         for iface in chassis_network_data['interfaces']
                         if 'chassis_mgmt' not in iface and chassis_network_data[
                             'interfaces'][iface].type.lower() == 'portchannel']
        # this is a special port, we make sure it is reset to the default state
        # to avoid errors
        port_channels_config = """
            top
            scope ssa
            scope eth-uplink
                scope fabric a
                    enter port-channel 48
                        set port-type cluster
                        enable
                    exit
        """
        self.execute_lines(port_channels_config, exception_on_bad_command=True)

        for port_channel in port_channels:
            self.configure_port_channel(port_channel)

        interfaces = [chassis_network_data['interfaces'][iface]
                      for iface in chassis_network_data['interfaces']
                      if 'chassis_mgmt' not in iface and chassis_network_data[
                          'interfaces'][iface].type == 'Ethernet' and
                      re.match('^Ethernet\d+/\d+$', chassis_network_data['interfaces'][iface].hardware.strip())]

        for iface in interfaces:
            self.configure_interface(iface)

        aggr_interfaces = [chassis_network_data['interfaces'][iface]
                           for iface in chassis_network_data['interfaces']
                           if 'chassis_mgmt' not in iface and chassis_network_data[
                               'interfaces'][iface].type == 'Ethernet' and
                           re.match('^Ethernet\d+/\d+/\d+$', chassis_network_data['interfaces'][
                               iface].hardware.strip())]
        for aggr_iface in aggr_interfaces:
            self.configure_aggr_interface(aggr_iface)

    def delete_all_resource_profiles(self):
        """
        Deletes all the resource profiles present on the device
        :return: None
        """
        for profile in self.get_resource_profiles_list():
            self.execute_lines("""
                top
                scope ssa
            """)
            self.execute_lines("""
                delete resource-profile {}
            """.format(profile.profile_name))
            self.execute_lines("""
                commit-buffer
            """, exception_on_bad_command=True)

    def configure_resource_profiles(self, chassis_software_data):
        """
        Cleans up all resource profiles on the device and configures the
        chassis resource profiles configuration commands
        :param chassis_software_data: a dict describing the chassis software
        configuration (see testbed format for details)
        :return: the commands for the configuration of the resource profiles
        """
        resource_profiles_config = ""
        rps_on_device = [rp.profile_name for rp in
                         self.get_resource_profiles_list()]
        for profile in chassis_software_data.get('resource_profiles', []):
            if chassis_software_data['resource_profiles'][profile]['name'] in \
                    rps_on_device:
                continue
            resource_profiles_config += """
                top
                scope ssa
                create resource-profile {}
                set cpu-core-count {}
                commit-buffer
            """.format(
                chassis_software_data['resource_profiles'][profile]['name'],
                chassis_software_data['resource_profiles'][profile][
                    'cpu_core_count']
            )
        logger.info("""command lines for resource profiles config
            {}
        """.format(resource_profiles_config))
        self.execute_lines(resource_profiles_config,
                           exception_on_bad_command=True)

    def accept_application_license_agreement(self, app_version):
        accept_license_agreement = """
                        top
                        scope ssa
                        scope app ftd {}
                        accept-license-agreement
                        commit-buffer
                    """.format(app_version)
        logger.info("""command lines for license agreement accept
                    {}
                """.format(accept_license_agreement))
        self.execute_lines(accept_license_agreement,
                           exception_on_bad_command=True, timeout=60)

    def accept_license_agreement(self, chassis_data):
        """
        Executes the commands needed to accept the license agreement for
        all the apps involved in the baseline procedure
        :param chassis_data: a dict describing the chassis
        (see testbed format for details)
        :return: the commands to accept all the license agreements for the
        apps involved in the baseline procedure
        """
        app_versions = []
        for app_key, app_data in chassis_data['custom']['chassis_software'][
            'applications'].items():
            app_versions.append(app_data['startup_version'])

        app_versions = set(app_versions)
        for app_version in app_versions:
            self.accept_application_license_agreement(app_version)

    def _get_interface_object_from_chassis_data(self, external_port_link, chassis_network):
        interface_object = None
        chassis_interfaces = chassis_network['interfaces']
        is_port_interface = re.match(
            '^Ethernet\d+/\d+$', external_port_link, re.IGNORECASE)
        is_port_subinterface = re.match(
            '^Ethernet\d+/\d+\.\d+$', external_port_link, re.IGNORECASE)
        is_port_portchannel = re.match(
            'Port-channel\d+', external_port_link, re.IGNORECASE)
        is_port_aggr_interface = re.match('^Ethernet\d+/\d+/\d+$', external_port_link, re.IGNORECASE)
        is_port_aggr_subinterface = re.match('^Ethernet\d+/\d+/\d+.\d+$', external_port_link, re.IGNORECASE)
        for intf in chassis_interfaces:
            if 'chassis_mgmt' not in intf:
                iface = chassis_interfaces[intf]
                if is_port_interface and iface.type.lower().startswith(
                        'ethernet') and iface.hardware == external_port_link:
                    interface_object = iface
                    break
                if is_port_subinterface and \
                        iface.type.lower().startswith('ethernet'):
                    if hasattr(iface, 'subinterfaces'):
                        subiface_ids = [iface.hardware + '.' +
                                        str(s['id'])
                                        for s in iface.subinterfaces]
                        if external_port_link in subiface_ids:
                            interface_object = iface
                            break
                if is_port_portchannel and iface.type.lower().startswith(
                        'portchannel') and hasattr(iface, 'id') and \
                        re.match('Port-channel' + str(iface.id),
                                 external_port_link, re.IGNORECASE):
                    interface_object = iface
                    break
                if is_port_aggr_interface and iface.type.lower().startswith('ethernet') and \
                        iface.hardware == external_port_link:
                    interface_object = iface
                    break
                if is_port_aggr_subinterface and iface.type.lower().startswith('ethernet'):
                    if hasattr(iface, 'subinterfaces'):
                        subiface_ids = [iface.hardware + '.' +
                                        str(s['id'])
                                        for s in iface.subinterfaces]
                        if external_port_link in subiface_ids:
                            interface_object = iface
                            break
        return interface_object

    def check_all_logical_devices_configuration(self):
        """
        Method checks if one of the logical devices is configured improperly
        """
        logger.info('Checking logical device for reported configuration errors...')
        # wait for logical device to report any errors
        time.sleep(10)
        for ld in self.get_logical_device_list():
            if 'incomplete' in ld.operational_state.lower():
                raise RuntimeError('Incomplete configuration of logical device: {}. Error Msg: {}'.format(
                ld.name, ld.error_msg))

    def configure_logical_devices_standalone(self, chassis_data):
        """
        Configures the logical devices when baselining in standalone mode
        :param chassis_data: the dict describing the chassis configuration
        (see testbed format for details)
        :return: the commands for the configuration of the logical devices
        in standalone mode
        """
        chassis_sw = chassis_data['custom']['chassis_software']
        for app_key, app_data in chassis_sw['applications'].items():
            self.create_app_instance(app_data, wait_upto=60)
            self.create_logical_device(app_data['slot'],
                                       app_data['logical_device'],
                                       chassis_data['custom'][
                                           'chassis_network'],
                                       app_data['application_name'],
                                       wait_upto=60)

    def delete_all_port_channels(self, skip_pc_ids=[48]):
        """
        Deletes app port channels found on the device except those
        specified in the skip_pc_ids list
        :param skip_pc_ids: ports to skip deletion
        :return: None
        """
        port_channels = self.get_port_channel_list()
        for port_channel in port_channels:
            self.execute_lines("""
                top
                scope ssa
                scope eth-uplink
                scope fabric a
            """)
            if int(port_channel.id) not in skip_pc_ids:
                self.execute_lines("""
                    delete port-channel {}
                """.format(port_channel.id))
            self.execute_lines('commit-buffer', exception_on_bad_command=True)

    def get_interfaces_list(self):
        """
        Get the list of interfaces present on the device
        :return: the list of interfaces names
        """
        cmd_lines = """
           top
           scope eth-uplink
           scope fabric a
           show interface detail
       """
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)
        interfaces_list = []
        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Port Name':
                interfaces_list.append(a_value)
        return interfaces_list

    def get_subinterfaces_list(self, interface_name):
        """
        Get the list of subinterfaces belonging to the specified interface
        :param interface_name: the interface name
        :return: the list of subinterfaces defined for the interface
        """
        cmd_lines = """
           top
           scope eth-uplink
           scope fabric a
           scope interface {}
           show subinterface detail
        """.format(interface_name)
        self.go_to('mio_state')
        output = self.execute_lines(cmd_lines, timeout=60)
        interfaces_list = []
        for line in output.split('\n'):
            line = line.strip()
            if line == '':
                continue
            logger.debug('line=' + line)
            if line.find(':') == -1:
                continue
            name_value = line.split(':')
            a_name = name_value[0].strip()
            a_value = name_value[1].strip()
            if a_name == 'Sub-If Id':
                interfaces_list.append(a_value)
        return interfaces_list

    def delete_all_subinterfaces(self):
        """
        Deletes all subinterfaces found on the device
        :return:
        """
        interfaces = self.get_interfaces_list()
        for interface in interfaces:
            self.execute_lines("""
                top
                scope ssa
                scope eth-uplink
                scope fabric a
                scope interface {}
            """.format(interface))
            subinterfaces = self.get_subinterfaces_list(interface)
            for subinterface in subinterfaces:
                self.execute_lines('delete subinterface {}'.format(
                    subinterface))
                self.execute_lines('commit-buffer',
                                   exception_on_bad_command=True)

    def configure_port_channel(self, port_channel):
        """
        Configure a port channel on the chassis
        :param port_channel: a dict describing the port channel
        information (see testbed format for details)
        """
        port_channel_config = """
            top
            scope ssa
            scope eth-uplink
            scope fabric a
            create port-channel {}
                set port-type {}
                enable
                commit-buffer""".format(port_channel.id,
                                 port_channel.subtype if
                                 (hasattr(port_channel, 'subtype')
                                  and port_channel.subtype) else 'data')
        self.execute_lines(port_channel_config, exception_on_bad_command=False)

        if hasattr(port_channel, 'member_ports') and isinstance(
                port_channel.member_ports, list):
            for member_port in port_channel.member_ports:
                member_port_config = """
                    top
                    scope ssa
                    scope eth-uplink
                    scope fabric a
                    enter port-channel {}
                    create member-port {}
                    enable
                    commit-buffer
                """.format(port_channel.id, member_port)
                self.execute_lines(member_port_config,
                                   exception_on_bad_command=False)

        if hasattr(port_channel, 'subinterfaces') and isinstance(
                port_channel.subinterfaces, list):
            for subinterface in port_channel.subinterfaces:
                subinterface_config = """
                    top
                    scope ssa
                    scope eth-uplink
                    scope fabric a
                    enter port-channel {}
                    create subinterface {}
                    set vlan {}
                    set port-type {}
                    exit
                    commit-buffer
                """.format(port_channel.id,
                           str(subinterface['id']),
                           str(subinterface['vlan_id']),
                           str(subinterface.get('subtype', 'data')))
                self.execute_lines(subinterface_config,
                                   exception_on_bad_command=False)

    def configure_logical_device_clustered(self, chassis_data):
        """
        Constructs and executes all the lines needed for configuring the
        logical device when deploying in clustered mode.
        :param chassis_data: a dict describing the chassis configuration
        :return: None
        """
        cluster_slot_str = ''
        for slot in self.get_all_slot_list():
            cluster_slot_str += str(slot) + ','
        cluster_slot_str = cluster_slot_str[:-1]
        chassis_id = int(chassis_data['custom']['chassis_id'])
        interfaces_mode = chassis_data['custom']['chassis_network'][
            'interfaces_mode']
        cluster_group_name = chassis_data['custom']['cluster_group_name']
        first_app_key = list(chassis_data['custom']['chassis_software'][
            'applications'].keys())[0]
        logical_device_name = chassis_data['custom']['chassis_software'][
            'applications'][first_app_key]['logical_device']['name']
        application_name = chassis_data['custom']['chassis_software'][
            'applications'][first_app_key]['application_name']

        logical_device_config = """
            top
            scope ssa
            enter logical-device {} {} {} clustered
            enter cluster-bootstrap
            set chassis-id {}
        """.format(
            logical_device_name,
            application_name,
            '"' + cluster_slot_str + '"',
            chassis_id
        )
        if chassis_data['custom'].get('chassis_site', None):
            logical_device_config += """
                set site-id {}
            """.format(int(chassis_data['custom']['chassis_site']))
        self.execute_lines(logical_device_config, timeout=60)

        self.set_key(chassis_data['custom']['chassis_security_key'])

        logical_device_config = """
            set mode {}
            set service-type {}
            exit
        """.format(
            interfaces_mode,
            cluster_group_name
        )
        self.execute_lines(logical_device_config)

        self.execute_lines("enter mgmt-bootstrap ftd")
        for bs_secret_key, value in chassis_data['custom']['chassis_software'][
            'applications'][first_app_key]['logical_device'][
            'bootstrap_keys_secret'].items():
            self.execute_lines("enter bootstrap-key-secret {}".format(
                bs_secret_key.upper()))
            self.set_value(value)
            self.execute_lines("exit")
        self.execute_lines("exit")

        logical_device_config = """
            
            enter mgmt-bootstrap ftd
        """
        for bs_key, value in chassis_data['custom']['chassis_software'][
            'applications'][first_app_key]['logical_device']['bootstrap_keys'].items():
            logical_device_config += """
                enter bootstrap-key {}
                    set value {}
                exit
            """.format(
                bs_key.upper(),
                value
            )

        for app_key, app_data in chassis_data['custom']['chassis_software'][
            'applications'].items():
            logical_device_config += """
                
                enter ipv4 {} firepower
                set ip {} mask {}
                set gateway {}
                exit
            """.format(
                str(app_data['slot']),
                app_data['logical_device']['ipv4']['ip'],
                app_data['logical_device']['ipv4']['netmask'],
                app_data['logical_device']['ipv4']['gateway']
            )

        logical_device_config += """
            commit-buffer
        """
        logger.info("""command lines for logical devices config
            {}
        """.format(logical_device_config))
        self.execute_lines(logical_device_config, timeout=60,
                           exception_on_bad_command=True)

        self.wait_till(self.is_logical_device_created, (logical_device_name, ),
                       wait_upto=60)

        self.check_all_logical_devices_configuration()

    def get_user_provided_slot_list(self, chassis_data):
        """
        Method gets the user provided slot list inside the testbed.
        :param chassis_data: the dictionary describing the chassis
        :return: the list of the user used slots
        """
        user_provided_slots = []
        user_apps = chassis_data['custom']['chassis_software'][
            'applications']
        for app, app_value in user_apps.items():
            user_provided_slots.append(int(app_value['slot']))
        return list(set(user_provided_slots))

    def cleanup_slots(self, cleanup_user_slots_only, cleanup_apps,
                      reinitialize_slots, chassis_data=None):
        """
        Deletes logical devices and apps on all slots of the chassis
        :param chassis_data: a dict describing the chassis data
        :return: None
        """
        if cleanup_user_slots_only:
            available_slots = self.get_user_provided_slot_list(chassis_data)
        else:
            available_slots = self.get_equipped_slot_list()
        if cleanup_apps:
            for slot in available_slots:
                # Delete logical device and app instance for the slot
                logger.info('=== Delete logical device and app instance')
                self.delete_logical_devices_and_app_instances(slot)
        if reinitialize_slots:
            self.reinitialize_slots(available_slots)

    def install_fxos(self, fxos_url, file_server_password, http_url):
        """
        Downloads and starts the installation procedure of the fxos package
        :param fxos_url:  the fxos scp address from where to download the fxos
        :param file_server_password: the scp password
        :param http_url: the fxos http address from where to download the fxos
        :param chassis_hostname: the chassis hostname
        :return: None
        """
        if fxos_url:
            # Download fxos bundle image
            logger.info('=== Download fxos bundle image')
            self.download_fxos(fxos_url=fxos_url,
                               file_server_password=file_server_password,
                               http_url=http_url)

            # Upgrade bundle image
            logger.info('=== Upgrade bundle image')
            bundle_package = fxos_url.split('/')[-1].strip()
            if self.upgrade_bundle_package(bundle_package):
                logger.info(
                    "Package installation has been completed successfully!")
        else:
            raise RuntimeError('Please provide the fxos package via the'
                               'fxos_url under chassis_software.')

    def wait_for_baseline_app_creation(self, chassis_data,
                                       wait_for_app_to_start=600):
        """
        Function used to wait for the creation of apps after the baseline
        has started. The apps are checked sequentially. The function also
        connects to each app and goes to the fireos state, changing the
        password if this is needed (first time connect to ftd)
        :param chassis_data: a dict describing the chassis configuration
        :param wait_for_app_to_start: time to wait for each app to start
        :return: None
        """
        in_cluster_mode = self.is_clustered(chassis_data)
        for slot in self.get_user_provided_slot_list(chassis_data):
            self.wait_till_slot_online(slot)

        for app_key, app_data in chassis_data['custom'][
            'chassis_software']['applications'].items():
            slot_id = str(app_data['slot'])
            app_name = app_data['application_name']
            app_identifier = app_data['application_identifier']
            self.wait_till_app_instance_ready(slot_id, app_name,
                                              app_identifier,
                                              in_cluster_mode,
                                              wait_for_app_to_start)

            if 'ftd' in app_name:
                if in_cluster_mode:
                    # if slot is not populated with hardware skip for cluster
                    # mode
                    if self._get_slot_operational_state(slot_id) == \
                            'Not Available':
                        continue
                logger.info('Connecting to FTD {} from slot {} and '
                            'changing password '.format(app_identifier,
                                                        slot_id))
                self.set_current_slot(slot_id)
                self.set_current_application(app_identifier)
                # wait up to 10 minutes for the ftd to be initialized
                try:
                    self.go_to('fireos_state', timeout=600)
                except StateMachineError as e:
                    # the below can happen on slow devices where the password is sent to the device but for
                    # some reason after showing the initial configuration prompt and going into fireos
                    # the device echoes back the password in the fireos buffer. This causes a state machine exception
                    # because the buffer is poluted with the password like so: '> Admin123!' although everything is
                    # good and we need to only clean the prompt which is handled below
                    self.spawn_id.read_update_buffer()
                    logger.info('Encountered exception: {}'.format(str(e)))
                    logger.info('spawn_id buffer is: {}'.format(self.spawn_id.buffer))
                    try:
                        self.spawn_id.buffer = ''
                        self.spawn_id.sendline('\x15')
                        self.spawn_id.sendline()
                        d = Dialog([['> ', 'sendline()', None, False, False]])
                        d.process(self.spawn_id, timeout=10)
                        self.sm.update_cur_state(self.sm.get_state('fireos_state'))
                    except Exception as e:
                        # the above should not fail because it causes the next devices to skip the
                        # initial configuration. It should only report an error.
                        logger.info('Encountered exception while trying to clean fireos prompt. '
                                    'Exception is: {}'.format(str(e)))

                logger.info('Password changed on FTD {} from slot '
                            '{}'.format(app_identifier, slot_id))
                self.go_to('mio_state', timeout=360)

    def is_clustered(self, chassis_data):
        """
        Returns if the device is in clustered mode or not.
        :param chassis_data: a dict describing the chassis configuration
        :return: True or False
        """
        clustered = None
        if chassis_data['custom']['chassis_software'][
            'device_mode'] == 'standalone':
            clustered = False
        if chassis_data['custom']['chassis_software'][
            'device_mode'] == 'clustered':
            clustered = True
        assert clustered is not None, \
            'Please specify "standalone" or "clustered" logical device mode.'
        return clustered

    def power_cycle_before_baseline(self, chassis_data):
        """
        Checks if the user has specified whether to power cycle before
        baseline or not
        :param chassis_data: a dict describing the chassis configuration
        :return: True or False
        """
        power_data = chassis_data['custom'].get('chassis_power', None)
        if not power_data:
            return False
        power_cycle_before_baseline = power_data.get(
            'power_cycle_before_baseline', 'false').lower()
        if power_cycle_before_baseline == 'false':
            power_cycle_before_baseline = False
        else:
            power_cycle_before_baseline = True
        logger.info(
            '=== Power cycle the device if power_cycle_flag is True')
        logger.info(
            '=== power_cycle_flag={}'.format(str(power_cycle_before_baseline)))
        return power_cycle_before_baseline

    def check_ftd_cpu_count_same_as_in_resource_profile(
            self, application_data, resource_profiles):
        """
        After the fTD comes up fine, go to “system support diagnostic-cli”
        and do “show version"
        ...
        Hardware:   FPR9K-SM-24, 108517 MB RAM, CPU Xeon E5 series 2200 MHz,
        2 CPUs (22 cores)
        ...
        :param application_data: the app data dict
        :param resource_profiles: the resource_profiles dict
        :return: None
        """
        rps_on_device = self.get_resource_profiles_list()
        self.set_current_slot(application_data['slot'])
        self.set_current_application(application_data['application_identifier'])
        self.go_to('enable_state')
        output = ''
        self.spawn_id.sendline('show version')
        time.sleep(10)
        while True:
            match_output = self.spawn_id.expect('.*').match_output
            output += match_output
            if '<--- More --->' in match_output:
                self.spawn_id.sendline('\x20')
                time.sleep(10)
            else:
                break
        self.go_to('mio_state')
        output = re.search('\n(Hardware:.*)\n', output).group(0)
        no_of_assigned_cores = int(re.search('\((.*)cores.*\)', output).group(
            1).strip())
        no_of_defined_cores = int(
            [rp.cpu_logical_core_count for rp in rps_on_device
             if rp.profile_name.strip() == application_data[
                 'resource_profile'].strip()][0])
        assert no_of_assigned_cores == no_of_defined_cores, \
            "The number of cores assigned to the application {} is different" \
            "from the number of cores defined in the resource profile {}".format(
                application_data['application_identifier'],
                application_data['resource_profile']
            )

    def check_interfaces_not_in_config_error(self, application_data):
        """
        > show interface ip brief
        Interface                  IP-Address      OK?           Method Status      Protocol
        Internal-Data0/0           unassigned      YES           unset  up          up
        Internal-Data0/1           unassigned      YES           unset  up          up
        Internal-Data0/2           169.254.1.1     YES           unset  up          up
        Internal-Data0/3           unassigned      YES           unset  down        down
        Ethernet1/1                unassigned      YES           unset  down        down
        Ethernet1/2.1              unassigned      YES           unset  down        down
        Ethernet1/3                unassigned      YES           unset  admin down  down
        :param application_data: the app data dict
        :return: None
        """
        self.set_current_slot(application_data['slot'])
        self.set_current_application(application_data['application_identifier'])
        self.go_to('fireos_state')
        output = ''
        self.spawn_id.sendline('show interface ip brief')
        time.sleep(10)
        while True:
            match_output = self.spawn_id.expect('.*').match_output
            output += match_output
            if '<--- More --->' in match_output:
                self.spawn_id.sendline('\x20')
                time.sleep(10)
            else:
                break
        self.go_to('mio_state')
        output_lines = output.split('\n')
        for out_line in output_lines:
            if 'config-error' in out_line:
                raise RuntimeError('Configuration error concerning '
                                   'interface. Details: '.format(out_line))

    def cleanup_chassis(self, chassis_data):
        """
        Method perform cleanup on the chassis according to the cleanup options
        provided in the testbed.
        :param chassis_data: the dictionary describing the chassis from the
        testbed
        :return: None
        """
        options = chassis_data['custom'].get('cleanup_options', {})
        cleanup_user_slots_only = options.get('cleanup_user_slots_only', True)
        cleanup_apps = options.get('cleanup_apps', True)
        reinitialize_slots = options.get('reinitialize_slots', True)
        reset_interfaces_to_data_type = options.get(
            'reset_interfaces_to_data_type', True)
        cleanup_subinterfaces = options.get('cleanup_subinterfaces', True)
        cleanup_aggr_interfaces = options.get('cleanup_aggregate_interfaces', True)
        cleanup_port_channels = options.get('cleanup_port_channels', True)
        cleanup_resource_profiles = options.get(
            'cleanup_resource_profiles', True)

        self.cleanup_slots(cleanup_user_slots_only, cleanup_apps,
                           reinitialize_slots, chassis_data)
        if cleanup_port_channels:
            self.delete_all_port_channels()
        if cleanup_subinterfaces:
            self.delete_all_subinterfaces()
        if reset_interfaces_to_data_type:
            self.assign_all_interfaces_to_data_type()
        if cleanup_aggr_interfaces:
            self.assign_all_aggr_interfaces_to_data_type()
        if cleanup_resource_profiles:
            self.delete_all_resource_profiles()

    def do_extra_checks_after_baseline(self, chassis_data):
        """
        Method performs extra checks after the baseline has finished:
            - checks the number of cpu cores assigned to each app is the
            same as those specified in the resource profile
            - checks none of the interfaces assigned to the app is in
            config error mode.
        :param chassis_data: the dictionary describing the chassis data from
        the testbed
        :return: None
        """
        in_cluster_mode = self.is_clustered(chassis_data)
        for app_key, app_data in chassis_data['custom'][
            'chassis_software']['applications'].items():
            slot_id = str(app_data['slot'])
            if in_cluster_mode:
                # if slot is not populated with hardware skip for cluster
                # mode
                if self._get_slot_operational_state(slot_id) == \
                        'Not Available':
                    continue
            if app_data.get('resource_profile', None) and chassis_data[
                'custom']['chassis_software'].get('resource_profiles', None):
                self.check_ftd_cpu_count_same_as_in_resource_profile(
                    app_data,
                    chassis_data['custom']['chassis_software'][
                        'resource_profiles']
                )
            self.check_interfaces_not_in_config_error(app_data)

    def baseline_by_branch_and_version(self,
                                       chassis_data,
                                       wait_for_app_to_start=3600, serverIp='', tftpPrefix='', scpPrefix='', docs='', pxePassword='', fxosDir=''):
        """
        Generic function used to perform a basic baseline in standalone or
        clustered mode for the device by branch and version. The fxos and
        csp images are first copied to the pxe server closest to the device.

        :param site: the site where the device is located ('ast', 'ful')
        :param branch: the branch of the build
        :param version: the version of the build
        :param chassis_data: a dict describing the chassis configuration
        :param wait_for_app_to_start: the time to wait for the applications
        to be created and started
        :return: None
        """
        publish_kick_metric('device.chassis_by_branch_and_version.baseline', 1)

        chassis_software = chassis_data['custom']['chassis_software']
        if not chassis_software.get('fxos_url', None):
            if chassis_data['custom']['chassis_software'].get(
                    'install_fxos', True):
                raise RuntimeError("Please provide the fxos version you want " +
                                   "via fxos_url parameter under " +
                                   "chassis_software.")

        if not chassis_software.get('site', None):
            raise RuntimeError("Please provide the site where the device is " +
                               "located via the site parameter under " +
                               "chassis_software.")

        if not chassis_software.get('branch', None):
            raise RuntimeError("Please provide the branch to use for apps " +
                               "via the branch parameter under " +
                               "chassis_software.")

        if not chassis_software.get('version', None):
            raise RuntimeError("Please provide the version to use for apps " +
                               "via the version parameter under " +
                               "chassis_software.")

        # If the user specified a branch and a version use that
        # for baseline, but from pxe
        site = chassis_software['site']
        branch = chassis_software['branch']
        version = chassis_software['version']
        for app_key, app_data in chassis_data['custom']['chassis_software'][
            'applications'].items():
            app_data['startup_version'] = \
                version.lower().replace('-', '.').strip()

        fxos_url = chassis_software.get('fxos_url', None)
        fxos_file = None
        if fxos_url:
            fxos_file = fxos_url.split('/')[-1]
        if not chassis_data['custom'][
            'chassis_software'].get('install_fxos', True):
            fxos_file=None
        is_sw_on_device = self.is_fxos_image_on_device(fxos_url) and \
                          self.is_app_image_on_device(
                              version.lower().replace('-', '.').strip())
        server_password = None
        if not is_sw_on_device:
            if KICK_EXTERNAL:
                server_ip = serverIp
                tftp_prefix = tftpPrefix
                scp_prefix = scpPrefix
                files = docs
                server_password = pxePassword
                scp_fxos_link = 'scp://pxe@{}:{}/{}'.format(server_ip, fxosDir, fxos_file)
            else:
                server_ip, tftp_prefix, scp_prefix, files = \
                    prepare_installation_files(site, 'chassis', branch, version,
                                               fxos_file=fxos_file, fxos_link=fxos_url)
                scp_fxos_link = 'scp://pxe@{}:{}/{}'.format(server_ip,
                                                            pxe_dir['fxos_dir'],
                                                            fxos_file)
                server_password = pxe_password
            csp_file = [file for file in files if file.endswith('.csp')][0]
            scp_csp_link = "scp://pxe@{}:/{}/{}".format(server_ip, scp_prefix,
                                                        csp_file)
        else:
            logger.info('\n\n\nFXOS and APP images found already downloaded on '
                        'device.\n\n\n')
            scp_fxos_link = fxos_url
            scp_csp_link = version.lower().replace('-', '.').strip()

        self.baseline_fxos_and_apps(
            fxos_url=scp_fxos_link, csp_urls=[scp_csp_link],
            scp_password=server_password, http_url='', chassis_data=chassis_data,
            wait_for_app_to_start=wait_for_app_to_start)

    def baseline(self, chassis_data, wait_for_app_to_start=3600):
        publish_kick_metric('device.chassis.baseline', 1)
        csp_urls = []
        chassis_software = chassis_data['custom']['chassis_software']
        if not chassis_software.get('fxos_url', None):
            if chassis_data['custom']['chassis_software'].get(
                    'install_fxos', True):
                raise RuntimeError("Please provide the fxos version you want " +
                                   "via fxos_url parameter.")
        fxos_url = chassis_software['fxos_url']

        if not chassis_software.get('scp_password', None):
            raise RuntimeError("Please provide the scp password for the " +
                               "server via the scp_password parameter.")
        scp_password = chassis_software['scp_password']

        if chassis_software.get('csp_url', None):
            csp_urls = [chassis_software['csp_url']]
            for app, app_data in chassis_software['applications'].items():
                if app_data.get('csp_url', None):
                    csp_urls.append(app_data['csp_url'])
        else:
            for app, app_data in chassis_software['applications'].items():
                if not app_data.get('csp_url', None):
                    raise RuntimeError(
                        "You did not specify a top level csp_url under " +
                        "'chassis_software' key. You either need to specify " +
                        "a top level csp_url under 'chassis_software' which " +
                        "will be used for all the apps OR provide a csp_url" +
                        "attribute under each application. Also, you can " +
                        "specify a csp_url under 'chassis_software' and " +
                        "override the csp_url under a specific app."
                    )
                csp_urls.append(app_data['csp_url'])
        csp_urls = list(set(csp_urls))

        for app in chassis_data['custom']['chassis_software']['applications']:
            app_data = chassis_data['custom']['chassis_software'][
                'applications'][app]
            if not app_data.get('startup_version', None):
                filename = os.path.basename(app_data['csp_url'])
                startup_version = re.search(
                    '\.(\d+\.\d+\.\d+\.\d+)\.s', filename,
                    re.IGNORECASE).group(1)
                app_data.update({'startup_version': startup_version})

        self.baseline_fxos_and_apps(
            fxos_url=fxos_url, csp_urls=csp_urls,
            scp_password=scp_password, http_url='', chassis_data=chassis_data,
            wait_for_app_to_start=wait_for_app_to_start)

    def baseline_standalone(self, chassis_data):
        """
        Performs the standalone specific steps of the baseline
        :param chassis_data: a dict describing the chassis (see testbed format
        for details)
        :return: None
        """
        publish_kick_metric('device.chassis_standalone.baseline', 1)

        self.configure_logical_devices_standalone(chassis_data)

    def baseline_clustered(self, chassis_data):
        """
        Performs the clustered specific steps of the baseline
        :param chassis_data: a dict describing the chassis (see testbed format
        for details)
        :return: None
        """
        publish_kick_metric('device.chassis_clustered.baseline', 1)

        self.configure_logical_device_clustered(chassis_data)

    def baseline_fxos_and_apps(self, fxos_url, csp_urls, scp_password,
                               chassis_data, http_url,
                               wait_for_app_to_start=1800):
        """
        Generic baseline function for performing the baseline on 1RU
        and 3RU devices, standalone and clustered
        :param fxos_url: the fxos url scp path
        :param csp_urls: the list of csp url paths
        :param scp_password: the scp password for the server hosting both
        the fxos and csp images
        :param chassis_data: a dict describing the chassis (see testbed format
        for details)
        :param http_url: the http url for downloading the fxos
        :param wait_for_app_to_start: the time to wait for the applications
        to be created and started
        :return: None
        """
        publish_kick_metric('device.chassis_fxos_and_apps.baseline', 1)

        self.execute_lines("""
            top
            discard
        """)

        # set disconnect timeout to maximum
        self.set_default_auth_timeouts()

        # cleanup
        self.cleanup_chassis(chassis_data)

        # power cycle
        power_cycle_before_baseline = self.power_cycle_before_baseline(
            chassis_data)
        if power_cycle_before_baseline:
            self.set_power_bar(chassis_data['custom']['chassis_power'])
            self.power_cycle(wait_until_device_is_on=True,
                             timeout=900)

        # configure chassis network settings
        self.configure_chassis_network(
            chassis_data['custom']['chassis_network'])

        # install os
        if chassis_data['custom']['chassis_software'].get('install_fxos', True):
            self.install_fxos(fxos_url, scp_password, http_url)

        for csp_url in csp_urls:
            # download application
            self.download_csp(csp_url, scp_password)

        self.configure_chassis_interfaces(
            chassis_data['custom']['chassis_network'])

        # create resource profiles
        self.configure_resource_profiles(
            chassis_data['custom']['chassis_software'])

        # accept license agreement for apps that will be installed on slots
        self.accept_license_agreement(chassis_data)

        if self.is_clustered(chassis_data):
            self.baseline_clustered(chassis_data)
        else:
            self.baseline_standalone(chassis_data)

        self.wait_for_baseline_app_creation(chassis_data, wait_for_app_to_start)

        self.do_extra_checks_after_baseline(chassis_data)

        logger.info('Baseline finished successfully.')
