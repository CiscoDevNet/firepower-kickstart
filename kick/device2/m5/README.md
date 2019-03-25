----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for FMC M5 device,
which will first get access (Telnet, SSH)
to the FMC, execute/configure FMC M5 commands, and return outputs.
Cisco Unicon will be used for interaction between command sending/receiving.

Sub modules/Main Classes included:

* M5: A class that inherits M4 class and provides all the methods of parent class
* M5Line: A class that extends M4Line and provides various advanced methods to baseline FMC M5 such as:

- Baseline FMC M5 through its CIMC connection by providing the full path to the iso image
```python

    def baseline_fmc_m5(self, iso_map_name, http_link, iso_file_name,
                        mgmt_ip, mgmt_netmask, mgmt_gateway, timeout=None):
        """Baseline M5 through its CIMC connection.

        :param iso_map_name: map name for command map-www, e.g. 'myiso'
        :param http_link: http link for the share, e.g. 'http://10.83.65.25'
        :param iso_file_name: iso filename under http_link,
               e.g. '/cache/Development/6.3.0-10558/iso/Sourcefire_Defense_Center-6.3.0-10558-Autotest.iso
        :param mgmt_ip: management interface ip address
        :param mgmt_netmask: management interface netmask
        :param mgmt_gateway: management interface gateway
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s
        :return: None

        """
```
- Baseline FMC M5 through CIMC connection by specifying the branch and version (e.g. branch='Development', version='6.3.0-10581'):
this method looks for the iso file on devit-engfs server, copies it on local kick server and passes it to the baseline process.
The iso file is fetched automatically, based on device type, branch and version.
For more details regarding the files transfer please see:
https://confluence-eng-rtp2.cisco.com/conf/display/IES/NGFW+image+servers

 ```python

        def baseline_by_branch_and_version(self, site, branch, version, uut_ip, uut_netmask,
                                       uut_gateway, iso_file_type='Restore', timeout=None):
        """Baseline FMC M5 through CIMC connection by specifying the branch and version using PXE servers.
        Grabs automatically the iso file from devit-engfs server, copies it to the local kick server
        and use it to baseline the device.

        :param site: e.g. 'ful', 'ast', 'bgl'
        :param branch: branch name, e.g. 'Release', 'Feature'
        :param version: software build-version, e,g, 6.2.3-623
        :param uut_ip: ip address of management interface
        :param uut_netmask: netmask of management interface
        :param uut_gateway: gateway ip address of mgmt interface
        :param iso_file_type: 'Autotest' or 'Restore'; defaulted to 'Restore'
        :param timeout: in seconds; time to wait for device to boot with the new image;
                        if not provided, default baseline time is 7200s

        """
```

- baseline FMC M5 on serial connection: the physical serial port of the device has to be connected to a terminal server
and properly configured. This method uses 'Restore' image and follows the process described at 'Starting the Restore
Utility Using KVM or Physical Serial Port' paragraph from here:
https://www.cisco.com/c/en/us/td/docs/security/firepower/hw/getting-started/firepower-management-center-1000-2500-4500/Firepower-MC-Getting-Started-1000-2500-4500.html#47850

```python

    def baseline_using_serial(self, iso_url, mgmt_ip, mgmt_netmask, mgmt_gateway, mgmt_intf="eth0", timeout=None,
                              power_cycle_flag=False, pdu_ip='', pdu_port='',
                              pdu_user='admn', pdu_pwd='admn'):
        """Baseline FMC M5 device through its serial connection

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
        :return:
        """
```
