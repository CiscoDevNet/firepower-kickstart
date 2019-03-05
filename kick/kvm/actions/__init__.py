"""This module implements methods for deployment of virtual NGFW devices on
KVM."""
import re
import os
import time
import datetime
import os.path
import requests

from unicon.eal.expect import Spawn
from unicon.eal.dialogs import Dialog
from unicon.utils import AttributeDict
import urllib.request
import urllib.error
from .kvm_constants import InputConstants, find_file_on_pxe

try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric

import logging
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10


class Kvm:
    """Class for defining a KVM object."""
    
    def __init__(self, hostname='selenium-server', kvm_username='cisco',
                 kvm_password='cisco',
                 kvm_sudo_password='cisco'):
        """Constructor of Kvm.

        :param hostname: hostname of kvm
                        e.g. 'selenium-server'
        :param kvm_username: user name for login
        :param kvm_password: password for login
        :param kvm_sudo_password: password for root

        """
        
        self.kvm_username = kvm_username
        self.kvm_password = kvm_password

        # set hostname and enable_password
        from .constants import KvmConstants
        KvmConstants.hostname = hostname
        KvmConstants.kvm_username = kvm_username
        KvmConstants.kvm_login_password = kvm_password
        KvmConstants.kvm_sudo_password = kvm_sudo_password

        from .statemachine import KvmStatemachine
        self.sm = KvmStatemachine()

        # set timeout
        self.set_default_timeout(DEFAULT_TIMEOUT)

        # send metrics to grafana
        publish_kick_metric('kvm.init', 1)

    def set_default_timeout(self, timeout):
        """Change default timeout to given value:

        :param timeout: default timeout value in seconds
        :return: None

        """
        
        logger.debug('setting device default timeout to {}'.format(timeout))
        self.default_timeout = timeout

    def ssh(self, ip, port, username='', password='', timeout=None):
        """Setup ssh connection.

        :param ip: platform management IP
        :param port: ssh port
        :param username: login username
        :param password: login password
        :param timeout: timeout for ssh connection
        :return: a KvmLine object

        """
        
        if not timeout:
            timeout = self.default_timeout

        username = username or self.kvm_username
        password = password or self.kvm_password

        self.spawn = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                           '-l {} -p {} {} '.format(username, port, ip))
        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            [r'(P|p)assword: ', 'sendline({})'.format(password),
             None, True, False],
            ['Last login:', 'sendline()', None, False, False],
        ])
        d1.process(self.spawn, timeout=timeout)
        self.spawn.sendline()
        ssh_line = KvmLine(self.spawn, self.sm, 'ssh', kvm_line=True)

        logger.debug("Done: connection created by ssh {} {}".format(ip, port))
        return ssh_line


class KvmLine:
    """This class handles the actions that can be done on a KVM."""
    
    def __init__(self, spawn_id, sm, type, kvm_line=True):
        """Constructor of KVM line.

        :param spawn_id: spawn object
        :param sm: state machine
        :param type: type of the connection: ssh or telnet
        :param kvm_line: whether this is a kvm (kvm_line=True) or vm(kvm_line=False) line
        :return: None

        """

        self.spawn_id = spawn_id
        self.sm = sm
        self.type = type
        self.kvm_line = kvm_line
        sm.go_to('any', spawn_id)
        sm.go_to('any', spawn_id)
        # set timeout
        self.set_default_timeout(DEFAULT_TIMEOUT)

    def set_default_timeout(self, timeout):
        """Change default timeout to given value.

        :param timeout: default timeout value

        """
        
        logger.debug('setting line default timeout to {}'.format(timeout))
        self.default_timeout = timeout

    def go_to(self, state, timeout=None):
        """Go to specified state: e.g. go_to('sudo_state')

        :param state: string of the state to go to
        :param timeout: timeout for command
        :return: None

        """
        
        if not timeout:
            timeout = self.default_timeout

        self.sm.go_to(state, self.spawn_id, timeout=timeout)

    def execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """Run a command, get the console output. Then exclude the command echo
        and the new prompt to return the content in between.

        :param cmd: command to be executed
        :param timeout: timeout for command execution
        :param exception_on_bad_command: True/False - whether to raise an exception
            on a bad command
        :return: the output of the command

        """

        if not timeout:
            timeout = self.default_timeout

        current_state = self.sm.current_state
        prompt = self.sm.get_state(current_state).pattern

        if self.spawn_id.read_update_buffer():
            self.spawn_id.buffer = ''

        self.spawn_id.sendline(cmd)

        output = self.spawn_id.expect(prompt, timeout=timeout).last_match.string
        logger.debug("before trimming in execute(): {}".format(output))

        index = output.find('\r\n')
        output = output[index:]

        # handle bad command
        errors = ["% Invalid Command", "% Incomplete Command", "Error: ",
                  "ERROR: "]
        if any([error in output for error in errors]):
            if exception_on_bad_command:
                raise RuntimeError("bad command: {}".format(cmd))
            else:
                logger.debug("bad command: {}".format(cmd))

        r = re.search(prompt, output)
        end = r.span()[0]

        return_data = output[:end].strip()
        logger.debug("after trimming in execute(): {}".format(return_data))

        return return_data

    def execute_lines(self, cmd_lines, timeout=None):
        """When given a string of multiple lines, run them one by one and
        return the result for the last line.

        :param cmd_lines: commands to be executed separated by new line
        :param timeout: timeout for command
        :return: output of the last command as string

        """
        
        if not timeout:
            timeout = self.default_timeout

        return_data = ""
        for cmd in cmd_lines.split('\n'):
            cmd = cmd.strip()
            if cmd == "":
                continue  # empty line
            return_data = self.execute(cmd, timeout)

        return return_data

    def execute_lines_total(self, cmd_lines, timeout=None):
        """When given a string of multiple lines, run them one by one and
        returns the output of all commands.

        :param cmd_lines: commands to be executed line by line
        :param timeout: timeout for individual command to be executed
        :return: output for all command lines executed

        """

        if not timeout:
            timeout = self.default_timeout

        return_data = ""
        for cmd in cmd_lines.split('\n'):
            cmd = cmd.strip()
            if cmd == "":
                continue  # empty line
            return_data += self.execute(cmd, timeout=timeout)

        return return_data

    def disconnect(self):
        """Disconnect the session (ssh or telnet)"""

        if self.type == 'ssh':
            # send ~.
            self.spawn_id.sendline('')
            # self.spawn_id.send('~.')
            self.spawn_id.send('exit')
            # self.spawn_id.expect('Connection to .* closed.')
        elif self.type == 'telnet':
            # send ctrl + ], then q
            self.spawn_id.send('\035')
            self.spawn_id.expect('telnet> ')
            self.spawn_id.sendline('q')
            self.spawn_id.expect('Connection closed.')

    def expect_and_sendline(self, this_spawn, es_list, timeout=None):
        """Takes a list of expect/send actions and perform them one by one.
        es_list looks like:

        [['exp_pattern1', 'send_string1', 30],
         ['exp_pattern2', 'send_string2'],
         ...]

        The third element is for timeout value, and can be omitted when the
        overall timeout value applies.

        :param this_spawn: the spawn of the line
        :param es_list: pairs of expected output and command to be sent
        :param timeout: default timeout for the command if timeout is not set
        :return: None

        """

        if not timeout:
            timeout = self.default_timeout

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

    def _check_vm_name(self, vm_name=None, testbed_id=None, alias=None):
        """Check if a VM name exists (by vm_name or by name starting with testbed_id and alias.

        :param vm_name: name of the VM
        :param testbed_id: testbed id for the VM (used to create the VM name if vm_name not provided)
        :param alias: alias of the VM (used to create the VM name name if vm_name not provided)
        :param snapshot: Name of the snapshot to check

        """
        if vm_name is None:
            vm_name = self._get_device_by_tbid_and_type(testbed_id, alias)
            if not vm_name:
                logger.error("Failed to find VM name starting with testbed_id '{}' and alias '{}'".format(
                              testbed_id, alias))
                return ""
        if not self._check_vm_existance(vm_name):
            logger.error("Failed to find VM '{}'".format(vm_name))
            return ""

        return vm_name

    def _snapshot_process(self, vm_name=None, testbed_id=None, alias=None, snapshot=None, action="create"):
        """Process a snapshot for a VM.

        :param vm_name: name of the VM
        :param testbed_id: testbed id for the VM (used to create the VM name if vm_name not provided)
        :param alias: alias of the VM (used to create the VM name if vm_name not provided)
        :param snapshot: Name of the snapshot to process
        :param action: Action to apply to the snapshot. Valid actions: create, delete, restore.

        """
        actions = {'create': 'virsh snapshot-create-as',
                   'delete': 'virsh snapshot-delete',
                   'restore': 'virsh snapshot-revert',
            }

        if action not in actions.keys():
            raise ValueError("'{}' is not a valid action. Only '{}' can be used.".format
                            (action, "', '".join(actions.keys())))

        found_vm_name = self._check_vm_name(vm_name=vm_name, testbed_id=testbed_id, alias=alias)

        if found_vm_name and snapshot is not None:
            cmd = "{cmd} '{domain}' '{snapshot}'".format(cmd=actions[action], domain=found_vm_name, snapshot=snapshot)

            self.execute("")
            output = self.execute(cmd, timeout=3600)
            if 'error: ' in output:
                logger.error("Failed to {} snapshot '{}' for VM '{}'".format(action, snapshot, found_vm_name))
                return False
            logger.info("Snapshot '{}' for VM '{}' {}d successfully".format(snapshot, found_vm_name, action))
            return True
        else:
            logger.error("VM name ({}) or snapshot ({}) not specified.".format(found_vm_name, snapshot))
            return False

    def snapshot_exists(self, vm_name=None, testbed_id=None, alias=None, snapshot=None):
        """Check if a specified snapshot exists for a VM.

        :param vm_name: name of the VM
        :param testbed_id: testbed id for the VM (used to create the domain name if domain not provided)
        :param alias: alias of the VM (used to create the domain name if domain not provided)
        :param snapshot: Name of the snapshot to check

        """
        found_vm_name = self._check_vm_name(vm_name=vm_name, testbed_id=testbed_id, alias=alias)

        if found_vm_name and snapshot is not None:
            cmd = "virsh snapshot-list --domain '{}' | grep -cP '^ ({}) +([0-9]{{2}}([0-9]{{2}})?[- :]){{6}}'"\
                   .format(found_vm_name, snapshot)
            self.execute("")
            output = self.execute(cmd)
            if str(output) == "1":
                return True
        return False

    def create_snapshot(self, vm_name=None, testbed_id=None, alias=None, snapshot=None, overwrite=True):
        """Create a snapshot for a VM.

        :param vm_name: name of the VM
        :param testbed_id: testbed id for the VM (used to create the VM name if vm_name not provided)
        :param alias: alias of the VM (used to create the VM name if vm_name not provided)
        :param snapshot: Name of the snapshot to be created.
        :param overwrite: Delete old snapshot (with the same name) before creating a new one. Default is True

        """
        self.go_to('sudo_state', 30)

        found_vm_name = self._check_vm_name(vm_name=vm_name, testbed_id=testbed_id, alias=alias)

        if found_vm_name:
            if overwrite is True:
                if self.snapshot_exists(vm_name=found_vm_name, snapshot=snapshot):
                    self._snapshot_process(vm_name=found_vm_name, snapshot=snapshot, action='delete')
            return self._snapshot_process(vm_name=found_vm_name, snapshot=snapshot, action='create')
        else:
            return False

    def delete_snapshot(self, vm_name=None, testbed_id=None, alias=None, snapshot=None):
        """Delete a snapshot for a VM.

        :param vm_name: name of the VM
        :param testbed_id: testbed id for the VM (used to create the VM name if vm_name not provided)
        :param alias: alias of the VM (used to create the VM name if vm_name not provided)
        :param snapshot: Name of the snapshot to be deleted.

        """
        self.go_to('sudo_state', 30)

        found_vm_name = self._check_vm_name(vm_name=vm_name, testbed_id=testbed_id, alias=alias)

        if self.snapshot_exists(vm_name=found_vm_name, snapshot=snapshot):
            return self._snapshot_process(vm_name=found_vm_name, snapshot=snapshot, action='delete')
        else:
            logger.error("Snapshot '{}' for VM '{}' not found.".format(snapshot, found_vm_name))
            return False

    def revert_to_snapshot(self, vm_name=None, testbed_id=None, alias=None, snapshot=None):
        """Restore a snapshot on a VM.

        :param vm_name: name of the VM
        :param testbed_id: testbed id for the VM (used to create the VM name if vm_name not provided)
        :param alias: alias of the VM (used to create the VM name if vm_name not provided)
        :param snapshot: Name of the snapshot to restore.

        """
        self.go_to('sudo_state', 30)

        found_vm_name = self._check_vm_name(vm_name=vm_name, testbed_id=testbed_id, alias=alias)

        if self.snapshot_exists(vm_name=found_vm_name, snapshot=snapshot):
            return self._snapshot_process(vm_name=found_vm_name, snapshot=snapshot, action='restore')
        else:
            logger.error("Snapshot '{}' for VM '{}' not found.".format(snapshot, found_vm_name))
            return False

    def create_vm(self, vm_type, alias, day0_config, build_path,
                  network_map, testbed_id, vm_name, mgmt_mac='', cache='none', size='2'):
        """Creates a VM with the specified parameters.

        :param vm_type: type of the VM. valid values are: FTD, FMC
        :param alias: alias of the VM
        :param day0_config: dictionary containing day0 configuration
        :param build_path: location of the qcow2 image,
                            e.g. 'http://10.83.65.25/Release/6.2.0-362/virtual-ngfw/'
                            'Cisco_Firepower_Threat_Defense_Virtual-6.2.0-362.qcow2'
        :param network_map:  list of VLANs given in the following order: mgmt_vlan,
                            diagnostic vlan, data vlan1, data vlan2, etc
                            e.g ['br-2999', 'br-2999', 'br-3590', 'br-3591']
        :param testbed_id: the ID of the testbed, e.g testbed_id = 'AST37'
        :param vm_name: name of VM
        :param mgmt_mac: mac address of the management interface
        :param cache: caching options, if value is '' (empty string) it will not take this param into account
        when creating wm. Default value is 'none'
        :param size: the size to be used when creating new vm, default 2

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        self.go_to('sudo_state', 30)
        sudo_prompt = self.sm.get_state('sudo_state').pattern

        # check if another VM with the same TB_id and type already exists
        existing_vm = self._get_device_by_tbid_and_type(testbed_id, alias)
        if existing_vm:
            if self._check_vm_existance(existing_vm):
                self.destroy(existing_vm)

        # deleting previous .qcow2 images that were used for the same vm
        image_location = '/images/{}/{}'.format(testbed_id, vm_type)
        existing_vm = '{}-{}*.qcow2'.format(testbed_id, alias)
        self.delete_file(image_location, existing_vm)

        # step1: create day0-config file: ~/automation/AST37/FTD/ftd1/day0-config
        # or ~/automation/AST37/FMC/fmc1/day0-config
        day0_location = '~/automation/{}/{}/{}'.format(testbed_id, vm_type, alias)
        day0_file = self._generate_day0_file(day0_config, day0_location)

        # step2: create VM.ISO file: /images/AST37/FTD/ftd1/FTD.iso or
        # /images/AST37/FMC/fmc1/FMC.iso
        iso_location = '/images/{}/{}/{}'.format(testbed_id, vm_type, alias)
        iso_file_name = vm_type + '.iso'
        iso_file = self._generate_iso(iso_file_name, iso_location, day0_file)

        # step3: download qcow2 file in /images/AST37/FTD/ or /images/AST37/FMC/
        image_file_name = self._download_image(build_path, image_location)

        # step4: copying downloaded .qcow2 file to a new file based on which the deployment is done
        index = len(image_location)+1
        renamed_file = image_file_name[:index] + vm_name + '.qcow2'
        vm_image_file_name = self._copy_file(image_file_name, renamed_file)

        # step5: run virt-install command
        logger.info("Creating VM {}".format(vm_name))
        ip = self._get_ip(day0_config)
        cmd_line = self._vm_install_command(vm_name, vm_type, iso_file,
                                            vm_image_file_name, network_map, ip, mgmt_mac, cache, size)

        self.spawn_id.sendline()
        d1 = Dialog([
            [sudo_prompt, 'sendline(virt-install {})'.format(cmd_line),
             None, True, True],
            ["Starting install...", None, None, True, True],
            ["Creating domain...", None, None,
             True, True],
            ["Domain creation completed.", None, None, False, False],
            ["ERROR", None, None, False, False],
        ])

        try:
            d1.process(self.spawn_id, timeout=3600)
        except Exception as e:
            logger.debug("{} installation failed".format(vm_name))
            logger.debug('Exception occured', e.value)
            raise Exception("{} installation failed".format(vm_name))

        # lookging for newly created VM
        self.spawn_id.sendline()
        time.sleep(10)
        vm = self._check_vm_existance(vm_name)

        assert vm is not None, 'Failed to find newly created VM'

    def _get_name(self, testbed_id, alias, image_build, day0_config):
        """Generates VM name automatically from testbed_id, alias, sw version and ip
        e.g.: vm_name = AST37-fmc1-6.2.1-145-192.168.0.186-rout

        :param testbed_id: the ID of the testbed, e.g testbed_id = 'AST37'
        :param alias: alias of the device
        :param image_build: location of the qcow2 image on server
        :param day0_config: dictionary containing day0 configuration
        :return: vm_name
        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')
        ip4mode = day0_config['"IPv4Mode"'].strip('"').lower()
        mode = day0_config['"FirewallMode"'].strip('"')[:4]
        # last_digits = re.findall('(\d+)$', ip)[0]
        version = re.search('-([\-.\d]+)(\.\w+)*$', image_build).group(1)
        if ip4mode == 'manual':
            ip = day0_config['"IPv4Addr"'].strip('"')
            return '{}-{}-{}-{}-{}'.format(testbed_id, alias, version, ip, mode)

        return '{}-{}-{}-{}'.format(testbed_id, alias, version, mode)

    def _get_device_by_tbid_and_type(self, testbed_id, alias):
        """Looks for all devices with a given type and testbed_id.

        :param testbed_id: ID of the testbed, e.g testbed_id = 'AST37'
        :param alias: alias of the VM
        :return: the vm_name of the first machine that matches the TBid
                and given alias

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        prefix = '{}-{}'.format(testbed_id, alias)

        cmd = "virsh list --all | grep --color=never '{}' | awk '{{print $2}}'".format(prefix)

        logger.info('Looking for existing VMs with prefix {}'.format(prefix))
        output = self.execute(cmd)
        lines = output.split('\r\n')
        for l in lines:
            if l.startswith(prefix):
                logger.info('Found VM {}.'.format(l))
                return l

        return ''

    def _check_vm_existance(self, vm_name):
        """Check if a vm already exists.

        :param vm_name: the name of the vm
        :return: vm name if exists, None otherwise

        """
        if not vm_name:
            return ''

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        cmd = "virsh list --all | grep --color=never '{}' | awk '{{print $2}}'".format(vm_name)
        
        logger.info('Looking for VM {}'.format(vm_name))
        output = self.execute(cmd)
        lines = output.split('\r\n')
        for l in lines:
            if l == vm_name:
                logger.info('VM {} FOUND.'.format(l))
                return l

        logger.info('VM {} NOT FOUND.'.format(vm_name))
        return ''

    def destroy(self, vm_name):
        """Deletes a vm by its given name.

        :param vm_name: name of the vm you want to delete

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        logger.info('Deleting VM "{}".'.format(vm_name))

        logger.info('Undefining VM "{}".'.format(vm_name))
        try:
            resp_undefine = self.execute('virsh undefine {}'.format(vm_name))
            if 'Domain {} has been undefined'.format(vm_name) in resp_undefine:
                logger.info('VM {} has been undefined'.format(vm_name))
        except Exception as e:
            logger.error('Error {} appeared while running virsh undefine command'.format(e))

        logger.info('Destroying VM "{}".'.format(vm_name))
        try:
            resp_destroy = self.execute('virsh destroy {}'.format(vm_name))
            if 'Domain {} destroyed'.format(vm_name) in resp_destroy:
                logger.info('VM {} has been destroyed'.format(vm_name))
        except Exception as e:
            logger.error('Error {} appeared while running virsh destroy command'.format(e))
            #raise RuntimeError('Error!!! Could not destroy VM {}'.format(vm_name))

        if not self._check_vm_existance(vm_name):
            logger.info('VM {} has been deleted'.format(vm_name))
        else:
            logger.info('VM {} has NOT been deleted'.format(vm_name))
            raise Exception('Could not delete vm {}'.format(vm_name))

    def delete_file(self, location, file):
        """Deletes a file from a given location.

        :param location: from where to delete the file
        :param file: name of the file to be deleted
        :return: None

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')
    
        self.go_to('sudo_state')
        sudo_prompt = self.sm.get_state('sudo_state').pattern
        file = '{}/{}'.format(location, file)
        cmd_lines = [[sudo_prompt, 'rm -v {}'.format(file), 60]]
        logger.info('Removing {} files'.format(file))
        try:
            self.expect_and_sendline(self.spawn_id, cmd_lines)
        except:
            raise Exception('An error happened when removing previous qcow2 files')

    def _generate_day0_file(self, day0_config, location):
        """Creates day0-config file in the given location:
        ~/automation/sja/FTD/1.

        :param day0_config: dictionary containing day0 information
        :param location: location where to create the day0_config file
        :return: day0_config file location
                e.g. ~/automation/sja/FTD/1/day0-config

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        self.go_to('sudo_state')
        sudo_prompt = self.sm.get_state('sudo_state').pattern

        cmd_lines = [[sudo_prompt, 'mkdir -p {}'.format(location), 30],
                     [sudo_prompt, 'echo {} > {}/day0-config'.format(day0_config, location), 30]
                    ]

        logger.info('Creating day0-config file located in {}'.format(location))
        file_name = '{}/day0-config'.format(location)
        try:
            self.expect_and_sendline(self.spawn_id, cmd_lines)
            return file_name
        except:
            raise Exception('An error happened while creating day0-config file')

    def _generate_iso(self, iso_file_name, location, day0_file):
        """ISO File generator.

        :param iso_file_name: name of iso file: FTD.iso
        :param location: where to create the iso file: /images/sja/FTD/1
        :param day0_file: name of day0 configuration file: automation/day0-config
        :return: the iso file location e.g. /images/sja/FTD/1/FTD.iso

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        self.go_to('sudo_state')
        sudo_prompt = self.sm.get_state('sudo_state').pattern

        cmd_lines = [[sudo_prompt, 'mkdir -p {}'.format(location), 30],
                     [sudo_prompt, '/usr/bin/mkisofs -r -o {}/{} {}'.
                         format(location, iso_file_name, day0_file), 50]
                    ]

        file_name = '{}/{}'.format(location, iso_file_name)
        logger.info('Creating {} iso file'.format(file_name))
        try:
            self.expect_and_sendline(self.spawn_id, cmd_lines)
            return file_name
        except:
            raise Exception('An error happened while creating {} file'.format(file_name))

    def _download_image(self, image_path, location):
        """Function used to download qcow2 image.

        :param image_path: http://10.83.65.25/Release/6.1.0-330/virtual-ngfw/
                            Cisco_Firepower_Threat_Defense_Virtual-6.1.0-330.qcow2
                          or tftp:////10.83.65.20/Release/6.1.0-330/virtual-ngfw/
                          Cisco_Firepower_Threat_Defense_Virtual-6.1.0-330.qcow2
        :param location: where to download the image e.g /images/AST37/FTD
        :return: downloaded file,
                e.g /images/AST37/FTD/Cisco_Firepower_Threat_Defense_Virtual-6.2.1-1171.qcow2

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        if image_path.startswith('http'):
            return self._download_http(image_path, location)
        elif image_path.startswith('tftp'):
            return self._download_tftp(image_path, location)
        else:
            raise RuntimeError("Unsupported download protocol")

    def _download_http(self, image_path, location):
        """Downloads an image via http.

        :param image_path: http://10.83.65.25/Release/6.1.0-330/virtual-ngfw/
                        Cisco_Firepower_Threat_Defense_Virtual-6.1.0-330.qcow2
        :param location: location where to download the image
                         e.g /images/AST37/FTD
        :return: downloaded file,
                 e.g /images/AST37/FTD/Cisco_Firepower_Threat_Defense_Virtual-6.2.1-1171.qcow2

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        self.go_to('sudo_state')
        sudo_prompt = self.sm.get_state('sudo_state').pattern
        is_file = False

        # check locally if image exists
        size_local = ''
        filename = image_path.split('/')[-1]
        cmd = "ls -l {} | grep --color=never {} | awk '{{print $5}}'".format(location, filename)

        for i in range(3):
            time.sleep(10)
            size = self.execute(cmd, 30)
            try:
                size_local = re.findall('\\n(\d+)', size)[0]
                logger.info('File found locally')
                break
            except IndexError:
                continue
        if not size_local:
            logger.info('File not found locally')

        # check if URL path is correct
        t = 0
        is_remote = False
        for i in range(3):
            time.sleep(t)
            t += 60
            try:
                conn = urllib.request.urlopen(image_path)
            except (urllib.error.URLError, urllib.error.HTTPError):
                logger.info('File not found on the remote server')
                continue
            else:
                logger.info('File found on the remote server')
                is_remote = True
                break

        if is_remote:
            if size_local:
                cmd = "wget {} --spider --server-response -O - 2>&1 | " \
                      "sed -ne '/Content-Length/{{s/.*: //;p}}'".format(image_path)
                size_server = self.execute(cmd)
                if size_server == size_local:
                    logger.info('The image already exists in {} location'.format(location))
                    is_file = True
                else:
                    logger.info('Local image size does not match the one on server')
                    logger.info('Removing the local image')
                    self.spawn_id.sendline('rm -v {}/{}'.format(location, filename))
                    self.spawn_id.expect('removed')
            else:
                logger.info('The image does not exist in location, will dowload it from server')

            for i in range(3):
                if not is_file:
                    logger.info('Loop#{}: Start downloading the new image'. format(i))
                    cmd = [["100%|The file is already fully retrieved",
                            "wget --progress dot:giga --continue -P {} {}".
                                format(location, image_path), 7200]]
                    try:
                        self.expect_and_sendline(self.spawn_id, cmd)
                        logger.info('Download successful')
                        is_file = True
                    except:
                        logger.debug('Download failed at #{} try ... retrying'.format(i))
                        continue
        else:
            raise Exception('Image URL not valid')

        assert is_file, 'Download image has failed'

        if is_file:
            filename = '{}/{}'.format(location, filename)
            logger.info('Make {} executable'.format(filename))
            cmd_line = [[sudo_prompt, 'chmod 777 {}'.format(filename), 20]]
            self.expect_and_sendline(self.spawn_id, cmd_line)
            return filename

    def _download_tftp(self, full_path, location):
        """Downloads an image via tftp.

        :param full_path: build image given with absolute path,
                        e.g. tftp://10.83.65.20/netboot/ims/Release/6.1.0-330/virtual-appliance/
                        VMWARE/Cisco_Firepower_NGIPSv_VMware-VI-6.1.0-330.ovf
        :param location: download destination
        :return: downloaded filename

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        self.go_to('sudo_state')
        sudo_prompt = self.sm.get_state('sudo_state').pattern

        server_ip = full_path.split('/')[2]
        filename_path = full_path.split(server_ip)[1]
        filename = os.path.basename(full_path)

        is_file = False

        tftp_cmd = 'tftp {} <<< "get {} {}/{}"'.format(server_ip, filename_path, location, filename)
        cmd_line = [["Received", tftp_cmd, 7200]]

        for i in range(3):
            if not is_file:
                logger.info('Loop#{}: Start downloading the new image'.format(i))
                try:
                    self.expect_and_sendline(self.spawn_id, cmd_line)
                    logger.info('Download successful')
                    is_file = True
                except:
                    logger.debug('Download failed at #{} try ...retrying'.format(i))
                    continue

        assert is_file, 'TFTP Download has failed'

        if is_file:
            filename = '{}/{}'.format(location, filename)
            logger.info('Make {} executable'.format(filename))
            cmd_line = [[sudo_prompt, 'chmod 777 {}'.format(filename), 20]]
            self.expect_and_sendline(self.spawn_id, cmd_line)
            return filename

    def _copy_file(self, file1, file2):
        """Copies one file to another.

        :param file1: source file
        :param file2: destination file
        :return: destination file with its absolute path

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        self.go_to('sudo_state')
        sudo_prompt = self.sm.get_state('sudo_state').pattern
        
        cmd_lines = [[sudo_prompt, 'cp -v {} {}'.format(file1, file2), 120]]
        logger.info('Copying {} to {} file'.format(file1, file2))
        try:
            self.expect_and_sendline(self.spawn_id, cmd_lines)
            return file2
        except:
            raise Exception('An error happened when copying the file')
       
    def _get_ip(self, day0_config):
        """Gets the ip of the VM.

        :param day0_config: dictionary containing day0 configuration
        :return: ip address

        """

        ip = day0_config['"IPv4Addr"'].strip('"')
        return ip

    def _get_port(self, ip):
        """Port generator.

        :param ip: the IP of the VM
        :return port number: last octet of an ip + 8000

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        l = re.findall('(\d+)$', ip)[0]
        port = 8000 + int(l)

        return port

    def _vm_install_command(self, vm_name, vm_type, iso_path, image_path,
                            network_map, ip, mgmt_mac='', cache='none', size='2'):
        """Runs the vm install command.

        :param vm_name: the name of the vm_name
        :param vm_type: FMC or FTD
        :param iso_path: the local path to iso file
        :param image_path: the local path to build image
        :param network_map:  list of VLANs given in the following order: mgmt_vlan,
                            diagnostic vlan, data vlan1, data vlan2, etc
        :param ip: the IP of the VM
        :param mgmt_mac:  mac address of the management interface
        :param cache: caching options, if value is '' (empty string) it will not take this param into account
        when creating wm. Default value is 'none'
        :param size: the size to be used when creating new vm, default 2
        :return: the installation options in one line

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        lines = []

        lines.append('--noautoconsole')
 
        port = self._get_port(ip)

        mgmt_vlan = network_map[0]

        network_map[0] = '{},mac={}'.format(mgmt_vlan, mgmt_mac) if mgmt_mac is not '' else '{}'.format(mgmt_vlan)

        network_lines = ['--network bridge:{},model=virtio '.format(v) for v in network_map]

        network_lines = ' '.join(network_lines)
        lines.append(network_lines)

        name_line = '--name {}'.format(vm_name)
        lines.append(name_line)

        static_lines1 = '--ram=8192 --cpu host --vcpus=4 --vnc --accelerate --virt-type=kvm --arch=x86_64'
        lines.append(static_lines1)

        cache_str = ',cache={}'.format(cache) if cache is not '' else ''
        if vm_type == 'FMC':
            bus = 'scsi'
        elif vm_type == 'FTD':
            bus = 'virtio'
        else:
            raise RuntimeError('unknown vm_type: {}'.format(vm_type))
        disk_line = '--disk path={},bus={},format=qcow2,size={}{}'. \
            format(image_path, bus, size, cache_str)
        lines.append(disk_line)

        static_lines2 = '--disk path={},format=iso,device=cdrom --console pty,target_type=serial --serial tcp,' \
                        'host=127.0.0.1:{},mode=bind,protocol=telnet --os-variant=generic --watchdog i6300esb,' \
                        'action=reset --import --force'.format(iso_path, port)
        lines.append(static_lines2)

        cmd_line = ' '.join(lines)

        return cmd_line

    def deploy_ftd(self, day0_config, mgmt_mac='', testbed_id='', network_map=None,
                   build_path='', image_folder='', server_ip='',
                   server_username='pxe', server_pass='pxe',
                   root_path='', http_root_path='', transfer_protocol='', vm_name='',
                   cache='none', size='2', alias='ftd'):
        """Method used to deploy a FTD.

        :param day0_config: dictionary containing day0 configuration
        :param mgmt_mac: mac address of the management interface
        :param testbed_id: the ID of the testbed, e.g testbed_id = 'AST37'
        :param network_map:  list of VLANs given in the following order: mgmt_vlan,
                            diagnostic vlan, data vlan1, data vlan2, etc
        :param build_path: external location of the qcow2 image
                            e.g. http://10.83.65.25/Release/6.2.0-362/virtual-ngfw/
                            Cisco_Firepower_Threat_Defense_Virtual-6.2.0-362.qcow2
        :param image_folder: optional; if provided, it uses the build located on the local build server
                            e.g. Release/6.0.0-1005
        :param server_ip: ip of build image server
        :param server_username: username used to connect to build server
        :param server_pass: password for server username
        :param root_path: root path from where to retrieve build images
        :param http_root_path: root path used for http wget
        :param transfer_protocol: protocol used to download image build
        :param vm_name: name of VM, optional
        :param cache: caching options, if value is '' (empty string) it will not take this param into account
                      when creating wm. Default value is 'none'
        :param size: the size to be used when creating new vm, default 2
        :param alias: an alias used for the vm; defaulted to 'ftd1'
        :return: a Vm() object type ftd

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        if network_map is None:
            raise RuntimeError('Please provide network map')

        if testbed_id is '':
            raise RuntimeError('Please provide testbed id')

        if not build_path:
            build_path = self.get_build_path(vm_type='ftd', image_folder=image_folder,
                                             server_ip=server_ip, root_path=root_path,
                                             protocol=transfer_protocol,
                                             server_username=server_username,
                                             server_pass=server_pass,
                                             http_root_path=http_root_path)

        if not vm_name:
            vm_name = self._get_name(testbed_id, alias, build_path, day0_config)

        logger.info('Deploying FTD VM "{}"'.format(vm_name))
        self.create_vm('FTD',
                       alias,
                       day0_config or InputConstants.fmc_day0_config,
                       build_path,
                       network_map,
                       testbed_id,
                       vm_name,
                       mgmt_mac,
                       cache,
                       size)

        ip = self._get_ip(day0_config)

        if self._check_vm_existance(vm_name):
            # send metrics to grafana
            publish_kick_metric('kvm.ftd.deploy', 1)

            return Vm(vm_name=vm_name, vm_type='ftd', ip=ip)

        return None

    def deploy_fmc(self, day0_config, mgmt_mac='', testbed_id='', network_map=None,
                   build_path='', image_folder='', server_ip='',
                   server_username='pxe', server_pass='pxe',
                   root_path='', http_root_path='', transfer_protocol='', vm_name='',
                   cache='', size='2', alias='fmc'):
        """Method used to deploy a FTD.

        :param day0_config: dictionary containing day0 configuration
        :param mgmt_mac: mac address of the management interface
        :param testbed_id: the ID of the testbed, e.g testbed_id = 'AST37'
        :param network_map:  list of VLANs given in the following order: mgmt_vlan,
                            diagnostic vlan, data vlan1, data vlan2, etc
        :param build_path: external location of qcow2 image
                          e.g. http://10.83.65.25/Release/6.2.0-362/virtual-ngfw/kvm/
                          Cisco_Firepower_Management_Center_Virtual-6.2.0-362.qcow2
        :param image_folder: optional; if provided, it uses the build located on the local build server
                            e.g. Release/6.0.0-1005
        :param server_ip: ip of build image server
        :param server_username: username used to connect to build server
        :param server_pass: password for server username
        :param root_path: root path from where to retrieve build images
        :param http_root_path: root path used for http wget
        :param transfer_protocol: protocol used to download image build
        :param vm_name: name of VM, optional
        :param cache: caching options, if value is '' (empty string) it will not take this param into account
                      when creating wm. Default value is 'none'
        :param size: the size to be used when creating new vm, default 2
        :param alias: an alias used for the vm; defaulted to 'fmc'
        :return: a Vm() object type fmc

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        if network_map is None:
            raise RuntimeError('Please provide network map')

        if testbed_id is '':
            raise RuntimeError('Please provide testbed id')

        if not build_path:
            build_path = self.get_build_path(vm_type='fmc', image_folder=image_folder,
                                             server_ip=server_ip, root_path=root_path,
                                             protocol=transfer_protocol,
                                             server_username=server_username,
                                             server_pass=server_pass,
                                             http_root_path=http_root_path)

        if not vm_name:
            vm_name = self._get_name(testbed_id, alias, build_path, day0_config)

        logger.info('Deploying FMC VM "{}"'.format(vm_name))
        self.create_vm('FMC',
                       alias,
                       day0_config or InputConstants.fmc_day0_config,
                       build_path,
                       network_map,
                       testbed_id,
                       vm_name,
                       mgmt_mac,
                       cache,
                       size)

        ip = self._get_ip(day0_config)
        if self._check_vm_existance(vm_name):
            # send metrics to grafana
            publish_kick_metric('kvm.fmc.deploy', 1)

            return Vm(vm_name=vm_name, vm_type='fmc', ip=ip)

        return None

    def get_build_path(self, vm_type, image_folder, server_ip, root_path, protocol,
                       server_username, server_pass, http_root_path=''):
        """Retrieves the qcow path based on VM type and image_folder.

        :param vm_type: the type of the VM. valid values: ftd, fmc
        :param image_folder: the path to the ovf image: Testing/6.1.0-268
        :param server_ip: the server where build images are stored
        :param root_path: local root path from where to retrieve build images
        :param protocol: transfer protocol: http or tftp
        :param server_username: username to connect to build server
        :param server_pass: password for server username
        :param http_root_path: optional; root path used by http wget
                              if not set, the hhtp root path is the image_folder
                              e.g. 'http://172.23.47.63//Release/6.1.0-330/virtual-appliance/kvm/
                                    Cisco_Firepower_Management_Center_Virtual-6.1.0-330.qcow2'
        :return: the qcow2 path of the image associated with these parameters

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        if vm_type == 'fmc':
            file = find_file_on_pxe('ls {}/{}/virtual-appliance/kvm/'
                                    'Cisco_Firepower_Management_Center_Virtual-*.qcow2'.
                                    format(root_path, image_folder), server_ip,
                                    server_username, server_pass)
        elif vm_type == 'ftd':
            file = find_file_on_pxe('ls {}/{}/virtual-ngfw/'
                                    'Cisco_Firepower_Threat_Defense_Virtual-*.qcow2'.
                                    format(root_path, image_folder), server_ip,
                                    server_username, server_pass)
        else:
            raise RuntimeError('unknown vm_type: {}'.format(vm_type))

        assert file.startswith(root_path)
        file = file[len(root_path):]

        logger.debug('found qcow2 url: http://{}/{}/{}'.format(server_ip, http_root_path, file))
        return '{}://{}/{}/{}'.format(protocol, server_ip, http_root_path, file)

    def restart(self, vm_name):
        """Restarts the VM from KVM.

        :param: name of vm to be restarted
        :return: None

        """

        if not self.kvm_line:
            raise NotImplementedError('method not applicable for VM')

        sudo_prompt = self.sm.get_state('sudo_state').pattern
        logger.info("Powering on VM {}".format(vm_name))

        d1 = Dialog([
            [sudo_prompt, 'sendline(virsh --connect qemu:///system start {})'.format(self.vm_name),
                None, False, False],
            ['Domain {} started'.format(vm_name), None, None, False, False],
            ["error: Domain is already active", None, None, False, False],
            ["ERROR", None, None, False, False],
        ])
        try:
            d1.process(self.spawn_id, timeout=120)
            logger.debug("VM {} started".format(vm_name))
        except Exception as e:
            logger.debug("Could not start VM {}".format(vm_name))
            raise Exception("Could not start VM {}".format(vm_name))
    
    def run_as_root(self, cmd, timeout=None):
        """Run a command as root: become a root, run the command, exit root.

        :param cmd: command to be executed
        :param timeout: timeout for executing the command

        """

        if not timeout:
            timeout = self.default_timeout

        # get current prompt
        current_state = self.sm.current_state
        current_prompt = self.sm.get_state(current_state).pattern
        # become a root
        self.go_to('sudo_state', timeout=timeout)
        # execute command
        self.execute(cmd=cmd, timeout=timeout)
        # exit root
        self.go_to(current_state)


class Vm():

    def __init__(self, vm_name, vm_type, ip, port=22, username='admin',
                 login_password='Admin123',
                 sudo_password='Admin123'):
        """Constructor of Vm.

        :param vm_name: name of the vm
                        e.g. 'AST37-ftd1-6.1.0-330-rout'
        :param vm_type: the type of the vm: "ftd" or "fmc"
        :param ip: the ip of the VM
        :param port: the NAT port if forwarded, if not set, use port 22 for ssh
        :param username: user name for login
        :param login_password: password for login
        :param sudo_password: password for root

        """

        self.ip = ip
        self.port = port
        self.vm_name = vm_name
        self.vm_type = vm_type
        self.username = username
        self.login_password = login_password
        self.sudo_password = sudo_password

        from .vm.constants import VmConstants
        VmConstants.username = username
        VmConstants.login_password = login_password
        VmConstants.sudo_password = sudo_password

        from .vm.statemachine import VmStatemachine
        self.sm = VmStatemachine()

        # set timeout
        self.set_default_timeout(DEFAULT_TIMEOUT)

        # send metrics to grafana
        publish_kick_metric('kvm.{}.init'.format(vm_type.lower()), 1)

    def set_default_timeout(self, timeout):
        """Change default timeout to given value.

        :param: default value for timeout

        """

        logger.debug('setting line default timeout to {}'.format(timeout))
        self.default_timeout = timeout

    def telnet_console_with_credential(self, ip, port, username='admin', password='Admin123'):
        """Connect serial console via telnet with credentials.

        :param ip: ip of the Vm
        :param port: forwarded port if NAT is used or port 23 for telnet
        :param username: login username
        :param password: login password
        :return telnet_line: a KvmLine object

        """

        spawn_id = Spawn('telnet {} {}'.format(ip, port))
        spawn_id.expect("Connected to.*Escape character is '\^\]'\..")
        spawn_id.sendline()
        spawn_id.expect(".*login: ")
        spawn_id.sendline(username)
        spawn_id.expect("Password: ")
        spawn_id.sendline(password)
        spawn_id.expect("Last login")
        spawn_id.sendline()
        telnet_line = KvmLine(spawn_id=spawn_id,
                              sm=self.sm,
                              type='telnet',
                              kvm_line=False)

        return telnet_line

    def ssh(self, ip='', port='', username='', password='', timeout=None):
        """Setup a ssh connection on a vm.

        :param ip: VM IP
        :param port: sshport
        :param username: username for login
        :param password: password for login
        :param timeout: timout for ssh connection
        :return: ssh_line

        """

        if not timeout:
            timeout = self.default_timeout
        ip = ip or self.ip
        port = port or self.port
        username = username or self.username
        password = password or self.login_password

        self.spawn_id = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -l {} -p {} {} '.
                              format(username, port, ip))

        ctx = AttributeDict({'password': password})

        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['(p|P)assword:', 'sendline_ctx(password)', None, True, False],
            ['Password OK', 'sendline()', None, False, False],
            ['[.*>#$] ', 'sendline()', None, False, False],
        ])

        d1.process(self.spawn_id, context=ctx, timeout=timeout)
        self.spawn_id.sendline()
        ssh_line = KvmLine(spawn_id=self.spawn_id, sm=self.sm, type='ssh', kvm_line=False)

        logger.debug("Done: connection created by ssh {} {}".format(ip, port))
        return ssh_line

    def wait_for_ssh(self, ip='', port='', username="", password="", timeout=7200):
        """Waits up to 1 hour for ssh connection to be available; checks
        connection every 60 seconds.

        :param ip: VM IP
        :param port: ssh port
        :param username: username for login
        :param password: password for login
        :param timeout: time to wait for ssh to be available (seconds)
        :return: True if connection available, False otherwise

        """
        
        ip = ip or self.ip
        port = port or self.port
        username = username or self.username
        password = password or self.login_password
        vm_line = None
        start_time = time.time()
        logger.info('Waiting for ssh to be available')
        while start_time + timeout > time.time():
            vm_line = None
            try:
                vm_line = self.ssh(ip=ip, port=port, username=username,
                                   password=password, timeout=60)
                if vm_line:
                    vm_line.disconnect()
                    break
            except Exception as e:
                current_time = time.time()
                logger.info('ssh not available after {}'.format(_time_message(start_time, current_time)))
                logger.info('Error message: {}'.format(str(e)))
                time.sleep(60)
        if vm_line is not None:
            logger.info('Vm ssh available ')
            return True
        else:
            end_time = time.time()
            logger.error('Vm ssh not available after {} '.format(_time_message(start_time, end_time)))
            raise RuntimeError('vm ssh not available')

    def wait_for_fmc_webInterface(self, ip='', port=443, timeout=7200):
        """Waits for Fmc webUI interface to be available. It will check every
        minute for one hour.

        :param ip: ip of the VM
        :param port: port for https service, default is 443
        :param timeout: time to wait for webinterface to be available (seconds)
        :return: True if connection available, False otherwise

        """

        ip = ip or self.ip
        url = 'https://{}:{}'.format(ip, port)
        is_available = False
        start_time = time.time()
        logger.info('Waiting for FMC (DC) web interface to be available')
        while start_time + timeout > time.time():
            try:
                response = requests.get(url, verify=False)
                response.raise_for_status()
            except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
                current_time = time.time()
                logger.info('FMC (DC) web interface not available after {}'.
                            format(_time_message(start_time, current_time)))
                logger.info('Error message: {}'.format(e))
                time.sleep(60)
                continue
            else:
                logger.info('FMC (DC) web interface available')
                is_available = True
                break
        if is_available:
            logger.info('FMC web interface available, sleep 3 more minutes '
                        'to allow system initialization to complete')
            time.sleep(180)
        else:
            end_time = time.time()
            logger.error('FMC web interface not available after {} '. format(_time_message(start_time, end_time)))
            raise RuntimeError('FMC web interface not available')
        return is_available

    def log_checks(self,  ip='', port='', username='', password='',
                   list_files=['/var/log/messages', '/var/log/firstboot*'],
                   search_strings=['fatal', 'error'],
                   exclude_strings=[], timeout=300):
        """Wrapper function to Get logs for FTD.

        :param ip: ip of the Vm
        :param port: port for ssh connection
        :param username: for ssh login
        :param password: for ssh login
        :param list_files: List of file paths for files to search in
        :param search_strings: List of keywords to be searched in the logs
        :param exclude_strings: List of keywords to be excluded in the logs
        :param timeout: The number for seconds to wait for log retrieval
                        e.g list_files = ['/var/log/boot_1341232','/var/log/boot_*']
                        search_strings = ['fatal','error', 'crash']
                        exclude_strings = ['ssl_flow_errors', 'firstboot.S09']

        """

        ip = ip or self.ip
        port = port or self.port
        username = username or self.username
        password = password or self.login_password
        sudo_prompt = '\r\n(root@.*):(.*)|~#'
        
        logger.debug('Looking for errors in boot logs on {} device'.format(self.vm_name))
        device_line = self.ssh(ip=ip, port=port, username=username,
                               password=password, timeout=120)
        device_line.go_to('sudo_state')

        grep_command_list = []
        exclude_line = ''

        if exclude_strings:
            exclude_cmd = ['| grep -v {}'.format(string) for string in exclude_strings]
            exclude_line = ''.join(exclude_cmd)

        if list_files and search_strings:
            for file in list_files:
                for string in search_strings:
                    grep_command = "grep -Ii {} {} {}".format(string, file, exclude_line)
                    grep_command_list.append(grep_command)
        try:
            output_log = device_line.execute_lines_total(
                ("\n".join(grep_command_list)), timeout=timeout)
        except:
            output_log = "Log retrieval command timed out"

        logger.info("""
            ***********************************************************

            Logs for the requested files are : -

            {}

            ***********************************************************
            """.format(output_log))

        device_line.disconnect()

    def check_version(self, version, build, ip='', port='', username='', password='', timeout=None):
        """Checks if a given build and version is installed on vFmc.

        :param version: expected version
        :param build: expected build
        :param ip: ip of the Vm
        :param port: port for ssh connection
        :param username: for ssh login
        :param password: for ssh login
        :param timeout:  timeout for executing command
        :return: True if version and build match the given ones, error otherwise

        """

        if not timeout:
            timeout = self.default_timeout

        ip = ip or self.ip
        port = port or self.port
        username = username or self.username
        password = password or self.login_password

        l = self.get_build_and_version(ip=ip, port=port, username=username,
                                       password=password, timeout=timeout)
        current_build = l[0]
        current_version = l[1]
        if current_version == version and current_build == build:
            logger.info('The version and build match the given ones')
            return True
        else:
            logger.error('Version and build dont match, the device has version {} and '
                         'build {}'.format(current_version, current_build))
            return False

    def get_build_and_version(self, ip='', port='', username='', password='', timeout=None):
        """Read the build and version.

        :param ip: ip of the Vm
        :param port: port for ssh connection
        :param username: username for ssh login
        :param password: password for ssh login
        :param timeout: timeout for executing command
        :return: a list with two elements: current build and current version

        """

        if not timeout:
            timeout = self.default_timeout

        ip = ip or self.ip
        port = port or self.port
        username = username or self.username
        password = password or self.login_password
        for _ in range(3):
            vm_line = None
            try:
                vm_line = self.ssh(ip, port, username, password, 120)
                time.sleep(10)
                break
            except:
                pass
                time.sleep(10)

        if vm_line is not None:
            try:
                if self.vm_type.lower() == 'ftd':
                    response = vm_line.execute(cmd='show version', timeout=timeout)
                    current_build = re.findall(r'Build\s(\d+)', response)[0]
                    current_version = re.findall(r'(Version\s){1}([0-9.]+\d)', str(response))[0][1]
                elif self.vm_type.lower() == 'fmc':
                    response = vm_line.execute(cmd='cat /etc/sf/ims.conf | grep SWBUILD', timeout=timeout)
                    current_build = re.findall('SWBUILD=(\d+)', response)[0]
                    response = vm_line.execute(cmd='cat /etc/sf/ims.conf | grep SWVERSION', timeout=timeout)
                    current_version = re.findall(r'(SWVERSION=){1}([0-9.]+\d)', str(response))[0][1]
                vm_line.disconnect()
            except:
                raise RuntimeError('Could not extract sw build and version')
            logger.info('Current version: {}'.format(current_version))
            logger.info('Current build: {}'.format(current_build))

        else:
            raise RuntimeError("Could not open SSH session on device")
        if current_build and current_version:
            return [current_build, current_version]


def _time_message(start_time, end_time):
    """Method used to display the elapsed time between two given periods
    :param start_time: start time
    :param end_time: end time
    :return: elapsed time in hours minutes and seconds as a message

    """
    l_time = str(datetime.timedelta(seconds=round(end_time - start_time))).split(':')
    message = '{} {} {} '.format(l_time[0] + 'h ' if l_time[0] is not '0' else '',
                                 l_time[1] + 'm ' if l_time[1] is not '00' else '',
                                 l_time[2] + 's' if l_time[2] is not '00' else '')
    return message

