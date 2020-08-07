"""
This is pyats test script to recover the KP device from failed state
This utility is added to support defect "CSCvs48986"

"""

import argparse
parser = argparse.ArgumentParser(description="standalone parser")
from ats import aetest
from ats import topology
from kick.device2.hostname.actions.hostname import ChangeHostname
from kick.device2.kp.actions.kp import Kp , KpLine


class Common_Setup(aetest.CommonSetup):
    @aetest.subsection
    def connect_to_fpr(self):
        """
             Testbed file , branch and version are mandatory arguments for this script.
             :return:
         """
        global HOSTNAME, DEVICE_USERNAME, DEVICE_PASSWORD, SSH_IP, SSH_PORT, USERNAME, PASSWORD, \
        CONNECTION_TYPE, SITE, UUT_IP, UUT_NETMASK, UUT_GATEWAY, DNS_SERVERS, SEARCH_DOMAINS , \
        branch , version
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--testbed_file', default=None,
                            help="We need a testbed file to run our commands ons.", dest='testbed')
        parser.add_argument('--branch', default='branch',
                            help="branch on which baseline should take build .", dest='branch')
        parser.add_argument('--version', default='version',
                            help="installation version", dest='version')
        args, unknown = parser.parse_known_args()
        yamlfile = args.testbed

        # Load yaml file to testbed object (e.g. wm.yaml)
        tb = topology.loader.load(yamlfile)
        # Device name in the topology file

        HOSTNAME = str(tb.devices[tb.custom.device_name].custom.hostname)
        DEVICE_USERNAME = str(tb.devices[tb.custom.device_name].connections.alt.username)
        DEVICE_PASSWORD = str(tb.devices[tb.custom.device_name].connections.alt.password)
        SSH_IP = str(tb.devices[tb.custom.device_name].connections.a.ip)
        SSH_PORT = str(tb.devices[tb.custom.device_name].connections.a.port)
        USERNAME = str(tb.devices[tb.custom.device_name].connections.a.username)
        PASSWORD = str(tb.devices[tb.custom.device_name].connections.a.password)
        CONNECTION_TYPE = str(tb.devices[tb.custom.device_name].connections.a.protocol)
        SITE = str(tb.devices[tb.custom.device_name].custom.site)
        UUT_IP = str(tb.devices[tb.custom.device_name].interfaces['management'].ipv4.ip)
        UUT_NETMASK = str(tb.devices[tb.custom.device_name].interfaces.mgmt.ipv4.netmask)
        UUT_GATEWAY = str(tb.devices[tb.custom.device_name].interfaces.mgmt.gateway)
        DNS_SERVERS = tb.devices[tb.custom.device_name].custom.dns_servers
        SEARCH_DOMAINS = tb.devices[tb.custom.device_name].custom.search_domains
        branch = args.branch
        version = args.version
        """ Create connection for KP
        """
        global device_host, line
        device_host = ChangeHostname()

        """ connection to console        
        """
        '''
        This will do SSH or Telnet connection as per the details provided in testbed

        '''

        kp = Kp(hostname=HOSTNAME, login_username=DEVICE_USERNAME,
                login_password=DEVICE_PASSWORD)

        if CONNECTION_TYPE is not None and CONNECTION_TYPE == "ssh":
            line = device_host.connect_to_ssh_console_line(ts_ip=SSH_IP, port=SSH_PORT, username=USERNAME,
                                                           password=PASSWORD)
        elif CONNECTION_TYPE is not None and CONNECTION_TYPE == "telnet":
            line = device_host.connect_to_telnet_console_line(ts_ip=SSH_IP, port=SSH_PORT,
                                                              username=USERNAME, password=PASSWORD)
        else:
            line = None
        '''
        Raise exception if "protocol" is blank in testbed
        '''
        if line is None:
            raise ValueError("Protocol should not be blank")


class DropToRommon(aetest.Testcase):
    @aetest.test
    def drop_to_prelogin_logged_in_drop_rommon(self):
        """ First drop the device in prelogin state, then log in and then drop to rommon to recover "failed" state of device
        """
        device_host.drop_to_prelogin(line)
        device_host.from_prelogin_to_logged_in(line=line, username=DEVICE_USERNAME, password=DEVICE_PASSWORD)
        device_host.from_logged_in_to_rommon(line)
        device_host.disconnect_from_ssh_console_line(line)

    @aetest.test
    def baseline(self):
        """
        start the baseline script from rommon prompt to recover the device
        """
        global kp, dev

        kp = Kp(hostname=HOSTNAME, login_username=DEVICE_USERNAME,
                login_password=DEVICE_PASSWORD)

        '''
                This will do SSH or Telnet connection as per the details provided in testbed
        '''
        if CONNECTION_TYPE is not None and CONNECTION_TYPE == "ssh":
            dev = kp.ssh_console(ip=SSH_IP, port=SSH_PORT, username=USERNAME,
                                  password=PASSWORD)
        elif CONNECTION_TYPE is not None and CONNECTION_TYPE == "telnet":
            dev = kp.telnet_console(ip=SSH_IP, port=SSH_PORT, username=USERNAME,
                                     password=PASSWORD)
        else:
            dev = None
        '''
        Raise exception if "protocol" is blank in testbed
        '''
        if dev is None:
            raise ValueError("Protocol should not be blank")
        dev.baseline_by_branch_and_version(site=SITE,
                                           branch=branch,
                                           version=version,
                                           uut_ip=UUT_IP,
                                           uut_netmask=UUT_NETMASK,
                                           uut_gateway=UUT_GATEWAY,
                                           uut_username=DEVICE_USERNAME,
                                           uut_password=DEVICE_USERNAME,
                                           uut_hostname=HOSTNAME,
                                           dns_server=DNS_SERVERS,
                                           search_domains=SEARCH_DOMAINS)



class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def disconnect_fpr(self):
        """ Disconnect console connection
        """

        dev.disconnect()


if __name__ == '__main__':
    aetest.main()



