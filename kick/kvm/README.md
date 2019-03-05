KVM README
==========

Module Overview:
----------------

Use kick.kvm module to deploy an virtual FMC or virtual FTD on a KVM

Usage of kick.kvm module:
import kick
from kick.kvm import Kvm

Command line syntax:
------------------------------------------------------------------------

python <script_name.py> --testbed <testbed_name.yaml

All the user inputs can be given in a topology file.
In topology file at device_list user must specify: kvm (host),
http/tftp server and vm(s).
Each device specific inputs are defined in devices section and will be
referred to in script by device’s index from device_list.
The script uses http or tftp server to download the qcow image.
If the vm name is not provided, the script will use testbed id, build
version and vm type to generate the name

testbed:
...
     device_list:
         -host
         -tftp_server / http_server
         -ftd / fmc
devices:
      host:
                alias:
                type:
      ....
      http_server:
                type: 'linux'
      ....

------------------------------------------------------------------------
Please see kick/kvm/tests/kvm_testbed.yaml files as examples of how to
define a topology file for vFTD and vFMC deployment

Scripts and topology sample file can be accessed in kick.kvm.tests,
e.g: kick/kvm/tests/kvm_ with_testbed.py

Explained example:
------------------------------------------------------------------------

```python
import kick
from kick.kvm.actions import Kvm
from kick.kvm.actions.kvm_constants import InputConstants as IC
import logging
from ats import aetest
from ats import topology
# define logger and logging level
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# define a Kvm instance
kvm_instance = Kvm()
# open an ssh session on kvm; on this session a vm will be created using
# virsh commands
line = kvm_instance.ssh(ip=KVM_IP, port=KVM_PORT, timeout=30)
# deploy a VFTD by providing folder of the buil image
ftd = line.deploy_ftd(day0_config=FTD_DAY0_CONFIG,
      mgmt_mac=FTD_MGMT_MAC, testbed_id=TESTBED_ID,
      network_map=FTD_NETW_MAP, build_path='',
      image_folder=FTD_IMAGE_FOLDER, server_ip=HTTP_IP,
      root_path=HTTP_ROOT_PATH, transfer_protocol=HTTP_PROTOCOL,
      vm_name='')
# wait for ftd to be available
ftd.wait_for_ssh(ip=FTD_IP, port=FTD_PORT)
#check installed version
ftd.check_version(ip=FTD_IP, port=FTD_PORT, build=FTD_BUILD,
    version=FTD_VERSION)
# run a command as root
ftd_line = ftd.ssh(ip=FTD_IP, port=FTD_PORT, timeout=180)
ftd_line.run_as_root('cat /etc/version')
# search for a message in logs
ftd.log_checks(ip=FTD_IP, port=FTD_PORT, list_files=FTD_FILES,
    search_strings=FTD_SEARCH_WORDS, exclude_strings=FTD_EXCLUDE_WORDS,
    timeout=120)
# delete ftd
line.destroy(ftd.vm_name)
#OR
# deploy a ftd from a developer's build (user must provide absolute path)
ftd = line.deploy_ftd(day0_config=FTD_DAY0_CONFIG, mgmt_mac=FTD_MGMT_MAC,
                      testbed_id=TESTBED_ID, network_map=FTD_NETW_MAP,
                      build_path=FTD_IMAGE_PATH, vm_name='')
... # same methods like above
#OR
# deploy a VFMC b providing folder of the buil image
fmc = line.deploy_fmc(day0_config=FMC_DAY0_CONFIG, mgmt_mac=FMC_MGMT_MAC,
                      testbed_id=TESTBED_ID, network_map=FMC_NETW_MAP,
                      image_folder=FMC_IMAGE_FOLDER, server_ip=HTTP_IP,
                      root_path=HTTP_ROOT_PATH, transfer_protocol=HTTP_PROTOCOL,
                      vm_name='')
#... same methods like for VFTD
#...
# load yaml into a testbed object  and read all the variables
tb = topology.loader.load(yamlfile)
TESTBED_ID = tb.name
#...
```
