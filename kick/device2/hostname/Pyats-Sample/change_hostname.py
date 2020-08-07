"""
This is pyats test script to change the hostname for KP/WM device

"""

import argparse
parser = argparse.ArgumentParser(description="standalone parser")
from ats import aetest
from ats import topology
from kick.device2.hostname.actions.hostname import ChangeHostname

class Common_Setup(aetest.CommonSetup):
    @aetest.subsection
    def connect_to_fpr(self):
        """
               Testbed file is the mandatory argument for this script.
               :return:
        """
        global HOSTNAME, DEVICE_USERNAME, DEVICE_PASSWORD, SSH_IP, SSH_PORT, USERNAME, PASSWORD, CONNECTION_TYPE
        parser = argparse.ArgumentParser()
        parser.add_argument('--testbed_file', default=None,
                            help="We need a testbed file to run our commands ons.", dest='testbed')
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
        """ Create connection for WM/KP
        """
        global device_host,line
        device_host = ChangeHostname()

        """ connection to console        
        """
        '''
        This will do SSH or Telnet connection as per the details provided in testbed
        
        '''

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


class ChangehostnameWMKP(aetest.Testcase):
    @aetest.test
    def drop_to_prelogin(self):
        """ First drop the device in prelogin state
        """
        device_host.drop_to_prelogin(line)

    @aetest.test
    def change_hostname_prelogin(self):

        """ change hostname from pre-login state
            First it will check if app(FTD) is present, if it is then change hostname from FTD else from FXOS(scope system)
        """

        device_host.change_hostname_from_prelogin(line, hostname=HOSTNAME,username=DEVICE_USERNAME, password=DEVICE_PASSWORD)

class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def disconnect_fpr(self):
        """ Disconnect console connection
        """
        device_host.disconnect_from_ssh_console_line(line)


if __name__ == '__main__':
    aetest.main()



