"""Library to load new images on a FMC Series3.

We require a file server to be co-located with the device. This file
server has both the img files mounted.  Image downloading is via http.

The file server is a PXE server in each site.

"""
import re
import datetime
import logging
import subprocess
import time

logger = logging.getLogger(__name__)

from unicon.eal.expect import Spawn, TimeoutError
from unicon.eal.dialogs import Dialog
from ...series3.actions.webserver import Webserver
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


DUT_DIR_TMP = '/tmp'
DUT_DIR_BOOT = '/boot'
DUT_DIR_ETC = '/etc'
DUT_LILO_TMPL_FILE = 'lilo.conf'
DUT_LILO_FILE = 'lilo.conf.atf'
DUT_LILO_TMPL_PATH = '{}/{}'.format(DUT_DIR_ETC, DUT_LILO_TMPL_FILE)
DUT_LILO_TMP_PATH = '{}/{}'.format(DUT_DIR_TMP, DUT_LILO_FILE)
DUT_LILO_PATH = '{}/{}'.format(DUT_DIR_ETC, DUT_LILO_FILE)
MAX_TIME_INSTALL = 7200
DEFAULT_TIMEOUT = 10
MAX_RETRY_COUNT = 3
SSH_DEFAULT_TIMEOUT = 90


class Series3Fmc(Fmc):
    def __init__(self, hostname='firepower', login_username='admin',
                 login_password=KickConsts.DEFAULT_PASSWORD,
                 sudo_password=KickConsts.DEFAULT_PASSWORD, *args,
                 **kwargs):
        """Constructor for FMC.

        :param hostname: hostname of the device or fqdn
        :param login_username: user credentials
        :param login_password: device login password with user name 'admin'
        :param sudo_password: device sudo password for 'root'

        """

        super().__init__(hostname, login_username,
                         login_password,
                         sudo_password, *args, **kwargs)
        publish_kick_metric('device.series3fmc.init', 1)

        self.line_class = Series3FmcLine

    def ssh_vty(self, ip, port, username='admin', password='Admin123', timeout=None,
                line_type='ssh', rsa_key=None):
        """
        Set up an ssh connection to device's interface.

        This goes into device's ip address, not console.

         :param ip: ip address of terminal server
         :param port: port of device on terminal server
         :param username: usually "admin"
         :param password: usually "Admin123"
         :param timeout: in seconds
         :param line_type: ssh line type
         :param rsa_key: identity file (full path)
         :return: a line object (where users can call execute(), for example)

         """
        publish_kick_metric('device.series3fmc.ssh_vty', 1)
        if not timeout:
            timeout = self.default_timeout

        from .constants import Series3Constants
        Series3Constants.uut_ssh_ip = ip
        Series3Constants.uut_ssh_port = port

        if rsa_key:
            resp = subprocess.getoutput('chmod 400 {}'.format(rsa_key))
            if 'No such file or directory' in resp:
                raise RuntimeError('The identity file {} you provided does not exist'.format(rsa_key))
            spawn = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                          '-i {} -l {} -p {} {} \n'.format(rsa_key, username, port, ip))
        else:
            spawn = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                          '-l {} -p {} {} \n'.format(username, port, ip))

        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['(p|P)assword:', 'sendline({})'.format(password),
             None, False, False],
        ])
        try:
            d1.process(spawn, timeout=timeout)
        # spawn.sendline()
        except TimeoutError:
            pass

        ssh_line = Series3FmcLine(spawn, self.sm, 'ssh_vty', timeout=timeout)

        return ssh_line


class Series3FmcLine(FmcLine):
    def __init__(self, spawn, sm, type, timeout=None):
        """Constructor for series3fmc line A

        :param spawn: spawn of the line
        :param sm: object of statemachine
        :param type: line type, e.g. 'ssh', 'telnet'
        :return: None

        """
        self.spawn_id = spawn
        self.sm = sm
        self.type = type
        self.set_default_timeout(DEFAULT_TIMEOUT)
        try:
            sm.go_to('any', spawn, timeout=timeout)
        except:
            # Catch the case fmc is back from installation
            # Does not have the stable state
            pass

    # the following functions are for device baselining. This only works on
    # a ssh connection.
    def generate_config_file(self):
        """Compose the config file. Copy the config file to
        self.http_dir_for_build on Webserver. Create symbolic link to the iso
        image on Webserver.

        :return: None

        """

        server = Webserver(hostname=self.scp_hostname,
                           login_username=self.scp_username,
                           login_password=self.scp_password)
        dev = server.ssh_vty(self.scp_server)
        output = dev.execute('mkdir -p -m 775 {}'.format(self.http_dir_for_build))
        result = re.search('File exists', output)
        if result is not None:
            logger.info('File exists and it will be deleted ...')
            dev.execute('rm -rf {}'.format(self.http_dir_for_build))
            dev.execute('mkdir -p -m 775 {}'.format(self.http_dir_for_build))
        dev.execute('ln -s {}/{} {}'.format(self.http_dir_root,
                                            self.iso_image_path, self.http_dir_for_build))
        config_file_content = """TRANS=httpsrv
SRV={}
IPCONF=dhcp
REPLACE_TFTP_BOOT_FILE=Yes
TFTPSERVER={}
FN={}
TARGET_ARCH={}
""".format(self.http_server,
           self.http_server,
           self.iso_image_path,
           self.arch)
        dev.execute('echo "{}" > {}'.format(config_file_content, self.config_path))
        output_ls = dev.execute('ls {}'.format(self.config_path))
        logger.info(output_ls)
        output_cat = dev.execute('cat {}'.format(self.config_path))
        logger.info(output_cat)
        output = dev.execute('wget -O - http://{}:{}/{}'.format(self.http_server, self.http_port, self.config_file_url))
        assert 'TRANS=httpsrv' in output, \
                '\nFailed to access the boot configuration file.\nVerify http_dir_tmp is correct.\nhttp://{}:{}/{}'. \
                format(self.http_server, self.http_port, self.config_file_url)
        dev.disconnect()

    def scp_file_to_local(self, local_dir, sftp_ip, sftp_port,
                          username, password, remote_path):
        """Scp a remote file to DUT.

        :param local_dir: local directory as the destination directory on DUT
        :param sftp_ip: remote sftp server ip address
        :param sftp_port: remote sftp server port
        :param username: username to login to sftp server
        :param password: password to login to sftp server
        :param remote_path: file path with filename on remote sftp server
        :return: None

        """

        filename = remote_path.split('/')[-1]
        self.execute('rm -f {}/{}'.format(local_dir, filename))
        self.spawn_id.sendline('scp -P {} {}@{}:{} {}'.format(sftp_port,
                                                              username, sftp_ip, remote_path, local_dir))
        current_prompt = self.sm.get_state(self.sm.current_state).pattern
        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['[p|P]assword:', 'sendline({})'.format(password), None, True, False],
            [current_prompt, 'sendline()', None, False, False],
        ])
        d1.process(self.spawn_id, timeout=300)
        self.execute('pwd', timeout=180)
        self.execute('ls -ltr {}/{}'.format(local_dir, filename),timeout=120)
        output = self.execute('ls -ltr {}/{}'.format(local_dir, filename),
                              timeout=20)
        logger.info(output)
        full_filename = output.split('/')[-1]
        logger.info('filename={}, full_filename={}'.format(filename,
                                                           full_filename))
        assert ('No such file or directory' not in output) and \
               (filename[:-1] in full_filename), \
            'Failed to copy {}'.format(filename)
        return full_filename

    def copy_bz_usb_files_setup_lilo_to_install(self):
        """Scp bz and usb image files from remote sftp server to DUT. Configure
        lilo file on DUT. Execute run_lilo_and_depmod. Mount usb. Reboot to
        install.

        :return: None

        """

        # Scp bz and usb files
        self.go_to('sudo_state')

        full_bz_filename = self.scp_file_to_local(local_dir=DUT_DIR_TMP,
                                                  sftp_ip=self.scp_server, sftp_port=self.scp_port,
                                                  username=self.scp_username, password=self.scp_password,
                                                  remote_path=self.bz_image_path)
        logger.info('=== Extract bz_filename from {}: {}'.format(self.bz_image_path,
                                                                 full_bz_filename))
        full_usb_filename = self.scp_file_to_local(local_dir=DUT_DIR_TMP,
                                                   sftp_ip=self.scp_server, sftp_port=self.scp_port,
                                                   username=self.scp_username, password=self.scp_password,
                                                   remote_path=self.usb_image_path)
        logger.info('=== Extract usb_filename from {}: '
                    '{}'.format(self.usb_image_path,
                                full_usb_filename))
        cmd = 'mv {}/{} {}'.format(DUT_DIR_TMP,
                                   full_bz_filename,
                                   DUT_DIR_BOOT)
        self.execute_only(cmd=cmd)

        cmd = 'mv {}/{} {}'.format(DUT_DIR_TMP,
                                   full_usb_filename,
                                   DUT_DIR_BOOT)
        self.execute_only(cmd=cmd)

        # Generate lilo file
        cmd = "cat {} | perl -pe 's/default=[^\n]+/default=INSTALL/g'" \
              " > {}".format(DUT_LILO_TMPL_PATH, DUT_LILO_TMP_PATH)
        self.execute_only(cmd=cmd)

        lilo_append_lines = """
image=/boot/{}
      label=INSTALL
      read-only
      initrd=/boot/{}
      append="root=/dev/ram0 rw PRESERVE_DATA=Yes choicedevice=eth0 INTEGCONF={}/{}"
""".format(full_bz_filename, full_usb_filename, self.http_server, self.config_file_url)
        cmd = '''echo '{}' >> {}'''.format(lilo_append_lines,
                                           DUT_LILO_TMP_PATH)
        self.execute_only(cmd=cmd)

        self.execute('cat {}'.format(DUT_LILO_TMP_PATH))
        self.execute('mv {} {}'.format(DUT_LILO_TMP_PATH, DUT_LILO_PATH))
        logger.info('=== Generated lilo file [{}]\n{}\n'.format(DUT_LILO_PATH,
                                                                lilo_append_lines))
        logger.info('=== run_lilo_and_depmod')
        cmd = '/bin/bash -c "source /etc/lilo.d/functions.lilo; ' \
              'run_lilo_and_depmod"'
        self.execute_only(cmd=cmd, timeout=120)

        self.execute('mount LABEL=SFKEYFOB /usb', 60)
        self.execute('lilo -P ignore -C /etc/lilo.conf.atf', 60)
        self.execute('lilo -q 2>&1', 60)
        logger.info('=== System will reboot!')
        self.spawn_id.sendline('reboot')

    def confirm_device_rebooted(self):
        """Confirm device is rebooting by executing command pwd.

        If device is not reachable, exit. Wait until device is not
        reachable.

        """

        count = 0
        wait_time = 60
        total_count = 20
        while count < total_count:
            try:
                self.execute('pwd', 5)
                time.sleep(wait_time)
                count += 1
                logger.info('=== Wait {} seconds for device to reboot ...'.format(wait_time))
                time.sleep(wait_time)
            except:
                logger.info('=== The Appliance at {} is Rebooting.'.format(self.uut_ip))
                self.disconnect()
                break
        if count >= total_count:
            msg = '=== The appliance {} does not appear to have gone down' \
                  ' for reboot. Installer has failed'.format(self.uut_ip)
            logger.info(msg)
            raise RuntimeError(msg)

    def reconnect_and_process_dialog(self, device_reconnect_count, wait_time,
                                     dialog_timeout, start_time, dialog_name, dialog, initial_string=""):
        """Reconnect to the device. Process the dialog. Device could reboot
        multiple times. Wait until the device can be accessed and dialog is
        processed.

        :param device_reconnect_count: initial device reconnect count
        :param wait_time: wait time in each loop
        :param dialog_timeout: dialog timeout
        :param start_time: installation start time used to calculate elapsed_time
        :param dialog_name: dialog name used for logging info
        :param dialog: object of Dialog to be processed for device configuration
        :param initial_string: initial string sent to device to trigger dialog
        :return device_reconnect_count: incremented device reconnect count

        """

        count = 0
        total_count = 20
        from .constants import Series3Constants
        now = datetime.datetime.now()
        elapsed_time = (now - start_time).total_seconds()
        if elapsed_time < self.installation_timeout:
            logger.info('=== Sleep for {} seconds'.format(wait_time))
        while count < total_count:
            try:
                logger.info('=== Begin: {}'.format(dialog_name))
                time.sleep(wait_time)

                initial_password = self.sm.patterns.default_password

                tmp_fmc = self.fmc
                tmp_uut_ip = self.uut_ip
                tmp_version_build = self.version_build

                conn = self.fmc.ssh_vty(ip=Series3Constants.uut_ssh_ip,
                                        port=Series3Constants.uut_ssh_port,
                                        password=initial_password,
                                        timeout=self.ssh_timeout)

                self.spawn_id = conn.spawn_id

                self.fmc = tmp_fmc
                self.uut_ip = tmp_uut_ip
                self.version_build = tmp_version_build

                device_reconnect_count += 1
                logger.info('Device reconnected, {} times'.format(device_reconnect_count))
                if initial_string is not "":
                    self.spawn_id.sendline(initial_string)
                self.spawn_id.sendline()
                dialog.process(self.spawn_id, timeout=dialog_timeout)
                logger.info('=== End: {}'.format(dialog_name))
                time.sleep(5)
                return device_reconnect_count
            except:
                now = datetime.datetime.now()
                elapsed_time = (now - start_time).total_seconds()
                logger.info('=== Device is not ready, elapsed_time={}, '
                            'wait for {} seconds ...'.format(elapsed_time, wait_time))
                pass

    def poll_device_and_configure(self):
        """Poll device: wait for device to be up.

        :return: None

        """
        httpsd = '/usr/bin/httpsd -D FOREGROUND'
        d1 = Dialog([
            [httpsd, None, None, False, False],
            ])

        start_time = datetime.datetime.now()
        self.reconnect_and_process_dialog(
            device_reconnect_count=0,
            wait_time=600,
            dialog_timeout=30,
            start_time=start_time,
            dialog_name='wait for device to be ready',
            dialog=d1,
            initial_string='ps aux | grep www')

    def series3fmc_baseline(self, fmc, http_server, scp_server, scp_port,
                            scp_username, scp_password, scp_hostname,
                            version_build, iso_image_path,
                            uut_ip, uut_netmask, uut_gateway, dns_server,
                            hostname='firepower',
                            search_domains='cisco.com',
                            http_dir_root='/var/www',
                            http_dir_tmp='iso/tmp_dev',
                            scp_dir_root='/nfs/netboot/ims/Release',
                            bz_image='bzImage*',
                            usb_image='usb-ramdisk*',
                            arch='x86_64',
                            console=False,
                            uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                            timeout=None, change_password=True, http_port='80'):
        """Install FMC iso image on Series 3 device via http.

        :param fmc: object of Series3fmc for reconnecting the device
        :param http_server: HTTP Server IP Address, e.g. '10.89.23.80'
                            must use the same http server as the scp server
        :param http_port: HTTP server port, e.g. '80'
        :param scp_server: SCP Server IP Address, e.g. '10.89.23.80'
        :param scp_port: SCP Server Port, e.g. '22'
        :param scp_username: SCP Username
        :param scp_password: SCP Password
        :param scp_hostname: SCP Hostname
        :param version_build: e.g. '6.2.1-1366'
        :param iso_image_path: FMC image path on HTTP server
                                e.g. '/netboot/ims/Development/6.2.1-1366/iso/Sourcefire_Defense_Center_S3-6.2.1-1366-Restore.iso'
        :param uut_ip: Device IP Address
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param hostname: hostname to be set, e.g. 'BATIT-3D8130-1-AST'
        :param search_domains: search domains delimited by comma,
                                defaulted to 'cisco.com'
        :param http_dir_root: absolute path of the http root
                                e.g. '/var/www'
        :param http_dir_tmp: the temp dir under http_dir_root for version_build
                            and the config file, e.g. 'iso/tmp_dev'
        :param scp_dir_root: absolute path of the dir for version_build
                            e.g. '/nfs/netboot/ims/Release' or '/nfs/netboot/ims/Development'
        :param bz_image: bz image has to be installed on DUT, which is copied
                        from the scp_server, defaulted to 'bzImage*'
        :param usb_image: usb image has to be installed on DUT, which is copied
                            from the scp_server, defaulted to 'usb-ramdisk*'
        :param arch: arch type, defaulted to 'x86_64'
        :param console: set to True if the device is accessed through its console;
                        defaulted to False
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param change_password: Flag to change the password after baseline
        :return: None

        """
        publish_kick_metric('device.series3fmc.baseline', 1)
        # set baseline timeout
        self.set_installation_timeouts(timeout)
        # Define attributes and variables
        self.fmc = fmc
        self.http_server = http_server
        self.http_port = http_port
        self.scp_server = scp_server
        self.scp_port = scp_port
        self.scp_username = scp_username
        self.scp_password = scp_password
        self.scp_hostname = scp_hostname
        self.version_build = version_build
        self.iso_image_path = iso_image_path
        self.iso_file = iso_image_path.split('/')[-1]
        self.uut_ip = uut_ip
        self.uut_netmask = uut_netmask
        self.uut_gateway = uut_gateway
        self.uut_ip6 = uut_ip6
        self.uut_prefix = uut_prefix
        self.uut_gateway6 = uut_gateway6
        self.dns_server = dns_server
        self.hostname = hostname
        self.search_domains = search_domains
        self.http_dir_root = http_dir_root
        self.http_dir_tmp = http_dir_tmp
        self.http_dir_for_build = '{}/{}/{}'.format(self.http_dir_root,
                                                    self.http_dir_tmp, self.version_build)
        self.config_file = '{}.config'.format(self.iso_file.strip('.iso'))
        self.config_path = '{}/{}'.format(self.http_dir_for_build, self.config_file)
        self.config_file_url = '{}/{}/{}'.format(self.http_dir_tmp, self.version_build, self.config_file)
        self.scp_dir_root = scp_dir_root
        self.bz_image = bz_image
        self.usb_image = usb_image
        self.arch = arch
        self.bz_image_path = '{}/{}/os/{}/boot/{}'.format(self.scp_dir_root,
                                                          self.version_build,
                                                          self.arch, self.bz_image)
        self.usb_image_path = '{}/{}/os/{}/ramdisks/{}'.format(self.scp_dir_root,
                                                               self.version_build,
                                                               self.arch, self.usb_image)
        self.console = console

        logger.info('=== Generate config file on the http server ...')
        self.generate_config_file()

        logger.info('=== Copy bz and usb files to dut ...')
        logger.info('=== Generate lilo file on dut ...')
        self.go_to('sudo_state')
        self.copy_bz_usb_files_setup_lilo_to_install()

        if not self.console:
            logger.info('=== Confirm device is rebooted ...')
            self.confirm_device_rebooted()

            logger.info('=== Wait for device to be up and configure device ...')
            self.poll_device_and_configure()
        else:
            logger.info('=== Console connection available, wait for login prompt ...')
            d = Dialog([
                ['login:', 'sendline({})'.format(self.sm.patterns.login_username),
                 None, True, False],
                ['Password:', 'sendline({})'.format(self.sm.patterns.default_password),
                 None, False, False],
            ])
            d.process(self.spawn_id, timeout=self.installation_timeout)
        self.go_to('any')
        self.configure_network(uut_gateway, uut_ip, uut_netmask,
                               uut_ip6, uut_prefix, uut_gateway6,
                               change_password)
        logger.info('=== Fully installed.')
        logger.info('=== Validate version installed ...')
        self.validate_version(self.iso_file)

        logger.info('Installation completed successfully.')

    def baseline_by_branch_and_version(self, fmc, site, branch, version,
                                       uut_ip, uut_netmask, uut_gateway,
                                       dns_server, iso_file_type='Restore',
                                       uut_ip6=None, uut_prefix=None, uut_gateway6=None,
                                       change_password=True, timeout=None, serverIp='', tftpPrefix='',
                                       scpPrefix='', docs='', pxeUsername='', pxePassword='', pxeHostname='',
                                       scpDirRoot='', httpDirRoot='', httpDirTmp='', **kwargs):
        """Baseline series3 fmc by branch and version using PXE servers.
        Look for needed files on devit-engfs, copy them to the local kick server
        and use them to baseline the device.

        :param fmc: object of Series3fmc for reconnecting the device
        :param site: e.g. 'ful', 'ast', 'bgl'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param uut_ip: Device IP Address
        :param uut_netmask: Device Netmask
        :param uut_gateway: Device Gateway
        :param dns_server: DNS server
        :param iso_file_type: 'Autotest' or 'Restore'; defaulted to 'Restore'
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param change_password: Flag to change the password after baseline
        :param \**kwargs:
        :Keyword Arguments, any of below optional parameters:
        :param hostname: hostname to be set, defaulted to 'firepower'
        :param search_domains: search domains delimited by comma,
                                defaulted to 'cisco.com'
        :param detection_mode: defaulted to 'Inline',
                                can be: 'Passive','Inline','Access Control','Network Discovery'
        :param http_dir_root: absolute path of the http root
                                e.g. '/tftpboot/asa/'
        :param http_dir_tmp: the temp dir under http_dir_root for version_build
                            and the config file, e.g. '/cache/temp_config'
        :param scp_dir_root: absolute path of the dir for version_build
                            e.g. '/tftpboot/asa/cache/Release' or '/tftpboot/asa/cache/Development'
        :param bz_image: bz image has to be installed on DUT, which is copied
                        from the scp_server, defaulted to 'bzImage*'
        :param usb_image: usb image has to be installed on DUT, which is copied
                            from the scp_server, defaulted to 'usb-ramdisk*'
        :param arch: arch type, defaulted to 'x86_64'
        :param console: set to True if the device is accessed through its console;
                        defaulted to False
        :return: None
        """

        kwargs['fmc'] = fmc
        kwargs['uut_ip'] = uut_ip
        kwargs['uut_netmask'] = uut_netmask
        kwargs['uut_gateway'] = uut_gateway
        kwargs['uut_ip6'] = uut_ip6
        kwargs['uut_prefix'] = uut_prefix
        kwargs['uut_gateway6'] = uut_gateway6
        kwargs['change_password'] = change_password
        kwargs['timeout'] = timeout
        kwargs['dns_server'] = dns_server
        arch = kwargs.get('arch', 'x86_64')

        if KICK_EXTERNAL:
            server_ip = serverIp
            tftp_prefix = tftpPrefix
            scp_prefix = scpPrefix
            files = docs
        else:
            server_ip, tftp_prefix, scp_prefix, files = prepare_installation_files(site, 's3fmc', branch, version,
                                                                               iso=iso_file_type, arch_type=arch)
        if not files[0]:
            raise Exception('Series3 FMC iso file not found on server')

        logger.debug('=== server {}, tftp prefix {}, scp prefix {}'.format(server_ip, tftp_prefix, scp_prefix))
        iso_file_name = '{}/{}'.format(tftp_prefix[len('asa'):], files[0])
        kwargs['http_server'] = server_ip
        kwargs['scp_server'] = server_ip
        kwargs['scp_port'] = '22'
        if KICK_EXTERNAL:
            kwargs['scp_username'] = pxeUsername
            kwargs['scp_password'] = pxePassword
            kwargs['scp_hostname'] = pxeHostname
            kwargs['scp_dir_root'] = scpDirRoot
            kwargs['http_dir_root'] = httpDirRoot
            kwargs['http_dir_tmp'] = httpDirTmp
        else:
            kwargs['scp_username'] = pxe_username
            kwargs['scp_password'] = pxe_password
            kwargs['scp_hostname'] = pxe_hostname
            kwargs['scp_dir_root'] = kwargs.get('scp_dir_root',
                                                '{}/{}'.format(pxe_dir['scp_dir_root'], branch))
            kwargs['http_dir_root'] = kwargs.get('http_dir_root', pxe_dir['http_dir_root'])
            kwargs['http_dir_tmp'] = kwargs.get('http_dir_tmp', pxe_dir['http_dir_tmp'])

        kwargs['iso_image_path'] = iso_file_name
        kwargs['version_build'] = version
        self.series3fmc_baseline(**kwargs)

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
                              power_cycle_flag=False, pdu_ip='', pdu_port='',
                              pdu_user='admn', pdu_pwd='admn', uut_ip6=None, uut_prefix=None,
                              uut_gateway6=None, timeout=None, change_password=True, ipv4_mode='static',
                              ipv6_mode='', dns_servers='', search_domains='', ntp_servers=''):
        """ Baseline Series3FMC device through its physical serial port connection.

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
        :param uut_ip6: Device IPv6 Address
        :param uut_prefix: Device IPv6 Prefix
        :param uut_gateway6: Device IPv6 Gateway
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :param change_password: Flag to change the password after baseline
        :param ipv4_mode: IPv4 configuration mode - 'static' or 'dhcp'
        :param ipv6_mode: IPv6 configuration mode - 'dhcp', 'router' or 'manual'
        :param dns_servers: a comma-separated string of DNS servers
        :param search_domains: a comma-separated string of search domains
        :param ntp_servers: a comma-separated string of NTP servers
        :return:

        """

        publish_kick_metric('device.series3fmc.baseline', 1)
        # set baseline timeout
        self.set_installation_timeouts(timeout)

        # network configuration flag used to indicate if cli configuration is
        # still needed after baseline
        network_config = False

        self.iso_file = iso_url.split('/')[-1]
        self.uut_ip = mgmt_ip
        self.uut_netmask = mgmt_netmask
        self.uut_gateway = mgmt_gateway
        self.uut_ip6 = uut_ip6
        self.uut_prefix = uut_prefix
        self.uut_gateway6 = uut_gateway6

        if power_cycle_flag:
            self.power_cycle(pdu_ip, pdu_port, pdu_user, pdu_pwd)
            d0 = Dialog([
                ['boot:', None, None, False, False],
            ])
            d0.process(self.spawn_id, timeout=600)

            self._boot_selection(self.spawn_id, self.sm.patterns.prompt.lilo_boot_menu_prompt)
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

            # ---------------------------------------------
            # Bring the system to liloos_state
            # ---------------------------------------------
            if self.sm.current_state in ["lilobootmenu_state"]:
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
                                                           ipv4_gateway=mgmt_gateway, ipv6=uut_ip6,
                                                           ipv6_prefix=uut_prefix, ipv6_gateway=uut_gateway6,
                                                           dns_servers=dns_servers, search_domains=search_domains,
                                                           ntp_servers=ntp_servers)
                break

            # If the device moved back to lilo boot menu. Try to go to lilo os and try install again
            if ret == 1:
                self._move_from_lilo_boot_menu_to_lilo_os()

        # Raise error in all the attempts failed
        if i >= 5:
            msg = "Failed to install sereis3Fmc using serial for %s times" % i
            logger.error(msg)
            raise RuntimeError(msg)

        time.sleep(60)

        logger.info('=== Validate mysql process')
        self.validate_mysql_process()

        if not network_config:
            logger.info('=== Configure network')
            self.configure_network(self.uut_gateway, self.uut_ip, self.uut_netmask,
                                   uut_ip6, uut_prefix, uut_gateway6,
                                   change_password)
            logger.info('=== Fully installed.')

        logger.info('=== Validate version')
        iso_file_name = iso_url.split('/')[-1]
        self.validate_version(iso_file_name=iso_file_name)

        logger.info('Installation completed successfully.')

    def _boot_selection(self, spawn, prompt):

        spawn.send("\t")
        spawn.expect('boot:')
        spawn.send("\t")
        spawn.expect('boot:')
        spawn.send("Restore_Serial\r")
        spawn.expect(prompt, timeout=120)

