----------------------------------------------
Module overview
----------------------------------------------
This module provides operations for chassis device (1RU, 3RU, Queensway),
which will first get access (Telnet, SSH, etc)
to the chassis console, execute/configure chassis commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:
* Chassis(BasicDevice): A class that extends BasicDevice
* ChassisLine(BasicLine): A class that provides a connection to the chassis and helper methods

##### General information about 1RU and 3RU units
For detailed information on the different operational modes of the 1RU and 3RU devices please check out:
https://www.cisco.com/c/en/us/td/docs/security/firepower/fxos/fxos201/cli-config/b_CLI_ConfigGuide_FXOS_201/getting_started.html

The below information provides a basic understanding on the operational modes that can be used
with the chassis library.

##### The chassis device
The chassis is to be understood as the physical device that comprises of the chassis backbone
plus the chassis slots. The slots can be populated by security modules. 

Each security module can host an application (ftd) in NATIVE or CONTAINER mode. 
NATIVE mode means that the security module's hardware resources are allocated to the hosted FTD 
application as a whole. It's like installing an os on a PC. All the PCs resources are allocated 
to that os natively.
CONTAINER mode means that the security module's hardware resources can be shared between 
multiple FTD applications hosted on an intermediate layer. This is also referred as
"MULTIINSTANCE" mode. I will use CONTAINER mode in this documentation because multiinstance
can be a more confusing term. When using container mode, since the applications are sharing
the underlying security module's hw resources, the user need to create RESOURCE PROFILES and 
ASSING A RESOURCE PROFILE TO EACH FTD.

A chassis can be configured in one of two modes: STANDALONE or CLUSTERED.
STANDALONE mode means that the chassis slots are isolated from each other from a logical point
of view. Each slot is isolated from the next slot and configured independently. That means
that also the security modules that populate the slots are isolated from each other.
CLUSTERED mode means that more slots in a chassis can behave as a single slot in which their
resources are brought together from a logical point of view. For instance if we have a 3 slot
unit, a 3RU, the slots can be configured to run as a single FTD application. This is
called intra-chassis clustering. There is also inter-chassis clustering in which chassis
instances can be grouped together in a cluster.

Each chassis has installed on it an operating system called fxos. This is the operating
system that allows the configuration of the chassis related parameters: for e.g. the
chassis management ip, the chassis slot related configurations (standalone, clustered),
deploying the configuration of the ftd applications on each security module, debugging
the security modules, configuration of the network interfaces that are available on the
chassis etc.

When installing an FTD application on a chassis a procedure must be followed:

PREREQUISITES:
1. The user must think how the network interfaces will be configured and assigned to the
chassis. This is necessary if the user wants to use certain topologies in his tests.
2. The user must think about how many application he needs.
3. The user must think what the network configuration for the applications will be.

PROCEDURE:
1. Configure the chassis management network, ip, netmask, gateway, dns etc.
1. Decide wether an fxos update is needed or not. There are compatibility issues between 
the fxos versions and the FTD versions so the user must take care of this. This is out of
scope for the current documentation.
2. Download the fxos and install for above step. This is done in kick by using the engfs
servers and the fxos server to get the images that the user needs. These are copied to
each local site where the device is located (also specified by the user) and downloaded
to the device from there for lower download times. 
3. Configure the network interfaces (these are independent of the management interface
of the chassis) which will be used by the FTD applications. Each network interface 
must be configured in its type: data, firepower-eventing, data-sharing, management.
Also interfaces can be grouped in port-channels for higher throughput. Each ftd app will
need at least a management type interface assigned to it in order to come online.
4. Download and install the ftd application package. Also done in kick similar to fxos.
5. Create an application instance on a specified slot. The application instance is called
and app-instance in the domain specific language.
6. Create a bootstrap script that installs, configures and launches the application
on the slot. The bootstrap script is called a logical-device in the domain specific
language. The logical device will contain interface assignment, that is the interfaces
on the chassis will be mapped to so called external-port-links of the FTD. This means
that the user must think how to share the interfaces on the chassis when deploying
multiple ftds because their number is limited while the number of ftd instances in
container mode can be large.
7. Wait for the app to become online.

The chassis library provides baseline functions and helper functions for issueing commands 
to the chassis backbone and chassis slots and also provides a state machine for representing 
some of the states that the chassis, slots and slot applications can be in.

The library deploys the application instances in parallel for time efficiency.

##### The chassis class
A chassis instance can be initialized by calling the Chassis class constructor
in the following way:
```python
chassis_data = Chassis.extract_chassis_data_device_configuration(
    testbed.devices['chassis1'])
chassis = Chassis(chassis_data)
```
where testbed is the testbed object loaded in memory from the yaml, and the label
'chassis1' is the node named 'chassis1' from the devices section of the testbed.
```yaml
devices:
    chassis1:
        type: 'Firepower 9300'
        connections:
            console:
                protocol: 'ssh'
                ip: '10.83.53.61'
<rest of the testbed contents>
```

##### The chassis connection
A connection object to the chassis can be obtained in various ways (ssh etc.)
like in the example below:
```python
chassis_con = chassis.ssh_console(
    ip=chassis_data['connections'].console.ip,
    port=chassis_data['connections'].console.port,
    username=chassis_data['connections'].console.user,
    password=chassis_data['connections'].console.password)
```
where chassis_data is obtained like above, or the arguments can be directly
extracted from the testbed by the user.

##### The chassis state machine

1. The chassis states are the following:
    - 'prelogin_state' - the state the chassis is in before login
    - 'mio_state' - the main chassis prompt state
    - 'local_mgmt_state' - the chassis local management state
    - 'fxos_state' - the chassis operating system management state

2. The chassis security module states (each populated slot):
    - 'cimc_state' - the cimc management state for the slot
    - 'fpr_module_state' - the security module management state corresponding to the module
    that populates a slot

3. The chassis application states:
    1. Ftd states:
        - 'fireos_state' - the ftd main prompt state
        - 'expert_state' - the ftd goes into expert mode
        - 'sudo_state' - the ftd goes into the sudo prompt
        - 'enable_state' - the ftd enable state
        - 'config_state' - the ftd configuration mode state, if configured on
        the device
        - 'disable_state' - the ftd disable state

Between all of these state the statemachine provides automatic transitions.
For going to a specific state the user must issue a call to go_to(<state_name>)
where state_name is for instance 'fireos_state' etc. Because a setup can have
multiple slots and multiple apps on each slot the state machine is controlled
by 2 important parameters, the current slot id and the current application
identifier. These can be set by calling the below methods.
```python
chassis_con.set_current_slot(1)
chassis_con.set_current_application('sensor1')
```
This means that the state machine will change states according to the current
slot id which is 1 and the current application identifier which is 'sensor1'.
For example, issueing
```python
chassis_con.go_to('fireos_state')
```
will tell the state machine to transition to the ftd main prompt that is on
slot 1 and has the identifier 'sensor1'.

##### Chassis baseline requirements
Terminal server:
1. A terminal server.
2. A connection from terminal server to chassis.
The above are needed in order that the connection always be kept alive even
if the device is power cycled or restarted during the baseline process.
3. The roty fields should reflect the port number modulo 100. So if the ssh
port is 2030 then the roty id is 30 and the line id x/x/x is taken by issueing
show line command and matching the roty field and taking the line id.
4. Ssh connection is prefered but telnet is also suported.

##### Chassis baselining
There are 2 easily available methods than can be used for chassis baselining:

1. Using a call to baseline_by_branch_and_version() method on the chassis
connection object like so:
```python
chassis_con.baseline_by_branch_and_version(
    chassis_data=chassis_data
)
```
where chassis_con and chassis_data are obtained as in above examples.
This method will use the pxe servers nearest to the device site specified for
image download of fxos and ftd. The images will get downloaded to the pxe from
the ngfs sites and after this they will get downloaded to the device. If the
images are already on the pxe server they will get downloaded from there to
the device.
The branch, version and site information are taken from the testbed from the
chassis_software section:
```yaml
chassis_software:
  device_mode: standalone
  version: 6.3.0-1393
  fxos_url: http://sjc-ssp-artifacts.cisco.com/ssp/92.4.1/92.4.1.2912/final/fxos-k9.92.4.1.2912.SSB
  site: ful
  branch: Development
```

2. Using a call to baseline
In this case the user can provide inside the testbed custom scp links for the
fxos and csp image files like below:
```yaml
chassis_software:
  device_mode: standalone
  csp_url: 'scp://pxe@pxe-fulton.cisco.com:/tftpboot/asa/cache/temp_config/cisco-ftd.6.3.0.1300.SSB.csp'
  fxos_url: 'scp://pxe@pxe-fulton.cisco.com:/tftpboot/asa/cache/temp_config/fxos/fxos-k9.92.4.1.2912.SSB'
  scp_password: 'pxe'
  device_mode: 'standalone'
  applications:
    1:
      slot: 1
      <other application settings>
      startup_version: '6.3.0.1302'
      csp_url: 'scp://pxe@pxe-fulton.cisco.com:/tftpboot/asa/cache/temp_config/cisco-ftd.6.3.0.1302.SSB.csp'
    <the rest of the specified applications>
```
In this case the baseline will:
 - take the fxos from the fxos_url location;
 - take the "base" csp_url for each app from the csp_url section under chassis_software
 - if the user also provides a csp_url entry under an application section this will be
 used instead of the "base" csp_url. The scp considers that the scp server that hosts
 the fxos and ftd images is the same for all of them so only one scp_password can be specified.

##### Standalone device mode

Standalone mode means that the chassis slots are used independently of each other.
The ftd applications installed on each slot are independent.
For more information on this visit: https://www.cisco.com/c/en/us/td/docs/security/firepower/fxos/fxos201/web-config/b_GUI_ConfigGuide_FXOS_201/logical_devices.html#task_4D51AFC7091E4D8F8289F08C6A071459

Section: Create a Standalone Threat Defense Logical Device

The mode is controlled by the device_mode attribute in the testbed.

##### Clustered device mode

Clustered mode means that the chassis slots act as a single unit. If multiple
slots are available the applications installed on each slot act together like
a single application.
For more information on this visit: https://www.cisco.com/c/en/us/td/docs/security/firepower/fxos/fxos221/cli-guide/b_CLI_ConfigGuide_FXOS_221/logical_devices.html

Section: Configure Firepower Threat Defense Clustering

The mode is controlled by the device_mode attribute in the testbed.

##### The chassis testbed
The structure of the chassis is abstracted in the yaml language as a testbed.

###### The topology section
The interfaces available on the chassis can be declared inside the topology
testbed section like so:
```yaml
topology:
    chassis1:
        interfaces:
            chassis_mgmt: # special interface containing the management details for the chassis network settings
                type: 'Ethernet'
                alias: 'chassis_management'
                ipv4_ip: '10.13.3.110'
                ipv4_netmask: '255.255.240.0'
                ipv4_gateway: '10.13.0.1'
            interface_1: # a simple physical interface configured as management
                type: 'Ethernet'
                hardware: 'Ethernet1/1'
                subtype: 'mgmt'
            interface_2: # a simple physical interface configured as data
                type: 'Ethernet'
                hardware: 'Ethernet1/2'
                subtype: 'data'
            interface_3: # a simple physical interface configured as data-sharing
                type: 'Ethernet'
                hardware: 'Ethernet1/3'
                subtype: 'data-sharing'
            interface_4: # a simple physical interface configured as firepower-eventing
                type: 'Ethernet'
                hardware: 'Ethernet1/4'
                subtype: 'firepower-eventing'
            interface_5: # a physical interface with subinterfaces
                type: 'Ethernet'
                hardware: 'Ethernet1/5'
                subtype: 'data'
                subinterfaces:
                    - {'id': 1, vlan_id: '100', subtype: 'data'}
                    - {'id': 2, vlan_id: '101', subtype: 'data-sharing'}
            interface_6: # a port channel interface joining two physical interfaces together
                id: '1'
                type: 'PortChannel'
                subtype: 'data'
                member_ports:
                    - 'Ethernet1/6'
                    - 'Ethernet1/7'
            interface_7: # a port channel interface with subinterfaces
                id: '1'
                type: 'PortChannel'
                subtype: 'data'
                member_ports:
                    - 'Ethernet2/1'
                    - 'Ethernet2/1'
                subinterfaces:
                    - {'id': 1, vlan_id: '100', subtype: 'data'}
                    - {'id': 2, vlan_id: '101', subtype: 'data-sharing'}
```

The testbed declaration is used to configure the interfaces on the chassis.
Later these interfaces can be assigned to the applications. If the user
creates an invalid interface configuration the chassis will not allow this and
will throw an error that is surfaced by the library (visible in the execution
log).

###### The chassis device section
The following chassis attributes are specified in the device section:
 - connections (the declaration of connection types, ssh etc.)
 - custom (custom attributes)

###### The chassis custom section
 - model_number (signals the type of device, in our case 'chassis')
 - cleanup_options (section describing cleanup settings)
    - cleanup_subinterfaces (used to specify if the baseline should first attempt
    subinterfaces deletion)
    - cleanup_port_channels (used to specify if the baseline should first attempt
    port channel deletion)
    - reset_interfaces_to_data_type (used to specify if the baseline should first
    attempt to reset all interfaces to data type)
    - cleanup_resource_profiles (used to specify if the baseline should first
    attempt resource profile deletion)
    - cleanup_user_slots_only (used to specify if the baseline should only take
    into consideration the user slots specified in the testbed for cleanup and
    leave the rest of the slots untouched)
    - cleanup_apps (used to specify if the baseline should first attempt
    application deletion)
    - reinitialize_slots (used to specify if the baseline should first attempt
    to reinitialize the slots, formatting them)
 - the chassis_id (the id of the chassis, see documentation link)
 - chassis_security_key (the chassis security key, see documentation link)
 - chassis_login (the chassis login information: username and password)
 - chassis_network (extra network details besides the ones available in topology)
    - hostname, the chassis hostname
    - dns_servers, the dns_servers
    - search_domain, the search domain
 - chassis_power (the chassis can be connected to a power bar server)
    - power_bar_server (the power bar server ip)
    - power_bar_port (the power bar server port to which the chassis is connected)
    - power_bar_user (the login username)
    - power_bar_password (the login password)
    - power_cycle_before_baseline (specifies whether to cycle the power
    before starting the baseline)
 - chassis_software (describes the software available on the chassis)
    - resource_profiles (defines the resource profiles to be created during the
    baseline)
        - name (the resource profile name)
        - cpu_core_count (the number of cpu cores to be assigned when assigning
        the resource profile to the application)
    - application_generic (section that describes settings that are common
    to all applications on the chassis)
        - sudo_login (username and password for sudo login for apps)
        - the hostname of the applications
    - install_fxos (flag can be used to skip fxos installation)
    - fxos_url (the operating system package url location)
    - csp_url (the application package url location)
    - device_mode (can be 'standalone' or 'clustered')
    - applications (section decribing application specific settings)
        - 1: (the first application)
            - slot (the slot id to which the application will be deployed)
            - resource_profile (the resource profile to be assigned to the current
            application)
            - application_name (the name of the application, can be ftd)
            - application_identifier (the identifier of the application, for example sensor1)
            - deploy_type: can be 'native' or 'container'
            - startup_version: the startup version of the application
            - logical device (section describing the logical device configuration
            of the current application):
                - name (should be the same as the application name to which it applies, for example sensor1)
                - external_port_links (section decribing the external port links mapping
                to the interfaces)
                    - this is specified as a list with objects from the chassis topology section
                    example:
                        ```yaml
                        external_port_links:
                          - Ethernet1/1 #example interface
                          - Ethernet1/2.2 #example subinterface
                          - 'Port-channel1' #example portchannel
                        ```
            - bootstrap_keys (section describing the bootstrap keys to be added to
            the logical device, key-value pairs. The keys must match valid boostrap
            key names)
            - bootstrap_keys (section describing secret bootstrap keys)
            - ipv4 (section describing the ipv4 setting to be added to the logical
            device)
                - ip
                - netmask
                - gateway

##### Special case for clustered baseline
In clustered baseline mode there is only a single logical device for all the
slots available in the chassis. Also, the slots can pe populated or not but must
all be included in the logical device creation.
Because of this the logical device details are read from the first application,
not from all the applications (bootstrap keys, bootstrap secret keys). Except for
the ip settings section which is still read from each of the apps because each module
will end up having it's own ip settings. Also, these ip settings will need to be
provided even if the slot is not populated by a security module.

**Example testbeds for the various deployment modes (standalone, clustered,
native or container) can be found in the kick/device2/chassis/tests folder.**

The most basic testbed example for a multiinstance (container) standalone baseline is:
```yaml
devices:
  chassis1:
    type: chassis
    alias: chassis1
    connections:
      console:
        password: labuser
        user: labuser
        port: '2006'
        ip: 10.83.53.61
        protocol: ssh
    custom:
      chassis_login:
        password: Admin123
        username: admin
      chassis_network:
        hostname: BATIT-C9300-1-FUL
      chassis_software:
        device_mode: standalone
        version: 6.3.0-1390
        fxos_url: http://sjc-ssp-artifacts.cisco.com/ssp/92.4.1/92.4.1.2912/final/fxos-k9.92.4.1.2912.SSB
        site: ful
        branch: Development
        application_generic:
          sudo_login:
            password: Admin123
            username: admin
        applications:
          '1':
            alias: sensor1
            application_name: ftd
            resource_profile: rp1
            slot: 1
            logical_device:
              external_port_links:
              - Ethernet1/1
              - Ethernet1/2.1
              bootstrap_keys:
                firepower_manager_ip: 10.13.3.109
                search_domain: cisco.com
                fqdn: sensor1.cisco.com
                dns_servers: 10.83.48.30
                firewall_mode: transparent
              name: sensor1
              ipv4:
                gateway: 10.13.3.1
                netmask: 255.255.240.0
                ip: 10.13.3.111
            deploy_type: container
            application_identifier: sensor1
          '2':
            alias: sensor2
            application_name: ftd
            resource_profile: rp1
            slot: 1
            logical_device:
              external_port_links:
              - Ethernet1/1
              - Ethernet1/2.2
              bootstrap_keys:
                firepower_manager_ip: 10.13.3.109
                search_domain: cisco.com
                fqdn: sensor2.cisco.com
                dns_servers: 10.83.48.30
                firewall_mode: transparent
              name: sensor2
              ipv4:
                gateway: 10.13.3.1
                netmask: 255.255.240.0
                ip: 10.13.3.112
            deploy_type: container
            application_identifier: sensor2
        resource_profiles:
          resource_profile_1:
            name: rp1
            cpu_core_count: 6
topology:
  chassis1:
    interfaces:
      interface_1:
        type: Ethernet
        hardware: Ethernet1/1
        subtype: mgmt
      interface_2:
        type: Ethernet
        hardware: Ethernet1/2
        subinterfaces:
        - vlan_id: '100'
          id: 1
          subtype: data
        - vlan_id: '101'
          id: 2
          subtype: data-sharing
        subtype: data
```

##### Using chassis in fastpod
If you are using the chassis inside fastpod, the input file is in json format
instead of yaml and the structure is a bit different.

The chassis settings are hosted under the type 'chassis' and the application
instances are hosted under their own entry as a stand alone ftd with type 'ssp'.
The rest of the details remain virtually the same.

The basic json structure looks like below:
```json
{
  "devices": {
    "FTD-1": {
      "type": "ssp",
      "chassis": "chassis1",
      "network": [
        "Ethernet1/1",
        "Ethernet1/2",
        "Ethernet1/5"
      ],
      "ipv4": {
        "ip": "10.89.19.35",
        "netmask": "255.255.255.224",
        "gateway": "10.89.19.33"
      }
    },
    "chassis1": {
      "network_map":{
        "Management": {
          "vlan": "1098"
        }
      },
      "type": "chassis",
      "access": {
        "laas_device": "SSP-3RU/SSP3RU"
      },
      "custom": {
        "chassis_login": {
          "username": "admin",
          "password": "Admin123"
        },
        "chassis_network": {
          "hostname": "BATIT-C9300-1-AST"
        },
        "chassis_software": {
          "site": "ast",
          "image": "Development/6.3.0-1698",
          "application_generic": {
            "sudo_login": {
              "username": "admin",
              "password": "Admin123"
            }
          }
        }
      },
      "interfaces": {
        "interface_1": {
          "type": "Ethernet",
          "hardware": "Ethernet1/1",
          "subtype": "data"
        },
        "interface_2": {
          "type": "Ethernet",
          "hardware": "Ethernet1/2",
          "subtype": "data"
        },
        "interface_3": {
          "type": "Ethernet",
          "hardware": "Ethernet1/5",
          "subtype": "mgmt"
        }
      }
    }
  },
  "testbed": {
    "pod_data": {
      "pod_id": "SJC1054",
      "vcenter_name": "sjc-vc01.cisco.com",
      "pcloud": false
    },
    "laas": {
      "site": "apex-laasng.cisco.com",
      "domain_name": "apex",
      "duration": 600
    },
    "fastpod_name": "chassis_restricted",
    "kick_url": "kick.cisco.com"
  }
}
```
The above example is for a basic deployment using a laasng hosted chassis.
We can see that the json revolves around two sections: the devices section and
the testbed section. The testbed section contains information about the laasng
server where the chassis details can be found, the fastpod_name, etc. The devices 
section is a list of devices that the fastpod will deploy for you. Here we have 
two devices, one of type chassis that contains the chassis related information
and one FTD application that will be deployed on the chassis that contains the
FTD specific information.

For the chassis the user basically has to provide, as seen above, the chassis
login details, the chassis network configuration, the chassis interface configuration
settings and other the same way as it is specified in the previous sections of 
this documentation. Under the ftd application the user must provide the chassis name
on which the application will be deployed on (there may be multiple chassises each
with a set of the applications), the bootstrap external port links assigned to the
application (the mapping of chassis interfaces to ftd interfaces) under "network"
and the ip settings that the ftd will have configured on its management interface.
Also, under chassis, since this is a laasng example the user will give the device
folder (in which case laasng will select a random device under that folder) or 
the device name of a specific device under "access" key. Also, the "network_map" is
used to controll the laasng router and connect defined interfaces in laasng to defined
vlans for specific network configurations. The applications will be baselined to the
specific branch and version provided under the "chassis_software" section for their
respective chassis. The "application_generic" section contains information that
will be common to all ftds deployed on the chassis, as can be seen in the example
all ftds will have the user "admin" and the password "Admin123". The above example
is very basic and default values will be provided for certain parameters that were
not specified by the user, for instance, the slot will be "1" is the user does not
specify it, the deploy_type will be native and the device_mode will be "standalone".

More information about using fastpod with chassis and physical ftds can be found at:
https://confluence-eng-rtp2.cisco.com/conf/display/IES/03.+Physical+FTD
