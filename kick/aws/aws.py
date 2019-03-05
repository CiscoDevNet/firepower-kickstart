
import boto3
import time
import socket
import types

# Added for qcow2 onboarding operations
import os.path
from os import chmod
from stat import S_IRUSR, S_IWUSR
import fabric
from fabric.operations import *
from fabric.context_managers import *

# TEMP
import logging
log = logging.getLogger(__name__)

DEFAULT_KEYPAIR_NAME = 'ngfwv-stager-temp-kp'


def wait_until_ssh_ready(ip, timeout=90):

    while True:

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip, 22))
        if result == 0:
            #print('OPEN')
            break
        else:
            #print( 'CLOSED, errno = ' + str(result) )
            time.sleep(5)


class Tester:

    def __init__(self):
        pass

    def deploy_testbed_from_qcow2s(self, ec2, fmc_qcow2, ftd_qcow2):
        """Tests full deployment, from qcow2 to type1 testbed.

        Args:
            ec2       - Active EC2 session
            fmc_qcow2 - Fully-qualified or relative path/name of the FMCv qcow2 image file
            ftd_qcow2 - Fully-qualified or relative path/name of the FTDv qcow2 image file

        Returns:
            0  - Success
            -1 - An error occurred

        """

        # Setup for onboarding
        onboard_vpc = ec2.add_vpc('ngfwv-ami-stager', '10.0.0.0/16')
        s0 = onboard_vpc.add_subnet('sn0', '10.0.0.0/24')
        keyname = 'ngfwv-stager-temp-kp'
        keyfile = keyname + '.pem'
        key = ec2.add_keypair(keyname)
        key.save(keyfile)

        # Onboard FMC
        fmc_ami_id = onboard_vpc.onboard_fmc(ec2, fmc_qcow2, s0, 'FMCv-full-deploy-test', keyname)
        if fmc_ami_id is None:
            log.error("Failed to onboard FMC: {0}".format(fmc_qcow2))
            onboard_vpc.delete()
            return -1

        # Onboard FTD
        ftd_ami_id = onboard_vpc.onboard_ftd(ec2, ftd_qcow2, s0, 'FTDv-full-deploy-test', keyname)
        if ftd_ami_id is None:
            log.error("Failed to onboard FTD: {0}".format(ftd_qcow2))
            onboard_vpc.delete()
            return -1

        # Clean up onboarding resource
        onboard_vpc.delete()
        ec2.delete_keypair(key)

        # Setup for deployment
        deploy_vpc = ec2.add_vpc('ngfwv-deployer', '10.0.0.0/16')
        keyname = 'ngfwv-deployer-kp'
        keyfile = keyname + '.pem'
        key = ec2.add_keypair(keyname)
        key.save(keyfile)

        # Deploy a testbed
        deploy_vpc.add_ngfw_testbed_type1(fmc_ami_id, keyname, ftd_ami_id, keyname)

        return 0


class Ftd:

    #
    # NOT USED
    #

    def __init__(self, subnet0, subnet1, subnet2, subnet3):
        pass

    def deploy(self):
        if (list(self.vpc.internet_gateways.all()) == []):
            ig = self.add_internet_gateway()
            route_tables = list(self.vpc.route_tables.all())
            route = route_tables[0].create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)

        s0 = self.get_subnet(subnet0)
        s1 = self.get_subnet(subnet1)
        s2 = self.get_subnet(subnet2)
        s3 = self.get_subnet(subnet3)

        nic0 = s0.create_network_interface(Description='ftd-nic0', Groups=[])
        nic1 = s1.create_network_interface(Description='ftd-nic1', Groups=[])
        nic2 = s2.create_network_interface(Description='ftd-nic2', Groups=[])
        nic3 = s3.create_network_interface(Description='ftd-nic3', Groups=[])

        nics = [{'NetworkInterfaceId': nic0.id, 'DeviceIndex': 0}, {'NetworkInterfaceId': nic1.id, 'DeviceIndex': 1},
                {'NetworkInterfaceId': nic2.id, 'DeviceIndex': 2}, {'NetworkInterfaceId': nic3.id, 'DeviceIndex': 3}]

        instances = self.resource.create_instances(ImageId='ami-7ff93e69', InstanceType='c3.xlarge', MinCount=1,
                                                   MaxCount=1, KeyName='ec2-demo-key', NetworkInterfaces=nics,
                                                   Placement={'AvailabilityZone': 'us-east-1a'}, )

        instance = instances[0]
        tag = instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}])

        instance.wait_until_running()
        instance.load()

        addr = self.client.allocate_address(Domain='vpc')
        response = self.client.associate_address(AllocationId=addr['AllocationId'], NetworkInterfaceId=nic0.id,
                                                 PrivateIpAddress=nic0.private_ip_address)

        self.instances[name] = instance


class Vpc:

    def __init__(self, resource, client, CidrBlock, vpc):

        self.subnets = {}
        self.security_groups = {}
        self.instances = {}

        self.resource = resource
        self.client = client
        if vpc is None:
            self.vpc = self.resource.create_vpc(CidrBlock=CidrBlock, DryRun=False, InstanceTenancy='default',
                                                AmazonProvidedIpv6CidrBlock=False)
        else:
            self.vpc = vpc

    def delete(self):

        # terminate instances
        for i in self.instances:
            instance = self.instances[i]['instance']
            for eip in self.resource.vpc_addresses.all():
                if instance.public_ip_address == eip.public_ip:
                    eip.association.delete()
                    eip.release()
                    break
            instance.terminate()
            instance.wait_until_terminated()

        # vpc.internet_gateways.all() -- call Vpc.detach_internet_gateway.
        for i in self.vpc.internet_gateways.all():
            self.vpc.detach_internet_gateway(InternetGatewayId=i.id)
            i.delete()

        # disassociate routing tables
        for rt in self.vpc.route_tables.all():
            for r in rt.associations:
                if r.main == False:
                    r.delete()

        # subnets
        for sn in self.vpc.subnets.all():
            for ni in sn.network_interfaces.all():
                ni.delete()
            sn.delete()

        # security groups
        for sg in self.vpc.security_groups.all():
            if sg.group_name != "default":
                sg.delete()

        # acl's
        for ac in self.vpc.network_acls.all():
            if ac.is_default != True:
                ac.delete()

        self.vpc.delete()

    def __common_del_inst_helper(self, instance, clean_nics=False):
        """Private helper function that deletes the specified instance (and
        associated elastic IP address).

        Args:
            instance    - instance object
            clean_nics  - Delete also network interfaces associated with the instance. Default: False

        Returns:
            True

        """
        for eip in self.resource.vpc_addresses.all():
            if instance.public_ip_address == eip.public_ip:
                eip.association.delete()
                eip.release()
                break

        nics = instance.network_interfaces

        instance.terminate()
        instance.wait_until_terminated()

        if clean_nics and nics is not None:
            for nic in nics:
                nic.delete()

        return True


    def __common_stop_inst_helper(self, instance):
        """Private helper function that stops the specified instance.

        Args:
            instance    - instance object

        Returns:
            True

        """
        instance.stop()
        instance.wait_until_stopped()
        return True

    def __common_start_inst_helper(self, instance):
        """Private helper function that starts the specified instance.

        Args:
            instance	- instance object

        Returns:
            True

        """
        instance.start()
        instance.wait_until_running()
        return True

    def get_instance(self, inst_name):
        """Searches for a VM instance that has been tagged with the specified name.

        Args:
            inst_name	- The Name tag of the desired instance

        Returns:
            Reference to the matching instance
            None if no match is found

        """
        # Iterate through the instances, looking for one with a matching 'Name' tag
        # that is in the VPC.
        for inst in self.resource.instances.all():
            if not inst.tags is None:
                for tag in inst.tags:
                    if tag["Key"] == 'Name':
                        if tag["Value"] == inst_name:
                            if inst.vpc_id == self.vpc.id:
                                return inst

        # We did not find a match
        return None

    def get_instance_by_id(self, inst_id):
        """Searches for a VM instance with the specified ID.

        Args:
            inst_id    - The ID of the desired instance

        Returns:
            Reference to the matching instance
            None if no match is found

        """
        # Iterate through the instances, looking for one with a matching ID.  Note that
        # instance IDs are unique, so don't need to match against VPC ID in this case.
        for inst in self.resource.instances.all():
            if inst.id == inst_id:
                return inst

        # We did not find a match
        return None

    def get_instance_state(self, inst_name):
        """Searches for a VM instance that has been tagged with the specified name,
        and returns its current state Name string.

        Args:
            inst_name    - The Name tag of the desired instance

        Returns:
            The current state Name as a string
            None if no matching instance is found

        """
        inst = self.get_instance(inst_name)
        return inst.state['Name'] if not inst is None else None

    def get_instance_state_by_id(self, inst_id):
        """Searches for a VM instance with the specified ID, and returns its current
        state Name string.

        Args:
            inst_id    - The ID of the desired instance

        Returns:
            The current state Name as a string
            None if no matching instance is found

        """
        inst = self.get_instance_by_id(inst_id)
        return inst.state['Name'] if not inst is None else None

    def delete_instance(self, inst_name, clean_nics=False):
        """Deletes the instance tagged with the given name, as well as the associated
        elastic IP address.

        Args:
            inst_name	- The Name tag of the instance to be deleted
            clean_nics  - Delete also network interfaces associated with the instance. Default: False

        Returns:
            True	- The instance and associated elastic IP have been deleted
            False	- An error occurred

        """
        # Does instance exist?
        inst = self.get_instance(inst_name)
        if inst is None:
            log.error("Cannot delete unknown instance '{0}'".format(inst_name))
            return False

        return self.__common_del_inst_helper(inst, clean_nics)

    def delete_instance_by_id(self, inst_id, clean_nics=False):
        """Deletes the instance with the given ID, as well as the associated elastic
        IP address.

        Args:
            inst_id	- ID of the instance to be deleted
            clean_nics  - Delete also network interfaces associated with the instance. Default: False

        Returns:
            True	- The instance and associated elastic IP have been deleted
            False	- An error occurred

        """
        # Does instance exist?
        inst = self.get_instance_by_id(inst_id)
        if inst is None:
            log.error("Cannot delete unknown instance with ID '{0}'".format(inst_id))
            return False

        return self.__common_del_inst_helper(inst, clean_nics)

    def deregister_ami(self, ami_name, delete_snapshot=True):
        """
        Deregisters the AMI with the given AMI Name. If there are multiple AMIs with the same name it will only delete
        the first one it finds.
        :param ami_name: AMI name
        :param delete_snapshot: Whether to also delete the snapshot
        :return: True if the AMI was deregistered successfully, False otherwise
        """
        ami = None
        for image in self.resource.images.filter(Filters=[{'Name': 'name', 'Values': [ami_name]}]):
            ami = image
            break

        if ami is None:
            log.error("Cannot deregister unknown AMI '{0}'".format(ami_name))
            return False

        return self.deregister_ami_by_id(ami.id, delete_snapshot)

    def deregister_ami_by_id(self, ami_id, delete_snapshot=True):
        """
        Deregister the AMI with the given ID.
        :param ami_id: id of the AMI
        :param delete_snapshot: Whether to also delete the snapshot
        :return: True if the AMI was deregistered successfully, raises Exception otherwise
        """

        ami = self.resource.Image(ami_id)

        if delete_snapshot:
            if "/" in ami.image_location:
                snapshot_name = ami.image_location.split("/")[1]
            else:
                log.warning("Delete snapshot is True however the snapshot name cannot be extracted from AMI")
                snapshot_name = None

        log.info("Deregistering AMI {}...".format(ami.id))
        ami.deregister()
        log.info("AMI deregistered.")

        if delete_snapshot and snapshot_name is not None:
            for snapshot in self.resource.snapshots.filter(Filters=[{'Name': 'description',
                                                                     'Values': [snapshot_name]}]):
                log.info("Deleting snapshot {} with ID: {}...".format(snapshot_name, snapshot.id))
                snapshot.delete()
                log.info("Snapshot deleted.")

        return True

    def start_instance(self, inst_name):
        """Starts the instance tagged with the given name.

        Args:
            inst_name	- The Name tag of the instance to be started

        Returns:
            True	- The instance has been started
            False	- An error occurred

        """
        # Does instance exist?
        inst = self.get_instance(inst_name)
        if inst is None:
            log.error("Unable to start unknown instance '{0}'".format(inst_name))
            return False

        return self.__common_start_inst_helper(inst)

    def start_instance_by_id(self, inst_id):
        """Starts the instance with the given ID.

        Args:
            inst_id	- ID of the instance to be started

        Returns:
            True	- The instance has been started
            False	- An error occurred

        """
        # Does instance exist?
        inst = self.get_instance_by_id(inst_id)
        if inst is None:
            log.error("Unable to start unknown instance with ID'{0}'".format(inst_id))
            return False

        return self.__common_start_inst_helper(inst)

    def stop_instance(self, inst_name):
        """Stops the instance tagged with the given name.

        Args:
            inst_name	- The Name tag of the instance to be stopped

        Returns:
            True	- The instance has been stopped
            False	- An error occurred

        """
        # Does instance exist?
        inst = self.get_instance(inst_name)
        if inst is None:
            log.error("Unable to stop unknown instance '{0}'".format(inst_name))
            return False

        return self.__common_stop_inst_helper(inst)

    def stop_instance_by_id(self, inst_id):
        """Stop the instance with the given ID.

        Args:
            inst_id	- ID of the instance to be stopped

        Returns:
            True	- The instance has been stopped
            False	- An error occurred

        """
        # Does instance exist?
        inst = self.get_instance_by_id(inst_id)
        if inst is None:
            log.error("Unable to stop unknown instance with ID '{0}'".format(inst_id))
            return False

        return self.__common_stop_inst_helper(inst)

    def add_internet_gateway(self):

        internet_gateway = self.resource.create_internet_gateway()
        # print(internet_gateway.id)

        response = self.vpc.attach_internet_gateway(InternetGatewayId=internet_gateway.id)

        return internet_gateway

    def add_subnet(self, name, CidrBlock, AvailabilityZone=None):

        # Default AvailabilityZone if necessary
        if AvailabilityZone is None:
            AvailabilityZone = 'us-east-1a'

        s = self.vpc.create_subnet(CidrBlock=CidrBlock, AvailabilityZone=AvailabilityZone)

        tag = s.create_tags(Tags=[{'Key': 'Name', 'Value': name}, ])

        self.subnets[name] = s

        return s

    def get_subnet(self, sub_name):
        """Searches for a subnet that has been tagged with the specified name.

        Args:
            sub_name	- The Name tag of the desired subnet

        Returns:
            Reference to the matching subnet
            None if no match is found

        """
        # Iterate through the subnets, looking for one with a matching 'Name' tag
        # that is in the VPC.
        for sn in self.resource.subnets.all():
            if not sn.tags is None:
                for tag in sn.tags:
                    if tag["Key"] == 'Name':
                        if tag["Value"] == sub_name:
                            if sn.vpc_id == self.vpc.id:
                                return sn

        # We did not find a match
        return None

    def get_subnet_by_id(self, sub_id):
        """Searches for a subnet with the specified ID.

        Args:
            sub_id    - The ID of the desired subnet

        Returns:
            Reference to the matching subnet
            None if no match is found

        """
        # Iterate through the subnets, looking for one with a matching ID.  Note that
        # subnet IDs are unique, so don't need to match against VPC ID in this case.
        for sn in self.resource.subnets.all():
            if sn.id == sub_id:
                return sn

        # We did not find a match
        return None

    def __common_get_instance_ip_helper(self, inst, addr_type):
        """Common helper function that retrieves the specifed address from the
        supplied instance object.

        Args:
            inst        - Instance object
            addr_type    - Either 'public' or 'private' (case-insensitive)

        Returns:
            Requested IP address
            None if an error occurs

        """
        at = addr_type.casefold()
        if not at in ['public', 'private']:
            log.error('Unrecognized address type "{0}"'.format(addr_type))
            return None
        return inst.public_ip_address if at == 'public' else inst.private_ip_address

    def get_instance_ip(self, inst_name, addr_type):
        """Retrieves the requested IP address for the instance tagged with the
        specified name.

        Args:
            inst_name    - The 'name' of the instance in question
            addr_type    - Either 'public' or 'private'

        Returns:
            Requested IP address
            None if an error occurs

        """
        inst = self.get_instance(inst_name)
        if inst is None:
            log.error('No instance "{0}" found'.format(inst_name))
            return None

        # Hand off to common helper
        return self.__common_get_instance_ip_helper(inst, addr_type)

    def get_instance_ip_by_id(self, inst_id, addr_type):
        """Retrieves the requested IP address for the instance with the specified
        instance ID.

        Args:
            inst_id        - ID of the instance in question
            addr_type    - Either 'public' or 'private'

        Returns:
            Requested IP address
            None if an error occurs

        """
        inst = self.get_instance(inst_id)
        if inst is None:
            log.error('No instance with ID "{0}" found'.format(inst_id))
            return None

        # Hand off to common helper
        return self.__common_get_instance_ip_helper(inst, addr_type)

    def __common_get_ftd_private_ip_helper(self, ftd, int_num):
        """Common helper function that looks up the private IP address of a given FTD
        interface number.

        Args:
            ftd        - FTD instance object
            int_num    - Interface number, as follows:
                        0 - Mgmt interface ('ftd-nic0')
                        1 - Diag interface ('ftd-nic1')
                        2 - g0/0 interface ('ftd-nic2')
                        3 - g0/1 interface ('ftd-nic3')

        Returns:
            IP address of the specified interface
            None if an error occurs

        """
        # Compute description for NIC in question
        if not int_num in [0, 1, 2, 3]:
            log.error('Invalid FTD interface number "{0}"'.format(int_num))
            return None
        int_descr = 'ftd-nic{0}'.format(int_num)

        # Look for a NIC with the computed description string
        for nic in ftd.network_interfaces:
            if nic.description == int_descr:
                # Found it
                return nic.private_ip_address

        # This should never happen, but if so...
        log.error('No FTD interface with description "{0}" found'.format(int_descr))
        return None

    def get_ftd_private_ip(self, ftd_name, int_num):
        """Retrieves the private IP address associated with the interface referenced
        by the interface number.

        Args:
            ftd_name    - Name (tag) of the FTD instance in question
            int_num        - See __common_get_ftd_private_ip_helper()

        Returns:
            IP address of the specified interface
            None if an error occurs

        """
        # Find FTD instance
        ftd = self.get_instance(ftd_name)
        if ftd is None:
            log.error('No FTD "{0}" found'.format(ftd_name))
            return None

        # Hand off to common helper
        return self.__common_get_ftd_private_ip_helper(ftd, int_num)

    def get_ftd_private_ip_by_id(self, ftd_id, int_num):
        """Retrieves the private IP address associated with the FTD interface
        referenced by the interface number.

        Args:
            ftd_id        - Instance ID of the FTD instance in question
            int_num        - See __common_get_ftd_private_ip_helper()

        Returns:
            IP address of the specified interface
            None if an error occurs

        """
        # Find FTD instance
        ftd = self.get_instance_by_id(ftd_id)
        if ftd is None:
            log.error('No FTD instance with ID "{0}" found'.format(ftd_id))
            return None

        # Hand off to common helper
        return self.__common_get_ftd_private_ip_helper(ftd, int_num)

    def add_security_group(self, name, GroupName, Description):
        '''
        Creates a Security Group in the VPC

        Args:
            name        - 'Name' tag for the Security Group
            GroupName    - Group Name of the Security Group
            Description - Text description of the Security Group

        Returs:
            Reference to the created Security Group
        '''
        sg = self.vpc.create_security_group(GroupName=GroupName, Description=Description)
        sg.create_tags(Tags=[{'Key': 'Name', 'Value': name}, ])
        return sg

    def get_security_group(self, name):
        """Searches for a security group that has been tagged with the specified
        name.

        Args:
            sg_name    - The Name tag of the desired security group

        Returns:
            Reference to the matching security group
            None if no match is found

        """
        # Iterate through the security groups, looking for one with a matching 'Name'
        # tag that is in the VPC.
        for sg in self.resource.security_groups.all():
            if not sg.tags is None:
                for tag in sg.tags:
                    if tag["Key"] == 'Name':
                        if tag["Value"] == name:
                            # log.info("sg.vpc_id = {0} vpc.id = {1}".format(sg.vpc_id, self.vpc.id))
                            if sg.vpc_id == self.vpc.id:
                                return sg

        # We did not find a match
        return None

    def get_security_group_by_id(self, sg_id):
        """Searches for a security group with the specified ID.

        Args:
            sg_id    - The ID of the desired security group

        Returns:
            Reference to the matching security group
            None if no match is found

        """
        # Iterate through the instances, looking for one with a matching ID. Note that security
        # group IDs are unique, so don't need to match against VPC ID in this case.
        for sg in self.resource.security_groups.all():
            if sg.id == sg_id:
                return sg

        # We did not find a match
        return None

    def add_ftd(self, name, subnet0, subnet1, subnet2, subnet3, **kwargs):
        '''
        Purpose:
            Creates an FTD instance.

        Arguments (required):
            name        - Name to be given to the FTD instance
            subnet0        - Mgmt interface subnet
            subnet1        - Diag interface subnet
            subnet2        - g0/0 interface subnet
            subnet3        - g0/1 interface subnet

        Keyword Arguments (optional):
            MinCount        - ?: defaults to 1
            MaxCount        - ?: defaults to 1
            InstanceType    - AWS instance type: defaults to 'c3.xlarge'
            ImageId            - AMI ID for instance: defaults to 'ami-7ff93a69'
            KeyName            - ssh keypair name: defaults to 'ec2-demo-key'
            MgmtSecGroup    - Security group for Mgmt interface; default is to
                              create a new one with some default values
            DataSecGroup    - Security group for Data/Sensor (g0/0 and g0/1)
                              interfaces; if not specified AWS will default it
            UserData        - Day0 config info to be pushed to the FTD instance
            AvailabilityZone- Availability Zone for the deployment; defaults to
                              'us-east-1a'

        Returns:
            EC2 FTD instance
            Raises an exception on error (probably)

        Network interface notes:  Network interfaces are created for the four
        interfaces. The descriptions for the four interfaces are as follows:
            'ftd-nic0'    - Mgmt interface
            'ftd-nic1'    - Diag interface
            'ftd-nic2'    - g0/0 interface
            'ftd-nic3'    - g0/1 interface

        Note:
            This method currently does not support overriding the default FTD
            disk volume size, derived from the AMI snapshot volume size (52 GB).
        '''

        # defaults
        kwargs['MinCount'] = kwargs.get('MinCount', 1)  # required
        kwargs['MaxCount'] = kwargs.get('MaxCount', 1)  # required
        kwargs['InstanceType'] = kwargs.get('InstanceType', 'c3.xlarge')  # required
        kwargs['ImageId'] = kwargs.get('ImageId', 'ami-7ff93e69')  # required
        kwargs['KeyName'] = kwargs.get('KeyName', 'ec2-demo-key')  # required

        # If present, retrieve (and remove) AvailabilityZone from kwargs,
        # defaulting otherwise
        if not kwargs.get('AvailabilityZone', None) is None:
            availability_zone = kwargs.get('AvailabilityZone')
        else:
            availability_zone = 'us-east-1a'
        try:
            del kwargs['AvailabilityZone']
        except:
            pass

        # If present, retrieve (and remove) MgmtSecGroup from kwargs
        if not kwargs.get('MgmtSecGroup', None) is None:
            mgmt_sg_name = kwargs.get('MgmtSecGroup')
        else:
            mgmt_sg_name = None
        try:
            del kwargs['MgmtSecGroup']
        except:
            pass

        network_interfaces = kwargs.get('NetworkInterfaces', None)
        try:
            del kwargs['NetworkInterfaces']
        except:
            pass

        if not list(self.vpc.internet_gateways.all()):
            ig = self.add_internet_gateway()
            route_tables = list(self.vpc.route_tables.all())
            route = route_tables[0].create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)

        if not network_interfaces:
            # If present, retrieve (and remove) DataSecGroup from kwargs
            if not kwargs.get('DataSecGroup', None) is None:
                data_sg_name = kwargs.get('DataSecGroup')
            else:
                data_sg_name = None
            try:
                del kwargs['DataSecGroup']
            except:
                pass

            # log.info("sg_name = {0}".format(sg_name))

            # Access or create the Management Security Group
            mgmt_sg = None
            if not mgmt_sg_name is None:
                mgmt_sg = self.get_security_group(mgmt_sg_name)
            if mgmt_sg is None:
                # Either no SecGroup name specified, or we did not find it, so need to create one
                mgmt_sg = self.add_security_group(name=name, GroupName=name, Description="ftd sg")
                mgmt_sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=80, ToPort=80)
                mgmt_sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=443, ToPort=443)
                mgmt_sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=22, ToPort=22)
                mgmt_sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=8305, ToPort=8305)

            # Access the Data Security Group (if specified)
            data_sg = None
            if not data_sg_name is None:
                data_sg = self.get_security_group(data_sg_name)

            # Provision Management interface
            nic0 = subnet0.create_network_interface(Description='ftd-nic0', Groups=[mgmt_sg.id])

            # Provision Diagnostic interface
            nic1 = subnet1.create_network_interface(Description='ftd-nic1', Groups=[])

            # Provision Data Sensor interfaces
            if not data_sg is None:
                nic2 = subnet2.create_network_interface(Description='ftd-nic2', Groups=[data_sg.id])
                nic3 = subnet3.create_network_interface(Description='ftd-nic3', Groups=[data_sg.id])
            else:
                nic2 = subnet2.create_network_interface(Description='ftd-nic2', Groups=[])
                nic3 = subnet3.create_network_interface(Description='ftd-nic3', Groups=[])
            response = self.client.modify_network_interface_attribute(NetworkInterfaceId=nic2.id,
                                                                      SourceDestCheck={'Value': False})
            response = self.client.modify_network_interface_attribute(NetworkInterfaceId=nic3.id,
                                                                      SourceDestCheck={'Value': False})

            nic0.create_tags(Tags=[{'Key': 'Name', 'Value': name}, {'Key': 'DeviceIndex', 'Value': '0'}])
            nic1.create_tags(Tags=[{'Key': 'Name', 'Value': name}, {'Key': 'DeviceIndex', 'Value': '1'}])
            nic2.create_tags(Tags=[{'Key': 'Name', 'Value': name}, {'Key': 'DeviceIndex', 'Value': '2'}])
            nic3.create_tags(Tags=[{'Key': 'Name', 'Value': name}, {'Key': 'DeviceIndex', 'Value': '3'}])
            nics = [{'NetworkInterfaceId': nic0.id, 'DeviceIndex': 0},
                    {'NetworkInterfaceId': nic1.id, 'DeviceIndex': 1},
                    {'NetworkInterfaceId': nic2.id, 'DeviceIndex': 2},
                    {'NetworkInterfaceId': nic3.id, 'DeviceIndex': 3}]

            addr = self.client.allocate_address(Domain='vpc')
            response = self.client.associate_address(AllocationId=addr['AllocationId'], NetworkInterfaceId=nic0.id,
                                                     PrivateIpAddress=nic0.private_ip_address)
        else:
            nics = network_interfaces

        instances = self.resource.create_instances(NetworkInterfaces=nics,
                                                   Placement={'AvailabilityZone': availability_zone}, **kwargs)

        instance = instances[0]
        instance.wait_until_running()

        tag = instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}])

        instance.load()

        self.instances[name] = {"instance": instance, "subnets": [subnet0, subnet1, subnet2, subnet3], "type": "ftd"}

        return (instance)

    def add_fmc(self, name, subnet0, image_id='ami-1df3080b', InstanceType='c3.xlarge',
                KeyName='ec2-demo-key', SecGroup=None,
                UserData=None, AvailabilityZone=None, DiskSize=250, **kwargs):
        '''
        Purpose:
            Creates an FMC instance.

        Arguments (required):
            name        - Name to be given to the FMC instance
            subnet0        - Mgmt interface subnet

        Keyword Arguments (optional):
            image_id        - AMI ID for instance: defaults to 'ami-1df3080b'
            InstanceType    - AWS instance type: defaults to 'c3.xlarge'
            KeyName            - ssh keypair name: defaults to 'ec2-demo-key'
            SecGroup        - Security group for Mgmt interface; default is to
                              create a new one with some default values
            UserData        - Day0 config info to be pushed to the FMC instance
            AvailabilityZone- Availability Zone for the deployment; defaults to
                              'us-east-1a'
            DiskSize        - Size of the FMC disk volume; defaults to 250 GB

        Returns:
            EC2 FMC instance
            Raises an exception on error (probably)

        Network interface notes:  Network interface is create for the interface
            fmc-nic0 (mgmt interface)
        '''

        # If not specified, default AvailabilityZone to us-east-1a
        availability_zone = AvailabilityZone if not AvailabilityZone is None else 'us-east-1a'

        if not list(self.vpc.internet_gateways.all()):
            ig = self.add_internet_gateway()
            route_tables = list(self.vpc.route_tables.all())
            route = route_tables[0].create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)

        # Creating a Security Group
        sg = None
        if not SecGroup is None:
            sg = self.get_security_group(SecGroup)
        if sg is None:
            # Did not find the specified security group, so create one
            sg = self.add_security_group(name=name, GroupName=name, Description="fmc sg")
            sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=80, ToPort=80)
            sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=443, ToPort=443)
            sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=22, ToPort=22)

        network_interfaces = kwargs.get('NetworkInterfaces', None)
        try:
            del kwargs['NetworkInterfaces']
        except:
            pass

        if not network_interfaces:
            nic = subnet0.create_network_interface(Description='fmc-nic0', Groups=[sg.id])
            nic.create_tags(Tags=[{'Key': 'Name', 'Value': name}, {'Key': 'DeviceIndex', 'Value': '0'}])
            nics = [{'NetworkInterfaceId': nic.id, 'DeviceIndex': 0}]

            addr = self.client.allocate_address(Domain='vpc')
            response = self.client.associate_address(AllocationId=addr['AllocationId'], NetworkInterfaceId=nic.id,
                                                     PrivateIpAddress=nic.private_ip_address)
        else:
            nics = network_interfaces

        # Prepare disk volume block device map
        bdm = [
            {
                'DeviceName': '/dev/xvda',
                'Ebs': {
                    'VolumeSize': DiskSize,
                    'DeleteOnTermination': True,
                }
            }
        ]

        if not UserData is None:
            instances = self.resource.create_instances(ImageId=image_id, InstanceType=InstanceType,
                                                       MinCount=1, MaxCount=1, KeyName=KeyName, NetworkInterfaces=nics,
                                                       BlockDeviceMappings=bdm,
                                                       Placement={'AvailabilityZone': availability_zone},
                                                       UserData=UserData)
        else:
            instances = self.resource.create_instances(ImageId=image_id, InstanceType=InstanceType,
                                                       MinCount=1, MaxCount=1, KeyName=KeyName, NetworkInterfaces=nics,
                                                       BlockDeviceMappings=bdm,
                                                       Placement={'AvailabilityZone': availability_zone}, )

        instance = instances[0]
        instance.wait_until_running()

        tag = instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}])

        instance.load()

        self.instances[name] = {"instance": instance, "subnets": [subnet0], "type": "fmc"}

        return (instance)

    # def add_endpoint(self, name, subnet, image_id='ami-0b33d91d', KeyName='ec2-demo-key', **kwargs ):
    def add_endpoint(self, name, subnet, **kwargs):

        user_data = "#!/bin/bash\nrpm -i https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/linux_amd64/amazon-ssm-agent.rpm"

        # defaults
        kwargs['MinCount'] = kwargs.get('MinCount', 1)  # required
        kwargs['MaxCount'] = kwargs.get('MaxCount', 1)  # required
        kwargs['InstanceType'] = kwargs.get('InstanceType', 't2.micro')  # required
        kwargs['ImageId'] = kwargs.get('ImageId', 'ami-0b33d91d')  # required
        kwargs['UserData'] = kwargs.get('UserData', user_data)
        kwargs['KeyName'] = kwargs.get('KeyName', 'ec2-demo-key')  # required

        # If present, retrieve (and remove) AvailabilityZone from kwargs,
        # defaulting otherwise
        if not kwargs.get('AvailabilityZone', None) is None:
            availability_zone = kwargs.get('AvailabilityZone')
        else:
            availability_zone = 'us-east-1a'
        try:
            del kwargs['AvailabilityZone']
        except:
            pass

        # Find (and remove) SecGroup from kwargs
        if not kwargs.get('SecGroup', None) is None:
            sg_name = kwargs.get('SecGroup')
        else:
            sg_name = None
        try:
            del kwargs['SecGroup']
        except:
            pass

        #log.info("sg_name = {0}".format(sg_name))

        bdm = kwargs.get('BlockDeviceMappings', None)
        if not bdm is None:
            kwargs['BlockDeviceMappings'] = bdm

        if not list(self.vpc.internet_gateways.all()):
            ig = self.add_internet_gateway()
            route_tables = list(self.vpc.route_tables.all())
            route = route_tables[0].create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)

        # Find or create the Security Group
        sg = None
        if not sg_name is None:
            sg = self.get_security_group(sg_name)
        if sg is None:
            # Either no Security Group name specified, or we did not find it, so need to create one
            sg = self.add_security_group(name=name, GroupName=name, Description="ep sg")
            sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=80, ToPort=80)
            sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=443, ToPort=443)
            sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=22, ToPort=22)
            # Allow all traffic on the private subnets.
            sg.authorize_ingress(IpProtocol="-1", CidrIp="10.0.0.0/16", FromPort=0, ToPort=0)

        network_interfaces = kwargs.get('NetworkInterfaces', None)
        try:
            del kwargs['NetworkInterfaces']
        except:
            pass
        if not network_interfaces:
            nic = subnet.create_network_interface(SubnetId=subnet.id, Groups=[sg.id])
            nics = [{'NetworkInterfaceId': nic.id, 'DeviceIndex': 0}]
            addr = self.client.allocate_address(Domain='vpc')
            response = self.client.associate_address(AllocationId=addr['AllocationId'], NetworkInterfaceId=nic.id,
                                                     PrivateIpAddress=nic.private_ip_address)
        else:
            nic = []
            nic_ids = []
            nics = network_interfaces
            for entry in network_interfaces:
                nic_ids.append(entry['NetworkInterfaceId'])

            for existing_nic in self.vpc.network_interfaces.filter(NetworkInterfaceIds=nic_ids):
                nic.append(existing_nic)

            if len(nics) > 0:
                nic = nic[0]

        instances = self.resource.create_instances(NetworkInterfaces=nics,
                                                   Placement={'AvailabilityZone': availability_zone}, **kwargs)

        instance = instances[0]
        instance.wait_until_running()

        tag = instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}, ])

        instance.load()

        self.instances[name] = {"instance": instance, "nic": nic, "type": "endpoint"}

        return (instance)

    def add_ngfw_testbed_type1(self, FmcImageId='ami-1df3080b', FmcKeyName='ec2-demo-key',
                               FtdImageId='ami-7ff93e69', FtdKeyName='ec2-demo-key'):

        s0 = self.add_subnet('sn0', '10.0.0.0/24')
        s1 = self.add_subnet('sn1', '10.0.1.0/24')
        s2 = self.add_subnet('sn2', '10.0.2.0/24')
        s3 = self.add_subnet('sn3', '10.0.3.0/24')

        fmc = self.add_fmc('fmc', s0, FmcImageId, FmcKeyName)
        print("FMC public ip = " + fmc.public_ip_address)

        ftd = self.add_ftd('ftd', s0, s1, s2, s3, ImageId=FtdImageId, KeyName=FtdKeyName)
        print("FTD public ip = " + ftd.public_ip_address)

        ep1 = self.add_endpoint('ep1', s2)
        print("EP1 public ip = " + ep1.public_ip_address)

        ep2 = self.add_endpoint('ep2', s3)
        print("EP2 public ip = " + ep2.public_ip_address)

    def add_esa(self, name, subnet0, subnet1, subnet2, image_id='ami-a65282b0', AvailabilityZone=None):

        # If not specified, default AvailabilityZone to us-east-1a
        availability_zone = AvailabilityZone if not AvailabilityZone is None else 'us-east-1a'

        if (list(self.vpc.internet_gateways.all()) == []):
            ig = self.add_internet_gateway()
            route_tables = list(self.vpc.route_tables.all())
            route = route_tables[0].create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)

        # Creating a Security Group
        sg = self.add_security_group(name="esa sg", GroupName="esa", Description="esa sg")
        sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=80, ToPort=80)
        sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=443, ToPort=443)
        sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=22, ToPort=22)

        nic0 = subnet0.create_network_interface(Description='esa-nic0', Groups=[sg.id])
        nic1 = subnet1.create_network_interface(Description='esa-nic1', Groups=[])
        nic2 = subnet2.create_network_interface(Description='esa-nic2', Groups=[])

        nics = [{'NetworkInterfaceId': nic0.id, 'DeviceIndex': 0}, {'NetworkInterfaceId': nic1.id, 'DeviceIndex': 1},
                {'NetworkInterfaceId': nic2.id, 'DeviceIndex': 2}]

        instances = self.resource.create_instances(ImageId=image_id, InstanceType='c4.large', MinCount=1, MaxCount=1,
                                                   KeyName='ec2-demo-key', NetworkInterfaces=nics,
                                                   Placement={'AvailabilityZone': availability_zone}, )

        instance = instances[0]
        tag = instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}])

        instance.wait_until_running()

        addr = self.client.allocate_address(Domain='vpc')
        response = self.client.associate_address(AllocationId=addr['AllocationId'], NetworkInterfaceId=nic0.id,
                                                 PrivateIpAddress=nic0.private_ip_address)

        instance.load()

        self.instances[name] = {"instance": instance, "subnets": [subnet0, subnet1, subnet2], "type": "esa"}

        return instance

    def add_hammer(self, name, subnet0, subnet1, subnet2, image_id='ami-baa0c9ad', AvailabilityZone=None):

        # If not specified, default AvailabilityZone to us-east-1a
        availability_zone = AvailabilityZone if not AvailabilityZone is None else 'us-east-1a'

        if (list(self.vpc.internet_gateways.all()) == []):
            ig = self.add_internet_gateway()
            route_tables = list(self.vpc.route_tables.all())
            route = route_tables[0].create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)

        # Creating a Security Group
        sg = self.add_security_group(name="hammer sg", GroupName="hammer", Description="hammer sg")
        sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=80, ToPort=80)
        sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=443, ToPort=443)
        sg.authorize_ingress(IpProtocol="tcp", CidrIp="0.0.0.0/0", FromPort=22, ToPort=22)

        nic0 = subnet0.create_network_interface(Description='hammer-nic0', Groups=[sg.id])
        nic1 = subnet1.create_network_interface(Description='hammer-nic1', Groups=[])
        nic2 = subnet2.create_network_interface(Description='hammer-nic2', Groups=[])

        nics = [{'NetworkInterfaceId': nic0.id, 'DeviceIndex': 0}, {'NetworkInterfaceId': nic1.id, 'DeviceIndex': 1},
                {'NetworkInterfaceId': nic2.id, 'DeviceIndex': 2}]

        instances = self.resource.create_instances(ImageId=image_id, InstanceType='c4.xlarge', MinCount=1, MaxCount=1,
                                                   KeyName='ec2-demo-key', NetworkInterfaces=nics,
                                                   Placement={'AvailabilityZone': availability_zone}, )

        instance = instances[0]
        tag = instance.create_tags(Tags=[{'Key': 'Name', 'Value': name}])

        instance.wait_until_running()

        addr = self.client.allocate_address(Domain='vpc')
        response = self.client.associate_address(AllocationId=addr['AllocationId'], NetworkInterfaceId=nic0.id,
                                                 PrivateIpAddress=nic0.private_ip_address)

        instance.load()

        self.instances[name] = {"instance": instance, "subnets": [subnet0, subnet1, subnet2], "type": "hammer"}

        return instance

    def add_esa_perf_testbed(self):

        s0 = self.add_subnet('sn0', '10.0.0.0/24')
        s1 = self.add_subnet('sn1', '10.0.1.0/24')
        s2 = self.add_subnet('sn2', '10.0.2.0/24')

        esa = self.add_esa('esa', s0, s1, s2)
        print("ESA public ip = " + esa.public_ip_address)

        ham = self.add_hammer('hammer', s0, s1, s2)
        print("Hammer public ip = " + ham.public_ip_address)

    def onboard_ftd(self, ec2, qcow2, subnet, ami_name=None, key_name=None, key_file=None, sec_group=None,
                    availability_zone=None):
        '''
        Purpose:
            Onboards an FTDv qcow2 image.  This method is a wrapper for onboard_ngfwv(), which
            does all the heavy lifting.

        Arguments:
            ec2         - Active EC2 session
            qcow2        - Fully-qualified or relative path/name of the FTDv qcow2 image file.
            subnet       - Subnet to use for the staging server.
            ami_name     - Optional string that will be inserted into the AMI name
            key_name     - Optional key name to use for ssh connections
            key_file     - Optional fully-qualified name/path of privkey pem file
            sec_group    - Optional security group name
            availability_zone - Optional availability zone, defaulted to 'us-east-1a'

        Returns:
            AMI ID of the onboarded FTDv image.
            None on error
        '''
        return self.onboard_ngfwv(ec2, 'ftd', qcow2, subnet, ami_name, key_name, key_file, sec_group,
                                  availability_zone)

    def onboard_fmc(self, ec2, qcow2, subnet=None, ami_name=None, key_name=None, key_file=None, sec_group=None,
                    availability_zone=None):
        '''
        Purpose:
            Onboards an FMCv qcow2 image.  This method is a wrapper for onboard_ngfwv(), which
            does all the heavy lifting.

        Arguments:
            ec2         - Active EC2 session
            qcow2          - Fully-qualified or relative path/name of the FMCv qcow2 image file.
            sub_name     - Subnet to use for the staging server.
            ami_name     - Optional string that will be inserted into the AMI name
            key_name     - Optional key name to use for ssh connections
            key_file     - Optional fully-qualified name/path of privkey pem file
            sec_group    - Optional security group name
            availability_zone - Optional availability zone, defaulted to 'us-east-1a'

        Returns:
            AMI ID of the onboarded FMCv image.
            None on error
        '''

        return self.onboard_ngfwv(ec2, 'fmc', qcow2, subnet, ami_name, key_name, key_file, sec_group,
                                  availability_zone)

    def onboard_ngfwv(self, ec2, mode, qcow2, subnet, ami_name, key_name, key_file, sec_group,
                      availability_zone=None):
        '''
        Purpose:
            Onboards an FTDv or FMCv qcow2 image.  This involves spinning up a transient
            staging server in the VPC, uploading the qcow2 image to the staging server,
            running a script to convert it to a snapshot, then registering that snapshot
            as an AMI.

        Arguments:
            ec2         - Active EC2 session
            mode           - either 'fmc' or 'ftd'
            qcow2         - Fully-qualified or relative path/name of the FTDv qcow2 image file.
            sub_name     - Subnet to use for the staging server.
            ami_name     - Optional string that will be inserted into the AMI name
            key_name     - Optional key name to use for ssh connections
            key_file     - Optional fully-qualified name/path of privkey pem file
            sec_group    - Optional security group name
            availability_zone - Optional availability zone, defaulted to 'us-east-1a'

        Returns:
            AMI ID of the onboarded FTDv/FMCv image.
            None on error

        TBD: Any additional error handling needed?
        '''

        # We will use the local time as a unique suffix for generated names
        timestamp = time.strftime("%s")

        # Make sure a mode has been specified
        if not mode in ['fmc', 'ftd']:
            log.error("Missing/invalid ngfwv mode '{0}'; must be 'fmc' or 'ftd'".format(mode))
            return None

        # Make sure qcow2 file exists and is readable
        if not os.path.isfile(qcow2):
            log.error("qcow2 input file '{0}' missing or not readable".format(qcow2))
            return None

        # Default the availability_zone, if not specified
        if availability_zone is None:
            availability_zone = 'us-east-1a'

        # Build the block device mapping for the ubuntu server (and set up a few
        # mode-dependent variables for later)
        if mode == "fmc":
            sda1_size = 30
            sdc_size = 250
            ami_prefix = 'FMCv-'
            fixup_script = "fixup-fmc.sh"
        elif mode == "ftd":
            sda1_size = 40
            sdc_size = 52
            ami_prefix = 'FTDv-'
            fixup_script = "fixup-ftd.sh"
        bdm = [
            {
                'DeviceName': '/dev/sda1',
                'Ebs': {
                    'VolumeSize': sda1_size,
                }
            },
            {
                'DeviceName': '/dev/sdc',
                'Ebs': {
                    'VolumeSize': sdc_size,
                    'DeleteOnTermination': True,
                }
            }
        ]
        fixup_script_real = os.path.dirname(__file__) + "/" + fixup_script

        # Compute a unique name for the AMI
        ami_suffix = '-' + os.getenv('USER') + '-' + timestamp
        if ami_name is None:
            ami_name_real = ami_prefix + ami_suffix
        else:
            ami_name_real = ami_name + ami_suffix

        # Need a keypair for ssh interaction with the staging server.  More specifically,
        # we need the Name of the keypair, and we need access to the private key pem file.

        # Default the keyname if needed
        key = None
        keyname = key_name if not key_name is None else DEFAULT_KEYPAIR_NAME

        # Does the keypair exist?
        if not ec2.get_keypair_info(keyname) is None:
            # Keypair with that name exists. Is the specified pem file accessible?
            keyfile = _resolve_key_file(key_file)
            if keyfile is None:
                # Unable to continue if we can't get to the pem file
                log.error("Unable to access pem file '{0}'".format(key_file))
                return None
        else:
            # Keypair does not exist, so create it
            keyfile = '/tmp/' + keyname + '.pem'
            key = ec2.add_keypair(keyname)
            key.save(keyfile)

        # Need a subnet
        if subnet is None:
            # Create with default name in default AvailabilityZone
            sn = self.add_subnet('onboard_s0', '10.0.0.0/24', availability_zone)
        else:
            sn = subnet

        # Spin up the staging server
        stager_name = mode + '-stager'
        stager = self.add_endpoint(stager_name, sn, SecGroup=sec_group, InstanceType='m3.large',
                                   ImageId='ami-038f5168', BlockDeviceMappings=bdm,
                                   KeyName=keyname,
                                   AvailabilityZone=availability_zone)
        wait_until_ssh_ready(stager.public_ip_address)
        log.info("Created stager " + mode + '-stager; public IP = {0}'.format(stager.public_ip_address))

        # Prepare the disk image
        #
        # Note:  Using 'hide()' to suppress the voluminous script output for the time being.  May want to revisit...
        with hide('output'), settings(host_string=stager.public_ip_address, user='ubuntu', key_filename=keyfile,
                                      connection_attempts=10, timeout=30):

            log.info("===== Starting disk image preparation =====")

            # Make sure we can write to /mnt on he staging server
            r = sudo('chmod 777 /mnt')
            print(r)

            # Upload the qcow2 image and fixup script
            log.info("Uploading qcow2 and fixup script")
            put(qcow2, '/mnt/image.qcow2')
            put(fixup_script_real, '/mnt/fixup.sh')
            r = sudo('chmod +x /mnt/fixup.sh')

            # Pre-install step
            log.info("Running pre-install step")
            r = sudo('/mnt/fixup.sh preinstall')

            # Install step
            log.info("Installing disk image. This can take awhile.")
            r = sudo('/mnt/fixup.sh doinstall')

            # Post-install step
            log.info("Running post-install step")
            r = sudo('/mnt/fixup.sh postinstall')

            log.info("===== Finished disk image preparation =====")

        # Retrieve volume ID of '/dev/sdc' volume
        volume_id = ec2.get_volume_id(stager.id, u'/dev/sdc')
        if volume_id is None:
            log.error("Failed to retrieve Volume ID for {0} deployment".format(mode))
            # Cleanup here
            return None

        log.info("Retrieved volume ID {0} for '/dev/sdc'".format(volume_id))

        # Create snapshot of volume
        snapshot_id = ec2.create_snapshot(volume_id, ami_name_real, qcow2)

        # Register the snapshot as an AMI
        ami_description = ami_name_real + ' initiated at ' + timestamp
        ami_id = ec2.register_ngfwv_ami(snapshot_id, ami_name_real, ami_description)

        # If default keypair was allocated, delete it
        if not key is None and keyname == DEFAULT_KEYPAIR_NAME:
            ec2.delete_keypair(key)

        # Delete the staging server
        self.delete_instance(stager_name, clean_nics=True)

        return ami_id


def _keypair_save(self, f):
    """Helper method added to keypair for saving the private key pem file.

    Args:
        f - name to be given to the private key pem file

    Returns:
        nothing

    """

    # Create pem file and save private key material in it
    key_file = open(f, "w")
    key_file.write(self.key_material)
    key_file.close()

    # Permissions on pem file must allow rw only by user
    chmod(f, S_IRUSR | S_IWUSR)


def _resolve_key_file(key_file):
    """Helper function that determines whether the specified PEM file
    exists and if so, whether it is readable/writeable by the user

    Args:
        key_file - Fully-qualified path/name of the private key pem file

    Returns:
        Fully-qualified path/name of the private key pem file
        None if an error occurs

    """
    if os.path.isfile(key_file):
        # We should really check the permissions here...
        return key_file

    # Look in present working directory
    key_file = os.getenv('PWD') + '/' + pem_file
    if os.path.isfile(key_file):
        # File exists, check permissions
        st = os.stat(key_file)
        return key_file if bool(st.st_mode & S_IRUSR) and bool(st.st_mode & S_IWUSR) else None

    # Didn't find it
    return None


class Ec2:

    def __init__(self, region_name='us-east-1', access_key_id=None, secret_access_key=None):
        if not access_key_id is None and not secret_access_key is None:
            self.client = boto3.client('ec2', region_name=region_name,
                                       aws_access_key_id=access_key_id,
                                       aws_secret_access_key=secret_access_key)
            self.resource = boto3.resource('ec2', region_name=region_name,
                                           aws_access_key_id=access_key_id,
                                           aws_secret_access_key=secret_access_key)
        else:
            self.client = boto3.client('ec2', region_name=region_name)
            self.resource = boto3.resource('ec2', region_name=region_name)

        self.vpcs = {}

    def add_vpc(self, name, CidrBlock=None):
        """Creates a Vpc object.  There are two flavors:

          1    - If a VPC tagged with the given name exists, it is embedded in the Vpc object.
          2 - If such a VPC does not exist, it is created and tagged with the given name.

        Args:
          name		- Name (tag) of the VPC
          CidrBlock	- Network block of the form 'w.x.y.o/nn' (optional when accessing an
                      existing VPC).

        Returns:
          Vpc object reference

        """
        vpc = self.get_vpc(name)
        if not vpc is None:
            # A VPC tagged with this name presently exists
            v = Vpc(self.resource, self.client, CidrBlock, vpc)
        else:
            # This is a new VPC
            v = Vpc(self.resource, self.client, CidrBlock, None)
            tag = v.vpc.create_tags(Tags=[{'Key': 'Name', 'Value': name}, ])

        self.vpcs[name] = v

        return v

    def get_vpc(self, vpc_name):
        """Searches for a VPC that has been tagged with the specified name.

        Args:
            vpc_name	- The Name tag of the desired VPC

        Returns:
            Reference to the matching VPC
            None if no match is found

        """
        # Iterate through the VPCs, looking for one with a matching 'Name' tag.
        for vpc in self.resource.vpcs.all():
            if not vpc.tags is None:
                for tag in vpc.tags:
                    if tag["Key"] == 'Name':
                        if tag["Value"] == vpc_name:
                            return vpc

        # We did not find a match
        return None

    def get_vpc_by_id(self, vpc_id):
        """Searches for a VPC that with the specified ID.

        Args:
            vpc_id	- The ID of the desired VPC

        Returns:
            Reference to the matchng VPC
            None if no match is found

        """
        # Iterate through all the VPCs, looking for one with a matching ID
        for vpc in self.resource.vpcs.all():
            if vpc.id == vpc_id:
                return vpc

        # We did not find a match
        return None

    def add_keypair(self, name):

        # Create the key pair
        key_pair = self.resource.create_key_pair(KeyName=name)

        # Add a method to save the key material
        key_pair.save = types.MethodType(_keypair_save, key_pair)

        return key_pair

    def get_keypair_info(self, name):
        """Searches for keypair info with the given name.  This indicates the keypair
        exists.

        Args:
            name	- The Name attribute of the desired keypair

        Returns:
            Reference to the matching keypair info object
            None if no match is found

        """
        # Iterate through the keypairs, looking for one with a matching 'Name' tag.
        for kp in self.resource.key_pairs.all():
            if kp.name == name:
                return kp

        # We did not find a match
        return None

    def delete_keypair(self, kp):
        """Deletes a keypair.

        Args:
            kp - Keypair object

        Returns:
            nothing

        """
        try:
            f = kp.name + '.pem'
            kp.delete()
            if os.path.isfile(f):
                os.remove(f)
        except Exception as e:
            log.error("Failed to delete keypair: {0}".format(e))

    def get_volume_id(self, instance_id, volume_name):
        """Retrieves the volumne ID of a named volume associated with an instance.

        Args:
            instance_id - ID of the instance in question
            volume_name - Name of the volume for which the volume ID is to be found

        Returns:
            Volume ID of the specified volume
            None if volume name is not found

        """
        instance = self.resource.Instance(instance_id)
        for v in instance.volumes.all():
            attachments = v.attachments[0]
            if attachments.get('Device', None) == volume_name:
                return attachments.get('VolumeId')

        # Not found
        return None

    def create_snapshot(self, volume_id, name, source, description=None):
        """Creates and tags a snapshot of the specified volume.

        Args:
            volume_id   - ID of the volume
            name        - Name to be given the snapshot
            source      - The source qcow2 file from which the image was derived (this
                          gets saved as a tag for reference)
            description - Optional description for the snapshot (defaults to the name)

        Returns:
            Snapshot ID
            None if an error occurs

            TBD: Any additional error handling needed?

        """

        # Handle optional description
        if description is None:
            description = name

        # Create the snapshot
        snapshot = self.resource.create_snapshot(VolumeId=volume_id, Description=description)

        # Wait for it to be ready
        log.info("Waiting for snapshot to complete.  This may take several minutes.")
        progress_ind = '.'
        time.sleep(30)
        snapshot.load()
        while snapshot.state != 'completed':
            log.info(progress_ind)
            progress_ind += '.'
            time.sleep(15)
            snapshot.load()
        log.info("Snapshot is ready, ID = {0}".format(snapshot.id))

        # Add Name and Source tags
        snapshot.create_tags(Tags=[{'Key': 'Name', 'Value': name},
                                   {'Key': 'Source', 'Value': source}])

        # Done
        return snapshot.id

    def register_ngfwv_ami(self, snap_id, name, description):
        """Registers an NGFWv (FMCv or FTDv) snapshot as an AMI.

        Args:
            snap_id     - ID of the snapshot to be registered
            name        - Name to be given to the AMI
            description - Description for the AMI

        Returns:
            AMI ID
            None if an error occurs

        """

        # Create a block device map containing the snapshot ID
        bdm = [
            {
                'DeviceName': '/dev/xvda',
                'Ebs': {
                    'SnapshotId': snap_id,
                }
            },
        ]

        # Register the AMI
        try:
            ami = self.resource.register_image(
                Name=name,
                Description=description,
                SriovNetSupport="simple",
                Architecture="x86_64",
                BlockDeviceMappings=bdm,
                VirtualizationType="hvm",
                RootDeviceName="/dev/xvda")
        except Exception as e:
            log.error("AMI failed to register: {0}; Exception = {1}".format(name, e))
            return None

        # Done
        log.info("AMI created; ID = {0}".format(ami.id))
        return ami.id

