----------------------------------------------
Module overview
----------------------------------------------
This module provides operations for a Westminster device,
which will first get access (Telnet, SSH, etc)
to the device console, execute/configure commands, and return outputs.

Cisco Unicon will be used for interaction between command sending/receiving.

Sub modules/Main Classes included:
* Wm(Kp): A class that extends Kp class
* WmLine(KpLine): A class that provides a connection to the Westminster device
 and helper methods like baseline(), baseline_by_branch_version()

#### Westminster Device
The Westminster device is a low end platform, similar to the Kilburn Park,
where one image will bring FXOS and FTD installed.

#### Wm Class
The Wm class is used to manage a Westminster device (FXOS+FTD).
Further, we are going to use the 'chassis' term to refer to the FXOS.

A Westminster instance can be initialized by calling the Wm class
constructor in the following way:

```python
from kick.device2.wm.actions.wm import Wm

wm_device = Wm(hostname=INIT_HOSTNAME, login_username=USERNAME,
		        login_password=PASSWORD, sudo_password=PASSWORD)
```
where
- INIT_HOSTNAME represents the chassis hostname
- USERNAME: username to login to the chassis
- PASSWORD: password to login to the chassis

### Wm connection
A connection object to the chassis can be obtained by connecting
to the console of the device, using one of the following methods:

```python
wm_conn = wm_device.ssh_console(ip=TERM_IP, port=PORT, username=USERNAME,
		                        password=PASSWORD, timeout=120)

wm_conn = wm_device.telnet_console(ip=TERM_IP, port=PORT, username=USERNAME,
		                           password=PASSWORD, timeout=120)

wm_conn = wm_device.telnet_console_no_credentials(ip=TERM_IP, port=PORT,
                                                  timeout=120)
```

### FTD connection
To access directly the FTD installed on a Wm, ssh_vty() method
has to be called, as shown below:

```python
ftd_conn = wm_device.ssh_vty(ip=MGMT_IP, port=22, username='admin',
                    password='Admin123', timeout=60)
```
where MGMT_IP is the ip of the sensor

### Westminster state machines

The Wm states are grouped by:

1. chassis related states: representing the fxos states
- ‘prelogin_state’ - the state the chassis is in before login
- ‘local_mgmt_state’ - the chassis local management state
- ‘fxos_state’ - the chassis operating system management state
- 'rommon_state'

2. FTD related states
- ‘fireos_state’ - the ftd main prompt state
- ‘expert_state’ - the ftd goes into expert mode
- ‘sudo_state’ - the ftd goes into the sudo prompt

Between all of these states the statemachine provides automatic transitions.
For going to a specific state the user must call 'go_to(<state_name>)' method
where state_name is a valid state.

### Westminster baseline requirements

1. Console connection to the chassis
2. The roty fields on the terminal server should reflect the port number modulo 100.
So if the ssh port is 2030 then the roty id is 30 and the line id x/x/x
is taken by issueing show line command and matching the roty field and taking the line id.
3. Ssh connection is preferred but telnet is also supported.

### Westminster baselining

There are 2 available methods than can be used for Wm baselining:

1. Baseline by specifying the branch and version
```python
wm_conn.baseline_by_branch_and_version(site=site,
                                       branch=branch,
                                       version=version,
                                       uut_ip=UUT_IP,
                                       uut_netmask=UUT_NETMASK,
                                       uut_gateway=UUT_GATEWAY,
                                       uut_username=USERNAME,
                                       uut_password=PASSWORD,
                                       uut_hostname=HOSTNAME,
                                       dns_server=DNS_SERVERS,
                                       search_domains=SEARCH_DOMAINS)
```
where:
- site: e.g. 'ful', 'ast', 'bgl'
- branch: branch name, e.g. 'Release', 'Feature', 'Development'
- version: software build-version, e,g, 6.4.0-10138
- uut_ip: FTD IP Address
- uut_netmask: FTD Netmask
- uut_gateway: FTD Gateway
- dns_server: DNS server

This method accepts also Keyword Arguments, any of below optional parameters:
- uut_hostname: Device Host Name in the prompt
- uut_username: User Name to login to uut
- uut_password: Password to login to uut
- search_domains: search domain, defaulted to 'cisco.com'
- file_server_password: if use scp protocol, this is the password to
			   download the image
- power_cycle_flag: if True power cycle the device before baseline
- mode: the manager mode (local, remote)
- uut_ip6: Device IPv6 Address
- uut_prefix: Device IPv6 Prefix
- uut_gateway6: Device IPv6 Gateway
- manager: FMC to be configured for registration
- manager_key: Registration key
- manager_nat_id: Registration NAT Id
- firewall_mode: the firewall mode (routed, transparent)

This method will use the pxe servers nearest to the device site specified
for image download of fxos and ftd. The images will get downloaded to
the pxe from the ngfs sites and after this they will get downloaded to
the device.

2. Baseline by providing the full path of the images

```python
wm_conn.baseline(tftp_server=TFTP_SERVER,
		     rommon_file=ROMMON_FILE,
		     uut_ip=UUT_IP,
		     uut_netmask=UUT_NETMASK,
		     uut_gateway=UUT_GATEWAY,
		     uut_username=USERNAME,
		     uut_password=PASSWORD,
		     uut_hostname=HOSTNAME,
		     dns_servers=DNS_SERVERS,
		     search_domains=SEARCH_DOMAINS,
		     fxos_url=FTD_URL,
		     ftd_version=FTD_VERSION)
```
This method does the following steps:
- assigns an ip address from mgmt network to the sensor in rommon mode
- tftp downloads and boots an fxos image
- from within FXOS downloads and installs a FTD image

It takes the following parameters:
- param tftp_server: tftp server to get rommon and fxos images
- param rommon_file: rommon build,
         e.g. 'asa/cache/Development/6.4.0-10138/installers/fxos-k8-fp2k-lfbff.82.5.1.893i.SSB'
- param uut_hostname: hostname of the FTD
- param uut_username: User Name to login to FTD
- param uut_password: Password to login to FTD
- param uut_ip: Device IP Address to access TFTP Server
- param uut_netmask: Device Netmask
- param uut_gateway: Device Gateway
- param dns_servers: DNS Servers
- param search_domains: Search Domains
- param fxos_url: FXOS+FTD image url,
         e.g. 'tftp://10.89.23.30/asa/cache/Development/6.4.0-10138/installers/
         cisco-ftd-fp1k.6.4.0-10138.SSB'
- param ftd_version: ftd version, e.g. '6.4.0-10138'
- param file_server_password: if use scp protocol, this is the password to
         download the image
- param power_cycle_flag: if True power cycle the device before baseline
- param mode: the manager mode ('local', 'remote')
- param uut_ip6: Device IPv6 Address
- param uut_prefix: Device IPv6 Prefix
- param uut_gateway6: Device IPv6 Gateway
- param manager: FMC to be configured for registration
- param manager_key: Registration key
- param manager_nat_id: Registration NAT Id
- param firewall_mode: the firewall mode ('routed', 'transparent')
- return: None

#### Baseline Command Line Syntax
* Command line syntax:

python test_baseline.py --testbed <testbed_topo_file> [--rommon_file <rommon_file>] [--ftd_file <ftd_file>]

Sample scripts can be found in the tests folder.

* Command line example 1:
python test_baseline.py --testbed wm.yaml
