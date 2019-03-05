VMWare Module Readme
==============================================

1 - Module overview
----------------------------------------------
GCP and PCloud related VM operation.

The following files contain public functions for users:

* vmware.py

This library allows users to deploy devices in a GCP and PCloud environment. The basic work
flow is explained in the examples below.

This file will be split in:
    
    1. Public method and public classes provided by the module
    2. Sample code

----------------------------------------------
2 - Public method and public classes provided by the module
----------------------------------------------
class Vcenter
```python
class Vcenter:
    """Vcenter class.

    """

    def __init__(self, site_url, username, password):
        """

        :param site_url: string - url of desired vcenter
        :param username: string - username to connect to vcenter
        :param password: string - the password for given user

        """
       
    def connect_to_vcenter(self):
        """Connect to the ServiceInstance (vCenter)

        :return: None

        """
        
    def disconnect_from_vcenter(self):
        """Disconnects the server instance.

        """
        
    def second_authentication(f):
        """The following function calls, if after a long delay, may timeout and
        generate an exception: pyVmomi.VmomiSupport.NotAuthenticated.

        This decorator will try again if the above is seen.

        :return: a decorated function

        """
        
    @second_authentication
    def get_obj(self, vimtype, name, root=None, create=True):
        """

        :param vimtype: the type of searched object
        :param name: the name of searched object
        :param root: the containing folder of searched object
        :param create: if founded folder isn't found it will be created if this param is set
        :return: an object by name, if name is None the first found object is returned.
                 this method also can search an object if a path is given by the user

        """
        
    @staticmethod
    def _wait_for_task(task):
        """Wait for a vCenter task to finish.
    
        :param task: the task which was started
        :return: the status of the action

        """
        
    @staticmethod
    def duration(start):
        """

        :param start: the time when action was started
        :return: the difference of time between start and when the method is called

        """
        
    @staticmethod
    def _upload_with_progress(file_object, lease, chunk_size=4096,total_size=None):
        """Generator to update an NFC lease while uploading a file.

        Keeps track of progress of uploading a file, updating the lease
        to both keep it alive, and show status in VI

        :param file_object: File object for what is being uploaded
        :param lease: vim.HttpNfcLease object to be updated for the upload
        :param chunk_size: integer for number of bytes to read at a time
        :param total_size: integer for number of total bytes to be uploaded
        :return: chunks of the file which is uploaded

        """
        
    @second_authentication
    def deploy_ovf_generic(self, datastore_obj, resource_pool_obj, vm_folder_obj,
                           vm_name, ovf_location, network_name_map=None,
                           property_name_map=None, force_create=False, vm_mac=None, datacenter_obj=None):
        """

        :param datacenter_obj: object pointing to datacenter
        :param datastore_obj: object pointing to the datastore
        :param resource_pool_obj: object pointing to the resource pool
        :param vm_folder_obj: object pointing to the vm_in_pod folder
        :param vm_name: string - name of the VM to deploy in VI
        :param ovf_location: string - path to the ovf file to deploy_ovf or to the *.ova file
        :param network_name_map: dict of interface name to vlan name (optional parameter)
        :param property_name_map: dict, it specifies the ip mapping of the vm (optional parameter)
        :param force_create: bool - if set to true the existing vm with same name will be deleted then deployed
                (optional parameter)
        :param vm_mac: string - explicit MAC address for deployed VM (optional parameter)
        :return: a Vm obj

        """
        
    @staticmethod
    def _get_path(folder, stop_folder):
        """

        :param folder: the folder where the deply was done
        :param stop_folder: usually the resource pool(the folder where the method should stop with path reconstruction)
        :return: relative path from deploy folder up to what folder you give

        """
        
    @staticmethod
    def _get_datacenter(obj):
        """Receives an object from vcenter and goes up to the datacenter

        :param obj: pyvmomi object(in vcenter hierarchy should be child of datacenter so this method will work
        :return: Datacenter object

        """
        
    @second_authentication
    def clone_vm_generic(self, source_vm_obj, dest_vm_name, datastore_obj,
                         resource_pool_obj, vm_folder_obj, create_template,
                         power_on=False, force_create=False, datacenter_obj=None):
        """Clone operation with a VM or a template.
                         power_on=False):

        Clone operation with a VM or a template.

        :param source_vm_obj: object pointing to the VM/Template used as source
        :param dest_vm_name: the name of the VM/Template used as destination
        :param datastore_obj: object pointing to the datastore
        :param resource_pool_obj: object pointing to the resource pool
        :param vm_folder_obj: object pointing to the vm_in_pod folder
        :param create_template: True/False, whether destination is a template
        :param power_on: True/False, whether to power on after clone.
        :param force_create: True/False
        :param datacenter_obj: object pointing to datacenter

        :return: vm_in_pod obj

        """
        
    @second_authentication
    def vm_is_present(self, vm_name, vm_folder_name=None):
        """Check if a VM is present inside a vm_folder.

        :param vm_name: name of the searched vm
        :param vm_folder_name: location of the searched vm
        :return: True or False

        """        
```
class Vm
```python
class Vm:
    """Object that maps and manages a virtual machine.

    """
    def __init__(self, vcenter, vm_name, vm_folder_name=None, datacenter=None):
        """Constructor of Vm() instance.

        :param vcenter: Vcenter object this VM is in
        :param vm_name: name of vmware
        :param vm_folder_name: ex: 'FULGRP0204 - ful-vmw-automation-gcplab'
        :param datacenter: the datacenter object

        """
        
    def update_vm_obj(self, vm_folder=None, datacenter=None):
        """

        :param vm_folder: location of vmware
        :param datacenter: datacenter object
        :return: None

        """
        
    def second_authentication(f):
        """The following function calls, if after a long delay, may timeout and
        generate an exception: pyVmomi.VmomiSupport.NotAuthenticated.

        This decorator will try again if the above is seen.

        :return: a decorated function

        """
        
    @second_authentication
    def rename(self, new_name):
        """Triggers the renaming of the virtual machine.

        :param new_name: the new name of vmware
        :return: None

        """
    
    @second_authentication
    def power_on(self):
        """Triggers the powering of the virtual machine.

        :return: None

        """
        
    @second_authentication
    def power_off(self):
        """Triggers the powering off of the virtual machine.

        :return: None

        """
        
    @second_authentication
    def destroy(self, rp=None, vf=None):
        """Deletes the virtual machine.

        :param: rp: resource pool object
        :param: vf: vm folder obj
        :return: None

        """
        
    @second_authentication
    def connect_to_vlan(self, vlan_name, interface_name='', mac_address='', distributed=True):
        """Connects the specified virtual network adapter specified by either
        interface name or mac address to the specified VLAN.

        :param si: vim.ServiceInstance - aka the connection to the VI
        :param vlan_name: the name of the vlan
        :param interface_name: the name of the virtual network interface
            (either the interface name or the mac address is needed)
        :param mac_address: the MAC address. (either the interface name or the mac address is needed)
        :param distributed: if True, it connects to a VDS (distributed portgroup),
            else to a VSS (standard switch)
        :return: None

        """
        
    @second_authentication
    def clear_vlan(self, interface_name='', mac_address=''):
        """Resets the VLAN connection to 'local'.

        :param interface_name: the name of the network adapter interface.
            (either this or the MAC address must be specified)
        :param mac_address: the mac address of the network adapter
            (either this or the interface name must be specified)
        :return: None

        """
        
    @second_authentication
    def get_mac_addresses(self):
        """Retrieves a dictionary with all the network devices with their corresponding MAC addresses.

        :return: a dictionary containing all the network devices with their corresponding MAC address, using the
                 interface name as the dictionary key.

        """
        
    @second_authentication
    def get_mac_address(self, interface_name):
        """Retrieves the MAC address of the network device with the given interface name.

        :param interface_name: the interface name of the network device
        :return: the MAC address of the network device or None if it was not found.

        """
        
    @second_authentication
    def get_summary(self):
        """Retrieves the Summary state information of the vm_in_pod.

        :return: the summary of vm_in_pod

        """
        
    @second_authentication
    def add_nic(self, vlan, distributed=True):
        """Creates a new Ethernet Adapter with the associated vlan.

        :param vlan: vlan name (such as "local") to associate adapter with
        :param distributed: if True, it connects to a VDS (distributed portgroup),
            else to a VSS (standard switch)

        """
        
    @second_authentication
    def update_virtual_nic_state(self, nic_number, new_nic_state):
        """

        :param nic_number: Network Interface Controller Number
        :param new_nic_state: Either 'connect', 'disconnect' or 'delete'
        :return: True if success

        """
        
    @second_authentication
    def create_snapshot(self, snapshot_name, description=None):
        """

        :param snapshot_name: name for created snapshot
        :param description:   describe the snapshot

        """
        
    @second_authentication
    def remove_snapshot(self, snapshot_name):
        """
        
        :param snapshot_name: name of snapshot to be deleted

        """
```
----------------------------------------------
3 - Sample code
----------------------------------------------
Deploy OVF
```python
from pyVmomi import vim
from kick.vmware.vmware import Vcenter, Vm
import logging
    
logger = logging.getLogger(__name__)
    
k_logger = logging.getLogger('kick')
k_logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
k_logger.addHandler(ch)
    
def deploy_ovf_test():
    """deploy a vmware from ovf.

    :return: a Vm() instance

    """

    # Constants
    SITE_URL = 'sja-vc01.cisco.com'
    USERNAME = 'some_username'
    PASSWORD = 'some_password'
    RESOURCE_POOL_NAME = 'SJAGRP0205 - sja-kick-pod'
    VM_FOLDER_NAME = 'SJAGRP0205 - sja-kick-pod'
    VM_NAME = 'vm_test'
    OVF_LOCATION = 'http://172.23.47.63/tiny.ovf'
    
    # create a Vcenter object
    vcenter = Vcenter(SITE_URL, USERNAME, PASSWORD)
    
    # select a vlan
    network_name_map = {
        'External-VM-Network': 'SJAGRP0205-sja-kick-pod-MGMT-1064'
    }

    # fill in datastore (ds), resource_pool (rp), vm_folder (vf), etc.
    # get storage pod from Vcenter
    sp = vcenter.get_obj([vim.StoragePod], 'GCP-Pods')
    # select datastore that has the most free space
    ds = sorted(sp.childEntity, key=lambda store: store.summary.freeSpace,
                reverse=True)[0]
    # get the resource pool object
    rp = vcenter.get_obj([vim.ResourcePool], RESOURCE_POOL_NAME)
    # get the folder where the VM will be deployed
    vf = vcenter.get_obj([vim.Folder], VM_FOLDER_NAME)

    # test that there isn't a vmware with that name already
    try:
        vcenter.get_obj([vim.VirtualMachine], VM_NAME, vf)
    except RuntimeError:
        # got RuntimeError - this is good
        pass
    else:
        raise RuntimeError("vmware {} already exists".format(VM_NAME))

    # start the deploy 
    vm = vcenter.deploy_ovf_generic(ds, rp, vf, VM_NAME, OVF_LOCATION,
                                    network_name_map)

    # return the deployed VM
    return vm
    
    # The script also knows to deploy from an *.ova file, so insted of the path or url to ovf it can 
    # be put a path ot url to an *.ova 
    # for ex: OVF_LOCATION = 'http://some_file_server_name/somefile.ova'
    
    
    # for more examples please see kick/vmware/sample_tests
```
