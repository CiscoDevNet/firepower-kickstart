import ssl
from pyVmomi import vim
from pyVmomi import vmodl
from pyVim import connect
from time import sleep
import requests
import os.path
import logging
import urllib.request
from functools import wraps
import time
import socket
from .ova_deploy import *


logger = logging.getLogger(__name__)


class Vcenter:
    """Vcenter class.

    """

    def __init__(self, site_url, username, password):
        """

        :param site_url: string - url of desired vcenter
        :param username: string - username to connect to vcenter
        :param password: string - the password for given user

        """

        self.site_url = site_url
        self.username = username
        self.password = password
        self.si = None
        self.content = None
        self.connect_to_vcenter()

    def connect_to_vcenter(self):
        """Connect to the ServiceInstance (vCenter)

        :return: None

        """

        context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        context.verify_mode = ssl.CERT_NONE

        logger.info('Creating service instance in Vcenter class.')
        si = connect.SmartConnect(host=str(self.site_url), user=self.username,
                                  pwd=str(self.password), sslContext=context)

        self.si = si
        self.content = si.RetrieveContent()

    def disconnect_from_vcenter(self):
        """Disconnects the server instance.

        """

        logger.info('Disconnecting service instance.')
        connect.Disconnect(self.si)

    def second_authentication(f):
        """The following function calls, if after a long delay, may timeout and
        generate an exception: pyVmomi.VmomiSupport.NotAuthenticated.

        This decorator will try again if the above is seen.

        :return: a decorated function

        """

        @wraps(f)
        def decorated_function(self, *args, **kwargs):
            try:
                return f(self, *args, **kwargs)
            except vim.fault.NotAuthenticated as e:
                logger.info("authentication may have time out. trying again.")
                self.connect_to_vcenter()
                return f(self, *args, **kwargs)

        return decorated_function

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

        check = False
        path = ''
        if name and os.path.basename(name) != name:
            check = True
            path, name = os.path.split(name)
            path = '/'.join(path.split('/')[::-1])
            while path:
                path, folder = os.path.split(path)
                root = self.get_obj([vim.Folder], folder, root=root, create=create)

        if not root:
            root = self.content.rootFolder

        try:
            container = self.content.viewManager.CreateContainerView(root, vimtype, True)

        except:
            raise Exception('Given path isn\'t good')

        for c in container.view:
            if name:
                if c.name == name:
                    if check:
                        if c.parent == root:
                            logger.debug("found obj {}".format(c.name))
                            return c
                    else:
                        if vimtype == [vim.Network]:
                            if path.lower() in c.parent.name.lower():
                                logger.debug("found network {}".format(c.name))
                                return c
                        else:
                            logger.debug("found obj {}".format(c.name))
                            return c
            else:
                logger.debug("found obj {}".format(c.name))
                return c
        else:
            # nothing is found
            if vimtype == [vim.Folder]:
                if create:
                    logger.debug("creating folder {}".format(name))
                    try:
                        return root.CreateFolder(name)
                    except vim.fault.DuplicateName as e:
                        return e.object
            raise RuntimeError("not found for type {}, name {}.".format(vimtype,
                                                                        name))

    @staticmethod
    def _wait_for_task(task):
        """Wait for a vCenter task to finish.

        :param task: the task which was started
        :return: the status of the action

        """

        while True:
            if task.info.state == 'success':
                return task.info.result

            if task.info.state == 'error':
                logger.error("there was an error")
                raise Exception('Error in _wait_for_task({})'.format(task))

    @staticmethod
    def duration(start):
        """

        :param start: the time when action was started
        :return: the difference of time between start and when the method is called

        """
        return int(time.time() - start)

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

        # Figure out our total file size
        if total_size is None:
            logger.debug('Finding total size of file')
            total_size = file_object.seek(0, 2)
            file_object.seek(0, 0)
        logger.debug('File size: {}'.format(total_size))

        # Counters for how much data we have read, and
        # status on when we last updated.
        data_read = 0
        last_progress = 0

        start = time.time()
        store = 0
        # Read until we are done
        while True:
            data = file_object.read(chunk_size)

            # Check lease once every 5 seconds
            if int(time.time() - start) % 5 == 0 and int(time.time() - start) != store:
                store = int(time.time() - start)
                if lease.state == 'error':
                    raise Exception('Lease state returned error!')

            if not data:
                logger.debug('Done reading file')
                break

            # Update how much data we have read and calculate
            # current percentage completed
            data_read += chunk_size
            current_progress = int(100 * data_read / total_size)

            # Update the lease if we've changed progress
            if current_progress > last_progress:
                logger.debug('Total data read: {}'.format(data_read))
                logger.debug('Current upload progress {}%'.format(current_progress))
                lease.HttpNfcLeaseProgress(current_progress)
                logger.debug('NFC lease updated')
                last_progress = current_progress

            # Yield our chunk of data
            yield data

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
        :param network_name_map: dict of interface name to vlan name (
        optional parameter), or it can be a dict of interface name to
        vim.Network.
        :param property_name_map: dict, it specifies the ip mapping of the vm (optional parameter)
        :param force_create: bool - if set to true the existing vm with same name will be deleted then deployed
                (optional parameter)
        :param vm_mac: string - explicit MAC address for deployed VM (optional parameter)
        :return: a Vm obj

        """

        # if datacenter wasn't given as parameter try to find it
        if not datacenter_obj:
            try:
                datacenter_obj = self._get_datacenter(datastore_obj)
            except:
                pass

        # Convert network_name_map and property_name_map
        if not network_name_map: network_name_map = dict()
        if not property_name_map: property_name_map = dict()

        try:
            # search for vm
            self.get_obj([vim.VirtualMachine], vm_name, vm_folder_obj)
        except RuntimeError:
            pass
        else:
            if force_create:
                # if already exist a vm with the given name, delete it
                found_vm = Vm(self, vm_name, vm_folder_obj, datacenter_obj)
                found_vm.power_off()
                found_vm.destroy()
            else:
                raise RuntimeError("vmware {} already exists".format(vm_name))

        logger.info('converting network_name_map - this may take a min')
        logger.debug('converting network_name_map: {}'.format(network_name_map))
        network_map = []
        for if_name, vlan_name in network_name_map.items():
            if isinstance(vlan_name, vim.Network):
                logger.debug('Network received as object vim.Network, no need to search it.')
                print ("VLAN name type",type(vlan_name))
                network_map.append(vim.OvfNetworkMapping(name=if_name, network=vlan_name))
                vlan_name_is_object = True
            elif isinstance(vlan_name, str):
                vlan_name_is_object = False
                if vlan_name and os.path.basename(vlan_name) != vlan_name:
                    try:
                        switch_folder = self.get_obj([vim.Folder], os.path.dirname(vlan_name),
                                              datacenter_obj, create=False)
                        network = self.get_obj([vim.Network], os.path.basename(vlan_name), switch_folder, create=False)
                    except RuntimeError:
                        network = self.get_obj([vim.Network], os.path.basename(vlan_name), datacenter_obj.networkFolder, create=False)
                else:
                    network = self.get_obj([vim.Network], vlan_name, datacenter_obj.networkFolder, create=False)
                network_map.append(vim.OvfNetworkMapping(name=if_name, network=network))
            else:
                logger.error('Unknown type to convert for network map')
                raise Exception('Unknown type: {}'.format(type(vlan_name)))

        logger.debug('network_name_map converted to: {}'.format(network_map))

        logger.info('converting property_name_map - this may take a few minutes')
        logger.debug('converting property_name_map: {}'.format(property_name_map))
        property_map = []
        for key, value in property_name_map.items():
            property_map.append(vim.KeyValue(key=key, value=value))
        logger.debug('property_name_map converted to: {}'.format(property_map))

        # Create the import spec
        # to save disk, we only deploy with thin provisioning
        logger.debug('Creating OVF Import Spec Parameters')
        spec_params = vim.OvfManager.CreateImportSpecParams(
            entityName=vm_name,
            diskProvisioning='thin',
            networkMapping=network_map,
            propertyMapping=property_map)

        # Read our OVF to get the OVF descriptor for import
        logger.debug('Reading OVF Descriptor at {}'.format(ovf_location))
        ovf_ova = False
        if ovf_location.endswith('.ova'):
            ovf_handle = OvfHandler(ovf_location, '.ovf')
            ovfd = ovf_handle.descriptor
            ovf_ova = True

        else:
            if any(ovf_location.startswith(prefix) for prefix in ['http', 'ftp']):
                # open ovf file from http
                try:
                    with urllib.request.urlopen(ovf_location) as ovf:
                        ovfd = ovf.read().decode('utf-8')
                        ovf.close()
                except urllib.error.HTTPError as err:
                    logger.error("Cannot access {}".format(ovf_location))
                    raise err

            else:
                # open ovf file from local path
                try:
                    with open(ovf_location, 'r') as ovf:
                        ovfd = ovf.read()
                except FileNotFoundError as err:
                    logger.error("Cannot access {}".format(ovf_location))
                    raise err

        # Prepare the OVF import
        logger.debug('Creating OVF Import Spec')
        manager = self.content.ovfManager
        spec_result = manager.CreateImportSpec(ovfd, resource_pool_obj,
                                               datastore_obj, spec_params)
        logger.debug("spec_result after CreateImportSpec:\n{}".format(
            spec_result))

        ram_memory = spec_result.importSpec.configSpec.memoryMB if spec_result.importSpec.configSpec.memoryMB > 8192 else 8192
        spec_result.importSpec.configSpec.memoryMB = int(property_name_map.get("memoryMB", ram_memory))
        index = 0
        for dev in spec_result.importSpec.configSpec.deviceChange:
            if isinstance(dev, vim.vm.device.VirtualDeviceSpec) and \
                    isinstance(dev.device, vim.vm.device.VirtualE1000) \
                    and dev.device.connectable.startConnected is False:
                dev.device.connectable.startConnected = True
            if isinstance(dev, vim.vm.device.VirtualDeviceSpec) and \
                    isinstance(dev.device, vim.vm.device.VirtualE1000) \
                    and vm_mac is not None and index == 0:
                        dev.device.addressType = 'Manual'
                        dev.device.macAddress = vm_mac
                        index +=1
            if isinstance(dev, vim.vm.device.VirtualDeviceSpec) and \
                    isinstance(dev.device, vim.vm.device.VirtualE1000):
                        # unset device name, that will be set on HOLDING later
                        found = False
                        for if_name, vlan_name in network_name_map.items():
                            if (hasattr(dev.device.backing, 'port') or (hasattr(dev.device.backing, 'deviceName') and dev.device.backing.deviceName == (vlan_name.name if vlan_name_is_object else vlan_name))):
                                found = True
                        if not found:
                            logger.debug("Clear vlan {} from network adapter".format(dev.device.backing.deviceName))
                            dev.device.backing.deviceName = ''

        # Start the import process.  Wait for the lease to finish initializing
        # and make sure it goes to ready state
        logger.debug('Beginning OVF import process')
        lease = resource_pool_obj.ImportVApp(spec=spec_result.importSpec,
                                             folder=vm_folder_obj)
        logger.debug('Waiting for NFC lease to leave initializing state')
        while lease.state == 'initializing':
            sleep(.5)
        logger.debug('NFC lease has left initializing state')
        if lease.state != 'ready':
            logger.debug('NFC lease did not enter ready state state, lease state is {}'.format(str(lease.state)))
            raise Exception('Import OVF Lease failed to enter ready state')
        logger.debug('NFC lease ready for file uploads')

        headers = {'Content-Type': 'application/x-vnd.vmware-streamVmdk'}
        # TODO: Properly update progress for multiple VMDKs
        logger.debug('Searching for file URLs to upload')
        total_size = sum([file.size for file in spec_result.fileItem])
        for deviceUrl in lease.info.deviceUrl:
            for fileItem in spec_result.fileItem:
                if fileItem.deviceId == deviceUrl.importKey:
                    if ovf_ova:
                        vmdk = OvfHandler(ovf_location, fileItem.path)
                        vmdk_path = vmdk.ovffile
                        url = deviceUrl.url
                        requests.post(
                            url,
                            data=self._upload_with_progress(vmdk_path,
                                                            lease,
                                                            total_size=total_size),
                            headers=headers,
                            verify=False
                        )
                    else:
                        vmdk_path = os.path.join(os.path.dirname(ovf_location),
                                                 fileItem.path)
                        logger.debug('Found VMDK to upload: {}'.format(vmdk_path))
                        url = deviceUrl.url
                        logger.info('Uploading VMDK to : {} - this may take a while'.format(url))

                        if any(vmdk_path.startswith(prefix) for prefix in ['http',
                                                                           'ftp']):
                            with urllib.request.urlopen(vmdk_path) as response:
                                requests.post(
                                    url,
                                    data=self._upload_with_progress(response,
                                                                    lease,
                                                                    total_size=total_size),
                                    headers=headers,
                                    verify=False
                                )
                        else:
                            # open vmdk file from local path
                            with open(vmdk_path, 'rb') as f:
                                logger.debug('Beginning VMDK upload')
                                requests.post(
                                    url,
                                    data=self._upload_with_progress(f, lease,
                                                                    total_size=total_size),
                                    headers=headers,
                                    verify=False
                                    )

                    logger.debug('VMDK upload completed')

        logger.debug('All VMDK uploads complete')
        lease.HttpNfcLeaseComplete()
        logger.debug('NFC Lease completed')

        # find the created VM
        path = self._get_path(vm_folder_obj, resource_pool_obj)
        vm = Vm(self, vm_name, path, datacenter_obj)
        return vm

    @staticmethod
    def _get_path(folder, stop_folder):
        """

        :param folder: the folder where the deply was done
        :param stop_folder: usually the resource pool(the folder where the method should stop with path reconstruction)
        :return: relative path from deploy folder up to what folder you give

        """

        path = ''
        current_folder = folder
        while folder.name != stop_folder.name:
            path = os.path.join(folder.name, path)
            folder = folder.parent
            if folder is None:
                return current_folder
        return os.path.normpath(os.path.join(stop_folder.name, path))

    @staticmethod
    def _get_datacenter(obj):
        """Receives an object from vcenter and goes up to the datacenter

        :param obj: pyvmomi object(in vcenter hierarchy should be child of datacenter so this method will work
        :return: Datacenter object

        """

        while type(obj) is not vim.Datacenter and obj is not None:
            obj = obj.parent
        return obj

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

        # if datacenter wasn't given as parameter try to find it
        if not datacenter_obj:
            try:
                datacenter_obj = self._get_datacenter(datastore_obj)
            except:
                pass

        target = 'template' if create_template else 'vm_in_pod'
        logger.info('Cloning {} into {} as a {}'.format(source_vm_obj.name,
                                                        dest_vm_name,
                                                        target))

        try:
            # search for vm
            self.get_obj([vim.VirtualMachine], dest_vm_name, vm_folder_obj)
        except RuntimeError:
            pass
        else:
            if force_create:
                # if already exist a vm with the given name, delete it
                found_vm = Vm(self, dest_vm_name, vm_folder_obj, datacenter_obj)
                found_vm.power_off()
                found_vm.destroy()
            else:
                raise RuntimeError("vmware {} already exists".format(dest_vm_name))

        # check if VM is powered on
        if source_vm_obj.runtime.powerState == \
                vim.VirtualMachinePowerState.poweredOn:
            raise Exception('Error: VM must be powered off before cloning.')

        # create relocate spec
        relocate_spec = vim.vm.RelocateSpec()
        relocate_spec.datastore = datastore_obj
        relocate_spec.pool = resource_pool_obj

        # create clone spec
        clone_spec = vim.vm.CloneSpec()
        clone_spec.location = relocate_spec

        # if it should be powered on after clone
        clone_spec.powerOn = power_on
        clone_spec.template = create_template

        task = source_vm_obj.Clone(vm_folder_obj, name=dest_vm_name,
                                   spec=clone_spec)

        logger.debug('Cloning VM ...')
        self._wait_for_task(task)

        # find the created VM
        path = self._get_path(vm_folder_obj, resource_pool_obj)
        vm = Vm(self, dest_vm_name, path, datacenter_obj)
        return vm

    @second_authentication
    def vm_is_present(self, vm_name, vm_folder_name=None):
        """Check if a VM is present inside a vm_folder.

        :param vm_name: name of the searched vm
        :param vm_folder_name: location of the searched vm
        :return: True or False

        """

        vf = self.get_obj([vim.Folder], vm_folder_name)
        try:
            self.get_obj([vim.VirtualMachine], vm_name, vf)
        except RuntimeError:
            return False
        else:
            return True

    @second_authentication
    def find_lightest_datastore(self, storage_pod_obj):
        """
        From the storage pod, find the least used datastore.
        :return: the least used datastore obj. (of type vim.Datastore)
        """
        ds = sorted(storage_pod_obj.childEntity, key=lambda store:
                    store.summary.freeSpace, reverse=True)

        return ds[0]


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

        self.vcenter = vcenter
        self.vm_name = vm_name
        self.vm_folder_name = vm_folder_name
        self.vm_obj = None
        self.update_vm_obj(vm_folder_name, datacenter)

    def update_vm_obj(self, vm_folder=None, datacenter=None):
        """

        :param vm_folder: location of vmware
        :param datacenter: datacenter object
        :return: None

        """

        try:
            self.vm_obj = self.vcenter.get_obj([vim.VirtualMachine], self.vm_name, vm_folder)
        except Exception:
            vm_folder_obj = self.vcenter.get_obj([vim.Folder], vm_folder,
                                                 datacenter.vmFolder if datacenter is not None
                                                 else None)
            self.vm_obj = self.vcenter.get_obj([vim.VirtualMachine], self.vm_name, vm_folder_obj)

    def set_memory_reservation(self, value):
        """ Set the memory reservation for a specific vm
        : param value: int value of the memory reservation in MB
        """
        spec = vim.vm.ConfigSpec()
        rai =  vim.ResourceAllocationInfo()
        rai.reservation = value
        spec.memoryAllocation = rai

        task = self.vm_obj.ReconfigVM_Task(spec=spec)
        while task.info.state == 'running':
            time.sleep(.5)

    def second_authentication(f):
        """The following function calls, if after a long delay, may timeout and
        generate an exception: pyVmomi.VmomiSupport.NotAuthenticated.

        This decorator will try again if the above is seen.

        :return: a decorated function

        """

        @wraps(f)
        def decorated_function(self, *args, **kwargs):
            try:
                return f(self, *args, **kwargs)
            except vim.fault.NotAuthenticated as e:
                logger.info("authentication may have time out due to {}. trying again.".format(e))
                self.vcenter.connect_to_vcenter()
                self.update_vm_obj()
                return f(self, *args, **kwargs)
            except vmodl.fault.ManagedObjectNotFound as e:
                logger.info("authentication may have time out due to {}. trying again.".format(e))
                self.vcenter.connect_to_vcenter()
                self.update_vm_obj()
                return f(self, *args, **kwargs)

        return decorated_function

    @second_authentication
    def rename(self, new_name):
        """Triggers the renaming of the virtual machine.

        :param new_name: the new name of vmware
        :return: None

        """

        logger.info('Renaming VM {} to "{}".'.format(self.vm_name, new_name))
        task = self.vm_obj.Rename_Task(new_name)
        while task.info.state == 'running':
            sleep(.5)
        self.vm_name = new_name

    @second_authentication
    def power_on(self):
        """Triggers the powering of the virtual machine.

        :return: None

        """

        logger.info('Powering ON the VM "{}".'.format(self.vm_name))
        if self.vm_obj.runtime.powerState != \
                vim.VirtualMachinePowerState.poweredOn:
            task = self.vm_obj.PowerOnVM_Task()
            while task.info.state == 'running':
                sleep(.5)

        if self.vm_obj.runtime.powerState != \
                vim.VirtualMachinePowerState.poweredOn:
            logger.info("VM not powered on yet - it may come on later, "
                        "or it may fail eventually.")
        else:
            logger.debug('Powered ON the VM "{}".'.format(self.vm_name))

    @second_authentication
    def power_off(self):
        """Triggers the powering off of the virtual machine.

        :return: None

        """

        logger.info('Powering OFF the VM "{}".'.format(self.vm_name))
        if self.vm_obj.runtime.powerState != vim.VirtualMachinePowerState.poweredOff:
            off_task = self.vm_obj.PowerOffVM_Task()
            while off_task.info.state != 'success':
                sleep(.5)

        if self.vm_obj.runtime.powerState != \
                vim.VirtualMachinePowerState.poweredOff:
            logger.info("VM not powered off yet - it may come off later, "
                        "or it may fail eventually.")
        else:
            logger.debug('Powered OFF the VM "{}".'.format(self.vm_name))

    @second_authentication
    def destroy(self, rp=None, vf=None):
        """Deletes the virtual machine.

        :param: rp: resource pool object
        :param: vf: vm folder obj
        :return: None

        """

        logger.info('Deleting the VM "{}".'.format(self.vm_name))
        destroy_task = self.vm_obj.Destroy_Task()
        while destroy_task.info.state != 'success':
            sleep(.5)
        if vf and rp:
            while vf.name != rp.name:
                if len(vf.childEntity) == 0:
                    logger.info('Deleting folder "{}".'.format(vf.name))
                    try:
                        temp = vf.parent
                        destroy_task = vf.UnregisterAndDestroy_Task()
                        while destroy_task.info.state != 'success':
                            sleep(.5)
                    except:
                        pass
                    vf = temp
                else:
                    break

    @second_authentication
    def connect_to_vlan(self, vlan_name, interface_name='', mac_address='', distributed=True, root=None):
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

        # search for the network adapter
        nic = None
        logger.info('Searching for network adapter.')
        for device in self.vm_obj.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                if device.macAddress == mac_address or device.deviceInfo.label == interface_name:
                    nic = device
                    break

        if not nic:
            raise Exception('Specified adapter was not found.')

        # initialize device spec
        nic_spec = vim.vm.device.VirtualDeviceSpec()
        nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
        nic_spec.device = nic
        nic_spec.device.wakeOnLanEnabled = nic.wakeOnLanEnabled

        # configure device spec using new values
        if not distributed:
            logger.info('Searching for VLAN object ' + str(vlan_name))
            network = self.vcenter.get_obj([vim.Network], vlan_name)
            if not network:
                logger.error('VLAN was not found.')
                raise Exception('VLAN was not found.')
            nic_spec.device.backing = \
                vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
            nic_spec.device.backing.network = network
            nic_spec.device.backing.deviceName = vlan_name
        else:
            logger.info('Searching for VLAN object (distributed) ' + str(vlan_name))
            network = self.vcenter.get_obj(
                [vim.dvs.DistributedVirtualPortgroup], vlan_name, root=root)
            if not network:
                logger.error('VLAN was not found (distributed).')
                raise Exception('VLAN was not found (distributed).')
            nic_spec.device.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo()
            dvs_port_connection = vim.dvs.PortConnection()
            dvs_port_connection.portgroupKey = network.key
            dvs_port_connection.switchUuid = network.config.distributedVirtualSwitch.uuid
            nic_spec.device.backing.port = dvs_port_connection

        # set connectivity settings
        nic_spec.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        nic_spec.device.connectable.startConnected = True
        nic_spec.device.connectable.connected = True
        nic_spec.device.connectable.allowGuestControl = True

        # start reconfiguration task
        logger.info('Reconfigure virtual network adapter.')
        config_spec = vim.vm.ConfigSpec(deviceChange=[nic_spec])
        task = self.vm_obj.ReconfigVM_Task(config_spec)
        while task.info.state == 'running':
            sleep(.5)

    @second_authentication
    def clear_vlan(self, interface_name='', mac_address=''):
        """Resets the VLAN connection to 'local'.

        :param interface_name: the name of the network adapter interface.
            (either this or the MAC address must be specified)
        :param mac_address: the mac address of the network adapter
            (either this or the interface name must be specified)
        :return: None

        """

        self.connect_to_vlan('local', interface_name, mac_address, False)

    @second_authentication
    def get_mac_addresses(self):
        """Retrieves a dictionary with all the network devices with their corresponding MAC addresses.

        :return: a dictionary containing all the network devices with their corresponding MAC address, using the
                 interface name as the dictionary key.

        """

        ret = {}

        logger.info('Retrieving the DHCP leases list.')
        for device in self.vm_obj.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                ret[device.deviceInfo.label] = device.macAddress

        return ret

    @second_authentication
    def get_mac_address(self, interface_name):
        """Retrieves the MAC address of the network device with the given interface name.

        :param interface_name: the interface name of the network device
        :return: the MAC address of the network device or None if it was not found.

        """

        logger.debug('Searching for MAC address for interface "{}".'.format(interface_name))
        return self.get_mac_addresses().get(interface_name)

    @second_authentication
    def _get_port_id(self, intf_name):
        """
        Find port ID for an interface.

        :param intf_name: 'Network adapter 1'
        :return: port ID, such as 112063
        """

        for dev in self.vm_obj.config.hardware.device:
            if isinstance(dev, vim.vm.device.VirtualEthernetCard):
                dev_backing = dev.backing
                if hasattr(dev_backing, 'port'):
                    return dev.backing.port.portKey
        else:
            raise RuntimeError("Cannot find port ID for interface: {}".format(intf_name))

    @second_authentication
    def get_summary(self):
        """Retrieves the Summary state information of the vm_in_pod.

        :return: the summary of vm_in_pod

        """

        return self.vm_obj.summary

    @second_authentication
    def add_nic(self, vlan, distributed=True):
        """Creates a new Ethernet Adapter with the associated vlan.

        :param vlan: vlan name (such as "local") to associate adapter with
        :param distributed: if True, it connects to a VDS (distributed portgroup),
            else to a VSS (standard switch)

        """

        spec = vim.vm.ConfigSpec()
        nic_changes = []

        nic_spec = vim.vm.device.VirtualDeviceSpec()
        nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add

        nic_spec.device = vim.vm.device.VirtualE1000()

        nic_spec.device.deviceInfo = vim.Description()
        nic_spec.device.deviceInfo.summary = 'vCenter API test'

        # get the vim object associated with the virtual switch folder
        if not distributed:
            logger.info('Searching for VLAN object.')
            network = self.vcenter.get_obj([vim.Network], vlan)
            if not network:
                logger.error('VLAN was not found.')
                raise Exception('VLAN was not found.')
            nic_spec.device.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
            nic_spec.device.backing.network = network
            nic_spec.device.backing.deviceName = vlan
        else:
            logger.info('Searching for VLAN object.')
            network = self.vcenter.get_obj([vim.dvs.DistributedVirtualPortgroup], vlan)
            if not network:
                logger.error('VLAN was not found.')
                raise Exception('VLAN was not found.')
            nic_spec.device.backing = vim.vm.device.VirtualEthernetCard. \
                DistributedVirtualPortBackingInfo()
            dvs_port_connection = vim.dvs.PortConnection()
            dvs_port_connection.portgroupKey = str(network.key)
            dvs_port_connection.switchUuid = str(network.config.distributedVirtualSwitch.uuid)
            nic_spec.device.backing.port = dvs_port_connection

        nic_spec.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        nic_spec.device.connectable.startConnected = True
        nic_spec.device.connectable.allowGuestControl = True
        nic_spec.device.connectable.connected = True
        nic_spec.device.connectable.status = 'untried'
        nic_spec.device.wakeOnLanEnabled = True
        nic_spec.device.addressType = 'assigned'

        nic_changes.append(nic_spec)
        spec.deviceChange = nic_changes
        task = self.vm_obj.ReconfigVM_Task(spec=spec)
        while task.info.state == 'running':
            sleep(.5)

        logger.debug('NIC card added')

    @second_authentication
    def update_virtual_nic_state(self, nic_number, new_nic_state):
        """

        :param nic_number: Network Interface Controller Number
        :param new_nic_state: Either 'connect', 'disconnect' or 'delete'
        :return: True if success

        """

        nic_prefix_label = 'Network adapter '
        nic_label = nic_prefix_label + str(nic_number)
        virtual_nic_device = None
        for dev in self.vm_obj.config.hardware.device:
            if isinstance(dev, vim.vm.device.VirtualEthernetCard) \
                    and dev.deviceInfo.label == nic_label:
                virtual_nic_device = dev
        if not virtual_nic_device:
            raise RuntimeError('Virtual {} could not be found.'.format(nic_label))

        virtual_nic_spec = vim.vm.device.VirtualDeviceSpec()
        virtual_nic_spec.operation = \
            vim.vm.device.VirtualDeviceSpec.Operation.remove \
                if new_nic_state == 'delete' \
                else vim.vm.device.VirtualDeviceSpec.Operation.edit
        virtual_nic_spec.device = virtual_nic_device
        virtual_nic_spec.device.key = virtual_nic_device.key
        virtual_nic_spec.device.macAddress = virtual_nic_device.macAddress
        virtual_nic_spec.device.backing = virtual_nic_device.backing
        virtual_nic_spec.device.wakeOnLanEnabled = \
            virtual_nic_device.wakeOnLanEnabled
        connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        if new_nic_state == 'connect':
            connectable.connected = True
            connectable.startConnected = True
        elif new_nic_state == 'disconnect':
            connectable.connected = False
            connectable.startConnected = False
        else:
            connectable = virtual_nic_device.connectable
        virtual_nic_spec.device.connectable = connectable
        dev_changes = []
        dev_changes.append(virtual_nic_spec)
        spec = vim.vm.ConfigSpec()
        spec.deviceChange = dev_changes
        task = self.vm_obj.ReconfigVM_Task(spec=spec)
        self.vcenter._wait_for_task(task)

    @second_authentication
    def get_esx_host(self):
        """
        Find which esx this vm is currently on.

        :return: esx host name as a string
        """

        return self.vm_obj.summary.runtime.host.name

    @second_authentication
    def migrate(self, esx_host_name):
        """
        Migrate to the specified esx host.

        :param esx_host_name: <string>, such as: u51c12p01esx02.cisco.com
        :return: None
        """

        current_esx_host = self.get_esx_host()
        if socket.gethostbyname(current_esx_host) != \
               socket.gethostbyname(esx_host_name):
            logger.debug("Migrating from {} to {}".format(current_esx_host,
                                                          esx_host_name))
            esx_host = self.vcenter.get_obj([vim.HostSystem], esx_host_name)
            relocate_spec = vim.vm.RelocateSpec(host=esx_host)
            on_task = self.vm_obj.Relocate(relocate_spec)
            while on_task.info.state == 'running':
                sleep(.5)
        else:
            logger.debug("Same host {}, no need to migrate".format(
                esx_host_name))

    @second_authentication
    def create_snapshot(self, snapshot_name, description=None, memory=False, quiesce=True):
        """

        :param snapshot_name: name for created snapshot
        :param description:   describe the snapshot
        :param memory: If set to true a dump of the internal state of the virtual machine (basically a memory dump)
        is included in the snapshot. Memory snapshots consume time and resources, and thus take longer to create.
        When set to FALSE, the power state of the snapshot is set to powered off.
        :param quiesce: If TRUE and the virtual machine is powered on when the snapshot is taken, VMware Tools is used
        to quiesce the file system in the virtual machine. This assures that a disk snapshot represents a consistent
        state of the guest file systems. If the virutal machine is powered off or VMware Tools are not available,
        the quiesce flag is ignored.

        """

        on_task = self.vm_obj.CreateSnapshot_Task(snapshot_name, description,
                                                  memory, quiesce)
        while on_task.info.state == 'running':
            sleep(.5)

    @second_authentication
    def revert_snapshot(self, snapshot_name):
        """
        :param snapshot_name: name of snapshot to be set
        """
        # get root snapshot list
        snapshot = self.vm_obj.snapshot.rootSnapshotList
        while snapshot:
            if snapshot_name == str(list(snapshot)[0].name):
                on_task = list(snapshot)[0].snapshot.RevertToSnapshot_Task()
                while on_task.info.state == 'running' or \
                      on_task.info.state == 'queued':
                    sleep(.5)
                if on_task.info.state == 'success':
                    return True
                return False
            snapshot = list(snapshot)[0].childSnapshotList
        return False

    @second_authentication
    def remove_snapshot(self, snapshot_name):
        """

        :param snapshot_name: name of snapshot to be deleted

        """

        # get root snapshot list
        snapshot = self.vm_obj.snapshot.rootSnapshotList

        while snapshot:
            if snapshot_name == str(list(snapshot)[0].name):
                # if we find a match delete it. Note this will also
                # delete all its children snapshots
                on_task = list(snapshot)[0].snapshot.RemoveSnapshot_Task(True)
                while on_task.info.state == 'running':
                    sleep(.5)
                break

            # check its children
            snapshot = list(snapshot)[0].childSnapshotList
