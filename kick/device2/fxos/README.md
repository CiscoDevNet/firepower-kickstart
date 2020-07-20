----------------------------------------------
Module overview
----------------------------------------------
This module provides operations for chassis device (1RU, 3RU, Queensway),
which will first get access (Telnet, SSH, etc)
to the chassis console, execute/configure chassis commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

##### General information about 1RU and 3RU units
For detailed information on the different operational modes of the 1RU and 3RU devices please check out:
https://www.cisco.com/c/en/us/td/docs/security/firepower/fxos/fxos201/cli-config/b_CLI_ConfigGuide_FXOS_201/getting_started.html


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

The library deploys the application instances in parallel for time efficiency.

##### Baselining using the fxos library
For baselining a device using the fxos library the user can run the baseline_ssp.py script from the tests
folder and provide a testbed similar to the ones shown inside the testbed_samples folder as input.
Please see inside baseline_ssp.py the documentation about input parameters beside testbed file.

Example usage:
python kick/device2/fxos/tests/baseline_ssp.py --testbed kick/device2/fxos/testbed_samples/ssp3ru_native.yaml --build 1119 --version 6.5.0 --branch Development --fxos_file fxos-k9.2.7.1.4.SPA

More information about using fastpod with chassis and physical ftds can be found at:
https://confluence-eng-rtp2.cisco.com/conf/display/IES/03.+Physical+FTD
