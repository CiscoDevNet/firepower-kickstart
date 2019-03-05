##########################################################
#
#   Name:   AzureCLI
#
#   Purpose:  To create a class that contains functions
#             to support connections to supporting Linux
#             this is the base class.
#
#
###########################################################
import re
import logging
import time
import yaml
import os
import ast
from subprocess import check_output

try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric

log = logging.getLogger(__name__)


class AzureCLI:
    """ This is the base class for the Azure CLI. It allows the user to login and
    perform Base manipulations of Azure. The login can be performed by using one of two methods:
    the first one requires Application-ID, Directory-ID and Auth-Key; the second one requires
    a Username and Password combination.
    """

    def __init__(self, appid=None, dirid=None, key=None, username=None, pw=None):

        """ The constructor of the AzureCLI class.

        :param appid: the Azure Application ID to connect to (default: None)
        :param dirid: the Azure Directory ID to connect to (default: None)
        :param key: the Azure Secret Key used to connect (default: None)
        :param username: the Azure username (default: None)
        :param pw: the Azure Password (default: None)

        """

        self.type = 'azure'
        # Check which method using to login confirm all needed parameters included
        if (appid and dirid and key):
            self.appid = appid
            self.dirid = dirid
            self.key = key
        elif (username and pw):
            self.username = username
            self.pw = pw
        else:
            raise ValueError("Either use Application-ID, Directory-ID and Auth-Key or Username and PW to login," \
                             " make sure to provide all parameters of your chosen method")

        self.is_logged_in = False
        
        # send metrics to grafana
        publish_kick_metric('azure.azure.init', 1)

    '''
    ************************************
    Azure Connectivity Functions
    ************************************
    '''

    def login_azure_cli(self):

        """ This method checks that Azure CLI is installed, then it logs in with the method
        that the Azure object was initialized with (Application-ID, Directory-ID and Auth-Key or Username
        and Password). If Azure CLI is not installed, the method will attempt to install it (this will only
        work on machines that have root logged in or machines logged in with users that have admin permissions)

        """

        # Confirm Azure CLI installed
        try:
            output = check_output("which az", shell=True)
        except Exception as e:
            log.info("Azure CLI not installed on this machine : %s" % e)
            # Install Azure CLI
            try:
                log.info("Attempting to install Azure-CLI, can take a few minutes")
                output = check_output("pip install azure-cli", shell=True)
                log.info("Azure CLI installed")
            except Exception as e:
                log.error("Unable to install Azure CLI: %s" % e)
                log.error(output)
                raise

        # Confirm able to login
        if self.appid:
            try:
                # Try to login with app-id, dir-id and auth-key
                check_output(
                    "az login -u %s --service-principal --tenant %s -p %s" % (self.appid, self.dirid, self.key),
                    shell=True)
            except Exception as e:
                log.error("Unable to logon to Azure with App-ID, Dir-ID and Auth-Key %s" % e)
                raise

        elif self.username:
            try:
                # Try to login with username and pw
                check_output("az login -u %s -p %s" % (self.username, self.pw), shell=True)
            except Exception as e:
                log.error("Unable to logon to Azure with Username and Password %s" % e)
                raise

        log.info("Logged into Azure")
        self.is_logged_in = True

    def disconnect_azure(self):

        """ This method disconnects from Azure CLI

        """

        try:
            # Try to logout
            check_output("az logout", shell=True)
        except Exception as e:
            log.error("Unable to logout %s" % (e))

    '''
    ************************************
    Azure Resource Group Functions
    ************************************
    '''

    def create_rg(self, rg_name, location="eastus"):

        """ This method creates a new resource group.

        :param rg_name: the name of the resource group to be created (user-defined)
        :param location: the location for the resource group (default = "eastus")

        """

        try:
            # Try create resource group
            check_output("az group create --name %s --location %s" % (rg_name, location), shell=True)
        except Exception as e:
            log.error("Unable to create rg %s: %s" % (rg_name, e))
            raise

    def delete_rg(self, rg_name):

        """ This method deletes the existing resource group.

        :param rg_name: the name of the resource group that will be deleted

        """

        try:
            # Try to logout
            check_output("az group delete --name %s -y" % rg_name, shell=True)
        except Exception as e:
            log.error("Unable to delete rg %s: %s" % (rg_name, e))
            raise

    def list_rg(self, tags={'location': 'eastus'}, json=False):

        """ This method gets a list of Azure resource groups based on the dictionary passed in tags

        :param tags: a dictionary containing a tag ID and a tag value (default = {'location':'eastus'}
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure resource groups
        """

        # Concantinate all tags into a single string to pass to Azure ClI
        tag_str = ""
        for tag in tags:
            tag_str += "[?%s=='%s']" % (tag, tags[tag])

        if (json):
            out = check_output('az group list --query "%s"' % tag_str, shell=True)
        else:
            out = check_output('az group list --query "%s" -o table' % tag_str, shell=True)

        # Check data isn't empty
        assert not out.isspace(), "No Resource Groups information collected"
        return out.decode('utf-8')

    def show_rg(self, rg_name, json=False):

        """ This method gets data about a specific Azure resource group

        :param rg_name: the name of the Azure resource group for which data will be retrieved
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: data about an Azure resource group
        """

        if (json):
            out = check_output('az group show --name %s' % rg_name, shell=True)
        else:
            out = check_output('az group show --name %s -o table' % rg_name, shell=True)

            # Check data isn't empty
        assert not out.isspace(), "No information for Resource Group %s collected" % rg_name
        return out.decode('utf-8')

    '''
    ************************************
    Azure VNET Functions
    ************************************
    '''

    def create_vnet(self, name, rg_name, add_prefix=None, location="eastus", subnet_name=None, subnet_prefix=None):

        """ This method created a new Vnet (the add_prefix, subnet_name and subnet_prefix can be left
        as defaults in order to use Azure's default prefix; in order to create a Vnet with a defined prefix and
        a subnet, add values for the add_prefix, subnet_name and subnet_prefix)

        :param name: the name of the Azure Vnet
        :param rg_name: the name of the resource group that will be created
        :param add_prefix: the address prefix of the Vnet (the default is the same as the Azure default: None)
        :param location: the location for the resource group (default = None)
        :param subnet_name: (optional) the name of the subnet to add (default = None)
        :param subnet_prefix: (optional) the subnet prefix to add (default = None)

        """

        try:
            # Try to create vnet with or without subnet depending on parameters defined
            if add_prefix and subnet_prefix and subnet_name:
                check_output("az network vnet create -g %s -n %s --location %s --address-prefix %s" \
                             " --subnet-name %s --subnet-prefix %s" % (rg_name, name, location, add_prefix, \
                                                                       subnet_name, subnet_prefix), shell=True)
            else:
                check_output("az network vnet create -g %s -n %s --location %s" % (rg_name, name, location), shell=True)
        except Exception as e:
            log.error("Unable to create vnet %s: %s" % (rg_name, e))
            raise

    def delete_vnet(self, name, rg_name):

        """  This method deletes an existing Vnet along with its resource group

        :param name: the name of the Vnet that will be deleted
        :param rg_name: the name of the resource group to be deleted

        """

        try:
            # Try to logout
            check_output("az network vnet delete -n %s -g %s" % (name, rg_name), shell=True)
        except Exception as e:
            log.error("Unable to delete vnet %s: %s" % (name, e))
            raise

    def list_vnet(self, rg_name, json=False):

        """ This method gets a list of Azure Vnets contained in a certain resource group

        :param rg_name: the name of the resource group you wan to find Vnets associated with
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure Vnets in a resource group
        """

        if (json):
            out = check_output('az network vnet list --resource-group %s' % rg_name, shell=True)
        else:
            out = check_output('az network vnet list --resource-group %s -o table' % rg_name, shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to list VNET information"
        return out.decode('utf-8')

    def show_vnet(self, name, rg_name, json=False):

        """ This method gets data about a specific Azure Vnet associated to a resource group

        :param name: the name of the Vnet for which data will be retrieved
        :param rg_name: the name of the resource group for which data will be retrieved
        :param json: set True for data to be retrieved in .json format (default = False)

        :return:  data about an Azure Vnet associated to resource group
        """

        if (json):
            out = check_output('az network vnet show -g %s -n %s' % (rg_name, name), shell=True)
        else:
            out = check_output('az network vnet show -g %s -n %s -o table' % (rg_name, name), shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable get information about VNET %s" % name
        return out.decode('utf-8')

    def add_vnet_subnet(self, name, rg_name, vnet_name, address_prefix, route_table=None):

        """ This method creates a new subnet and attaches it to a Vnet

        :param name: the name of the Azure subnet
        :param rg_name: the name of the resource group to be created
        :param vnet_name: the name of the Vnet which the subnet will be associated to
        :param address_prefix: the subnet prefix to be added
        :param route_table: (optional) the route-table you want to associate it with (default = None)

        """

        try:
            # Try to create subnet and attach to a vnet
            if route_table:
                check_output(
                    "az network vnet subnet create -g %s -n %s --vnet-name %s --address-prefix %s --route-table %s" \
                    % (rg_name, name, vnet_name, address_prefix, route_table), shell=True)
            else:
                check_output("az network vnet subnet create -g %s -n %s --vnet-name %s --address-prefix %s" \
                             % (rg_name, name, vnet_name, address_prefix), shell=True)
        except Exception as e:
            log.error("Unable to create vnet subnet %s: %s" % (name, e))
            raise

    def delete_vnet_subnet(self, name, rg_name, vnet_name):

        """ This method deletes a subnet associated to a Vnet

        :param name: the name of the Azure subnet that will be deleted
        :param rg_name: the name of the resource group
        :param vnet_name: the name of the Vnet that the subnet is associated to

        """

        try:
            # Try to delete a subnet
            check_output("az network vnet subnet delete -g %s -n %s --vnet-name %s" \
                         % (rg_name, name, vnet_name), shell=True)
        except Exception as e:
            log.error("Unable to delete subnet %s: %s" % (name, e))
            raise

    def list_vnet_subnets(self, name, rg_name, json=False):

        """ This method gets data about an Azure subnet

        :param name: the name of the Vnet for which the data will be retrieved
        :param rg_name: the name of the resource group that the subnet is associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of subnet data for an Azure Vnet
        """

        if (json):
            out = check_output('az network vnet subnet list -g %s --vnet-name %s' % (rg_name, name), shell=True)
        else:
            out = check_output('az network vnet subnet list -g %s --vnet-name %s -o table' % (rg_name, name),
                               shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to list VNET Subnets information"
        return out.decode('utf-8')

    def show_vnet_subnet(self, name, rg_name, vnet_name, json=False):

        """ This method gets data about a specific Azure subnet associated to a Vnet

        :param name: the name of the subnet for which data will be retrieved
        :param rg_name: the name of the resource group that the Vnet is associated with
        :param vnet_name: the name of the Vnet that the subnet is associated with
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: data about a specific subnet associated to an Azure Vnet
        """

        if (json):
            out = check_output('az network vnet subnet show -g %s -n %s --vnet-name %s' % (rg_name, name, vnet_name),
                               shell=True)
        else:
            out = check_output('az network vnet subnet show -g %s -n %s --vnet-name %s -o table' \
                               % (rg_name, name, vnet_name), shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to get information about Subnet VNET %s" % name
        return out.decode('utf-8')

    '''
    ************************************
    Azure Deployment Functions
    ************************************
    '''

    def create_parameter_file(self, parameter_template, testbed_file, output_file_path, yaml_object="azure"):

        """ This method creates a parameter file from the information in the testbed .YAML file and the
        parameter template file. The method combines the values from the testbed .YAML file and places them
        in appropriate placeholders in the parameter template files. The parameter file that is outputted
        can be then passed to the deployment methods to be used with the deployment templates

        :param parameter_template: the parameter template file to use
        :param testbed_file: the testbed .YAML file that contains the data for the parameter template
        :param output_file_path: path of the outputted file
        :param yaml_object: Object in the YAML file; the dictionary containing the variable to be placed
                            in the parameter_template live under i.e. testbed[azure] or testbed[asa];
                            default = "azure" if the variables aren't under any object and are called by
                            testbed[parameter]

        """

        new_parameters = ""
        # Open files
        testbed = yaml.load(open(testbed_file, 'r'))
        parameters = open(parameter_template, 'r')
        new_param_file = open(output_file_path, 'w+')

        # Get specific object in testbed YAML file - Will usually be 'azure'
        if yaml_object:
            testbed = testbed[yaml_object]

        # Check each line in parameter template for place holder
        # if placeholder found update with relevant data from testbed file
        lines = parameters.readlines()
        for line in lines:
            if '[' and ']' in line:
                m = re.search(r'\[(\w*)\]', line)
                new_line = line.replace(m.group(0), '"' + testbed[m.group(1)] + '"')
                line = new_line
            # Write new parameter file
            new_parameters += (line)
            new_param_file.write(line)

        # Close all files
        new_param_file.close()
        parameters.close()

    def deploy_from_template_custom_image(self, resource_group, storage_name, image_path, template_file,
                                          parameter_file, location='eastus', storage_container_name="images"):

        """ This method creates a new deployment using a custom image. First, a new resource group and a storage
        container must be created in order to store the custom image. Then, the custom image has to be copied to
        the new storage container. Finally, the method will attempt to deploy the template that was passed in.

        Note: if the deployment fails, the cleanup must perform the deletion of the resource group

        :param resource_group: the name of the resource group that will be created
        :param storage_name: the name of the storage container that will be created
        :param image_path: the path to the custom image that will be copied to the storage container and then deployed
        :param template_file: the path to the file that will be used for deployment
        :param parameter_file: the parameter file that will be combined with the template file for deployment
        :param location: the location of deployment (default = 'eastus')
        :param storage_container_name: the name of the storage container (default = 'images'); this name is defined
                                        in the template file; it is best not to change this name to a different value
                                        unless you have a matching value in the template file

        """

        try:
            # Create Resource Group
            self.create_rg(resource_group, location)
            log.info("Resource Group %s Created" % resource_group)

            # Create Storage and Storage Container
            self.create_storage(storage_name, resource_group, location)
            log.info("Storage %s Created" % storage_name)

            self.create_storage_container(storage_container_name, resource_group, storage_name)
            log.info("Storage Container %s Created" % storage_container_name)

            # Copy custom image onto storage container
            self.upload_vhd_to_container(storage_container_name, storage_name, resource_group, image_path)
            log.info("Image %s uploaded to Storage container %s" % (image_path, storage_container_name))

        except Exception as e:
            log.error("Unable to set up the resource group and storage to deploy template to: %s" % e)
            raise

        # Deploy template
        try:
            # Try create deployment
            log.info("Image on Azure, now deploying Template, can take a few minutes")
            check_output("az group deployment create -g %s --template-file %s --parameters %s" % (
                resource_group, template_file, parameter_file), shell=True)
            log.info("Template deployed")
        except Exception as e:
            log.error("Unable to deploy template %s" % e)
            raise

        # send metrics to grafana
        publish_kick_metric('azure.azure.deploy', 1)

    def deploy_from_template_mp_image(self, rg_name, location, template_file, parameter_file):

        """ This method creates a new deployment using a Marketplace Image, then checks if a resource group
        is created, otherwise it will create a new one.

        Note: if the deployment fails, the cleanup must perform the deletion of the resource group

        :param rg_name: the name of the resource group
        :param location: the location of the Marketplace Image
        :param template_file: the path to the Azure template file used for deployment
        :param parameter_file: the path to the file containing parameters needed for deployment

        """

        # Check if resource group exists - If not create it
        try:
            # See if able to get resource group information
            self.show_rg(rg_name)
            log.info("Resource group %s already exists" % rg_name)
        except:
            # If unable to get rg information make new one then continue
            log.info("Creating Resoucre group %s" % rg_name)
            self.create_rg(rg_name, location)

        # Deploy template
        try:
            # Try create deployment
            out = check_output("az group deployment create -g %s --template-file %s --parameters %s" % (
                rg_name, template_file, parameter_file), shell=True)
        except Exception as e:
            log.error("Unable to deploy template: %s" % (e))
            raise

        # send metrics to grafana
        publish_kick_metric('azure.azure.deploy', 1)

    '''
    ************************************
    Azure VM Functions
    ************************************
    '''

    def deploy_linux(self, name, rg_name, vnet_name, subnet_name, username="automation-admin", pw="Cisco-123123"):

        """ This method creates a basic Linux VM

        :param name: the name of the Linux VM
        :param rg_name: the name of the resource group associated with the Linux VM
        :param vnet_name: the name of the Vnet
        :param subnet_name: the name of the subnet in the Vnet
        :param username: the username of the VM (default = 'automation-admin')
        :param pw: the password of the VM (default = 'Cisco-123123')

        :return: Output from successful deployment - Includes public and private IP addresses in dictionary
        """

        # Deploy Linux
        try:
            # Try create deployment
            out = check_output(
                "az vm create -n %s -g %s --admin-username %s --admin-password %s --image UbuntuLTS --vnet-name %s --subnet %s" \
                % (name, rg_name, username, pw, vnet_name, subnet_name), shell=True)
            out = out.decode('utf-8')
        except Exception as e:
            log.error("Unable to deploy Linux: %s" % (e))
            raise

        # Confirm VM running is seen in output
        assert "VM running" in out, "Linux Deployment not sucessful: %s" % out

        # send metrics to grafana
        publish_kick_metric('azure.azure.deploy', 1)

        return out

    def delete_linux(self, name, rg_name, delete_associated_resources=True):

        """ This method deletes an existing Linux VM

        :param name: the name of the Linux VM
        :param rg_name: the name of the resource group associated with the Linux VM that will be deleted
        :param delete_associated_resources: specifies whether associated resources should be removed as well
        """

        # Delete Linux VM and all things associated with it
        log.info("Deleting Linux VM %s" % name)
        try:
            check_output("az vm delete -n %s -g %s --yes" % (name, rg_name), shell=True)
        except Exception as e:
            log.error("Unable to delete Linux: %s" % (e))
            raise

        remaining_vms = self.list_vm(rg_name)
        assert name not in remaining_vms, "VM Still available on Azure, command failed!"
        log.info("VM Successfully removed")

        if not delete_associated_resources:
            return

        log.info("Try to delete remaining resources associated with linux %s" % name)
        try:
            # delete associated disk
            self.delete_disk(rg_name, name)
            log.info("Deleted disk")

            # delete associated NIC
            self.delete_nic(rg_name, name)
            log.info("Deleted network interface")

            # delete associated NSG
            self.delete_nsg(rg_name, name)
            log.info("Deleted network security group")

            # delete associated Public IP
            self.delete_public_ip(rg_name, name)
            log.info("Deleted public IP")

            # Check all resources with name are deleted
            output = self.list_resources(rg_name)
            assert name not in output, "Some resources with name %s remaining: %s" % (name, output)
            log.info("All additional resources sucessfully deleted")

        except Exception as e:
            log.error("Unable to delete all resources associated with Linux %s : %s" % (name, e))
            raise

    def list_vm(self, rg_name, json=False):

        """ This method lists the Azure VMs associated to a resource group

        :param rg_name: the name of the resource group that the VMs are associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure VMs associated to a resource group
        """

        try:
            # Try to delete route table
            if (json):
                out = check_output("az vm list -g %s" % (rg_name), shell=True)
            else:
                out = check_output("az vm list -g %s -o table" % (rg_name), shell=True)
        except Exception as e:
            log.error("Unable to list vms %s" % (e))
            raise

        return out.decode('utf-8')

    def list_resources(self, rg_name, json=False):

        """ This method lists the Azure resources associated with a resource group

        :param rg_name: the name of the resource group that the resources are associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure resources associated to a resource group
        """

        try:
            # Try to delete route table
            if (json):
                out = check_output("az resource list -g %s" % (rg_name), shell=True)
            else:
                out = check_output("az resource list -g %s -o table" % (rg_name), shell=True)
        except Exception as e:
            log.error("Unable to list resources %s" % (e))

        # Check data isn't empty
        assert not out.isspace(), "Unable to list Resources associated with resource group %s" % rg_name
        return out.decode('utf-8')

    '''
    ************************************
    Azure Route-Table and Route Functions
    ************************************
    '''

    def show_all_route_tables(self, rg_name, json=False):

        """ This method gets data about Azure route tables associated to a resource group

        :param rg_name: the name of the resource group for which the route-tables will be retrieved
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: data about Azure route tables associated to a resource group
        """

        if (json):
            out = check_output("az network route-table list -g %s" % rg_name, shell=True)
        else:
            out = check_output("az network route-table list -g %s -o table" % rg_name, shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to list route tables associated with resource group %s" % rg_name
        return out.decode('utf-8')

    def show_route_table(self, rg_name, route_table, json=False):

        """ This method gets data about a specific Azure route table. In order for the information to be seen,
        the json parameter must be set to True

        :param rg_name: the name of the resource group that the route table is associated to
        :param route_table: the name of the route table for which the data will be collected
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: data about the Azure route table (as a string or .json)
        """

        if (json):
            out = check_output("az network route-table show -g %s -n %s" % (rg_name, route_table), shell=True)
        else:
            out = check_output("az network route-table show -g %s -n %s -o table" % (rg_name, route_table), shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable get information about route-table %s" % route_table
        return out.decode('utf-8')

    def show_routes(self, rg_name, route_table, json=False):

        """ This method gets data about the Azure routes in a route table

        :param rg_name: the name of the resource group that the route table is associated to
        :param route_table: the name of the route table for which route information will be retrieved
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: data about the Azure route table (as a string or .json)
        """

        if (json):
            out = check_output("az network route-table route list -g %s --route-table-name %s" % (rg_name, route_table),
                               shell=True)
        else:
            out = check_output(
                "az network route-table route list -g %s --route-table-name %s -o table" % (rg_name, route_table),
                shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable get information about routes in route-table %s" % route_table
        return out.decode('utf-8')

    def add_route_table(self, rg_name, route_table):

        """ This method adds an Azure route table

        :param rg_name: the name of the resource group that the route table is associated to
        :param route_table: the name of the route table to be added

        """

        try:
            # Try to add route table
            check_output("az network route-table create -g %s -n %s" % (rg_name, route_table), shell=True)
        except Exception as e:
            log.error("Unable to add route-table %s: %s" % (route_table, e))
            raise

    def delete_route_table(self, rg_name, route_table):

        """ This method deletes an Azure route table

        :param rg_name: the name of the resource group that the route table is associated to
        :param route_table: the name of the route table that will be deleted

        """

        try:
            # Try to delete route table
            check_output("az network route-table delete -g %s -n %s" % (rg_name, route_table), shell=True)
        except Exception as e:
            log.error("Unable to delete route-table %s: %s" % (route_table, e))
            raise

    def add_route(self, rg_name, route_table, route, prefix, next_hop_add, next_hop_type="VirtualAppliance"):

        """ This method adds an Azure route

        :param rg_name: the name of the resource group that the route table is associated to
        :param route_table: the name of the route table where the route will be added
        :param route: the name of the route to be added
        :param prefix: the address prefix to which the route applies
        :param next_hop_add: the type of Azure hop that the packet should be sent to.
                             Allowed values: Internet, None, VirtualAppliance, VirtualNetworkGateway, VnetLocal.
                             (default = 'VirtualAppliance')
        :param next_hop_type: the IP address that the packets should be forwarded to when using the VirtualAppliance
                              hop type

        """

        try:
            # Try to create route
            check_output("az network route-table route create -g %s -n %s --address-prefix " \
                         "%s --next-hop-type %s --route-table-name %s --next-hop-ip-address %s" \
                         % (rg_name, route, prefix, next_hop_type, route_table, next_hop_add), shell=True)
        except Exception as e:
            log.error("Unable to add route %s: %s" % (route, e))
            raise

    def delete_route(self, rg_name, route_table, route):

        """ This method deletes an Azure route

        :param rg_name: the name of the resource group that the route table is associated with
        :param route_table: the name of the route table from which the route will be deleted
        :param route: the name of the route to be deleted

        """

        try:
            # Try to delete route
            check_output("az network route-table route delete -g %s -n %s --route-table-name %s" \
                         % (rg_name, route, route_table), shell=True)
        except Exception as e:
            log.error("Unable to delete route %s: %s" % (route, e))
            raise

    '''
    ************************************
    Azure Network Functions
    ************************************
    '''

    def delete_public_ip(self, rg_name, vm_name, pip_name=None):

        """ This method deletes an Azure public IP

        :param rg_name: the name of the resource group that the public IP is associated to
        :param vm_name: the name of the VM associated to the public IP (it is important to be deleted)
        :param pip_name: (optional) the public IP to be deleted; the default value will use the VM name and
                         its public IP (default = None)

        """

        # Check vm Deleted
        assert vm_name not in self.list_vm(rg_name), "VM is still present delete before deleting Public IP"

        # If disk name not given get disk name
        if not pip_name:
            pip_name = vm_name + "PublicIP"

        try:
            # Try to delete public IP
            check_output("az network public-ip delete -n %s -g %s" % (pip_name, rg_name), shell=True)
        except Exception as e:
            log.error("Unable to delete Public IP %s: %s" % (pip_name, e))
            raise

    def list_pip(self, rg_name, json=False):

        """ This method gets a list of Azure public IPs associated to a resource group

        :param rg_name: the name of the resource group that the public IPs are associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure public IPs associated to a resource group (string or json format)
        """

        try:
            # List public IP
            if (json):
                out = check_output("az network public-ip list -g %s" % (rg_name), shell=True)
            else:
                out = check_output("az network public-ip list -g %s -o table" % (rg_name), shell=True)
        except Exception as e:
            log.error("Unable to list public-ip %s" % (e))
            raise

        # Check data isn't empty
        assert not out.isspace(), "Unable to list public IPs"
        return out.decode('utf-8')

    def get_public_ip_from_vm(self, pip_name, rg_name):

        """ This method gets a public IP from an existing VM

        :param pip_name: the public IP
        :param rg_name: the name of the resource group that the VM is associated to

        :return: the public IP in string format
        """

        # Get all public IPs associated with resource group
        out = self.list_pip(rg_name)
        assert out, "Unable to get Public IP information: %s" % out.decode('utf-8')

        # Use regex to find public IP
        m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}) .* %s' % pip_name, out)
        assert m, "Unable to find public ip in output %s" % out
        return m.group(1).strip()

    def list_nsg(self, rg_name, json=False):

        """ This method gets a list of Azure Network Security Groups associated to a resource group

        :param rg_name: the name of the resource group that the Azure NSG are associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure Network Security Groups associated to a resource group (string or json format)
        """

        try:
            # Try to list nsg
            if (json):
                out = check_output("az network nsg list -g %s" % (rg_name), shell=True)
            else:
                out = check_output("az network nsg list -g %s -o table" % (rg_name), shell=True)
        except Exception as e:
            log.error("Unable to list nsg %s" % (e))
            raise

        # Check data isn't empty
        assert not out.isspace(), "Unable to list network securit groups associated with resource group %s" % rg_name
        return out.decode('utf-8')

    def delete_nsg(self, rg_name, vm_name, nsg_name=None):

        """ This method deletes an Azure Network Security Group

        :param rg_name: the name of the resource group that the Azure NSG is associated to
        :param vm_name: the name of the VM that the Azure NSG is associated to (it is important to be deleted)
        :param nsg_name: (optional) the name of the Azure NSG to be deleted; the default value will use the VM name and
                         its NSG (default = None)

        """

        # Check vm Deleted
        assert vm_name not in self.list_vm(rg_name), "VM is still present delete before deleting NSG"

        # If nsg name not given get nsg name
        if not nsg_name:
            nsg_name = vm_name + "NSG"

        try:
            # Try to delete nsg
            check_output("az network nsg delete -n %s -g %s" % (nsg_name, rg_name), shell=True)
        except Exception as e:
            log.error("Unable to delete NSG %s: %s" % (nsg_name, e))
            raise

    def list_nic(self, rg_name, json=False):

        """ This method lists the Azure Network Interface associated with a resource group

        :param rg_name: the name of the resource group that the Network Interface is associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure Network Interfaces associated to a resource group (string or json format)
        """

        try:
            # List azure nics
            if (json):
                out = check_output("az network nic list -g %s" % (rg_name), shell=True)
            else:
                out = check_output("az network nic list -g %s -o table" % (rg_name), shell=True)
        except Exception as e:
            log.error("Unable to list nic %s" % (e))
            raise

        # Check data isn't empty
        assert not out.isspace(), "Unable to list network interfaces associated with resource group %s" % rg_name
        return out.decode('utf-8')

    def delete_nic(self, rg_name, vm_name, nic_name=None):

        """ This method deletes an Azure Network Interface

        :param rg_name: the name of the resource group that the Network Interface is associated to
        :param vm_name: the name of the VM that the Network Interface is associated to (it is important to be deleted)
        :param nic_name: (optional) the name of the Network Interface to delete; the default value will use the VM name
                                    and its NIC (default = None)

        """

        # Check vm Deleted
        assert vm_name not in self.list_vm(rg_name), "VM is still present delete before deleting NIC"

        # If nic name not given get nsg name
        if not nic_name:
            nic_name = vm_name + "VMNic"

        try:
            # Try to delete nic
            check_output("az network nic delete -n %s -g %s" % (nic_name, rg_name), shell=True)
        except Exception as e:
            log.error("Unable to delete NIC %s: %s" % (nic_name, e))
            raise

    '''
    ************************************
    Azure Public IP Functions
    ************************************
    '''

    def delete_disk(self, rg_name, vm_name, disk_name=None):

        """ This methods deletes an Azure Managed disk

        :param rg_name: the name of the resource group that the disk is associated with
        :param vm_name: the name of the VM that the Disk is associated to (it is important to be deleted)
        :param disk_name: (optional) the name of the disk to be deleted; the default value will use the VM name to
                          find the name of the disk (default = None)

        """

        # Check vm Deleted
        assert vm_name not in self.list_vm(rg_name), "VM is still present delete before deleting disk"

        # If disk name not given get disk name
        if not disk_name:
            disk_name = self.get_disk_name(rg_name, vm_name)

        try:
            # Try to delete disk
            check_output("az disk delete -n %s -g %s --yes" % (disk_name, rg_name), shell=True)
        except Exception as e:
            log.error("Unable to delete disk %s: %s" % (disk_name, e))
            raise

    def list_disk(self, rg_name, json=False):

        """ This method lists Azure Managed disks associated to a resource group

        :param rg_name: the name of the resource group that the disks are associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure Managed disks associated to a resource group (string or json format)
        """

        try:
            # Try to delete route table
            if (json):
                out = check_output("az disk list -g %s" % (rg_name), shell=True)
            else:
                out = check_output("az disk list -g %s -o table" % (rg_name), shell=True)
        except Exception as e:
            log.error("Unable to list disks %s" % (e))

        return out.decode('utf-8')

    def get_disk_name(self, rg_name, vm_name):

        """ This method lists Azure Managed disks associated to a resource group and extracts the name of the disk
        based on the name of the VM that the disk is associated to. The disk's name will usually be in the following
        format: 'vm_name_0sDisk_1_...'

        :param rg_name: the name of the resource group that the disks are associated to
        :param vm_name: the name of the VM

        :return: the name of disks associated to a the VM (if a disk is not found, the method returns None)
        """

        disks = self.list_disk(rg_name)

        # Confirm vm we want is in Disk list
        assert vm_name in disks, "VM %s is not present in disks %s" % (vm_name, disks)

        # Extract disk name
        m = re.search(r"(" + re.escape(vm_name) + r"_\w*)", disks)
        try:
            disk_name = m.group(1).strip()
        except:
            # Do not raise exception just continue on
            log.error("Unable to find VM disk name in disks")
            disk_name = None

        return disk_name

    '''
    ************************************
    Azure Storage Functions
    ************************************
    '''

    def create_storage(self, name, rg_name, location="eastus", sku="Standard_LRS"):

        """ This message creates a new storage account

        :param name: the name of the Azure storage account
        :param rg_name: the name of the resource group where the storage account will be created
        :param location: the location of the resource group (default = "eastus")
        :param sku: the storage account's SKU; accepted values: Premium_LRS, Standard_GRS, Standard_LRS,
                    Standard_RAGRS, Standard_ZRS; default = "Standard_LRS"

        """

        try:
            # Try to create storage account
            check_output("az storage account create -g %s -n %s -l %s --sku %s"
                         % (rg_name, name, location, sku), shell=True)
        except Exception as e:
            log.error("Unable to create storage %s: %s" % (name, e))
            raise

    def delete_storage(self, name, rg_name):

        """ This method deletes an existing storage account

        :param name: the name of the storage account that will be deleted
        :param rg_name: the name of the resource group that will be deleted

        """

        try:
            # Try to logout
            check_output("az storage account delete -n %s -g %s --yes" % (name, rg_name), shell=True)
        except Exception as e:
            log.error("Unable to delete storage %s: %s" % (name, e))
            raise

    def list_storage(self, rg_name, json=False):

        """ This method gets a list of Azure storage accounts based on the resource group

        :param rg_name: the name of the resource group for which associated storage accounts will be retrieved
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of Azure storage accounts based on the resource group (string or json format)
        """

        if (json):
            out = check_output('az storage account list -g %s' % rg_name, shell=True)
        else:
            out = check_output('az storage account list -g %s -o table' % rg_name, shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to list storage_accounts associated with resource group %s" % rg_name
        return out.decode('utf-8')

    def show_storage(self, name, rg_name, json=False):

        """ This method gets data about an Azure storage account associated to a resource group

        :param name: the name of the storage account for which data will be retrieved
        :param rg_name: the name of the resource group that the storage account is associated to
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: data about an Azure storage account (string or json format)
        """

        if (json):
            out = check_output('az storage account show -g %s -n %s' % (rg_name, name), shell=True)
        else:
            out = check_output('az storage account show -g %s -n %s -o table' % (rg_name, name), shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to get information about Storage Account %s" % name
        return out.decode('utf-8')

    def get_storage_keys(self, storage_name, rg_name):

        """ This method gets data about Azure Storage Keys

        :param storage_name: the name of the storage account for which data will be retrieved
        :param rg_name: the name of the resource group that the storage account is associated to

        :return: a dictionary of Azure storage keys in format {"keyname":"key", ...}
        """

        out = check_output('az storage account keys list -n %s -g %s' % (storage_name, rg_name),
                           shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to get Storage Account Key information"

        # Decode and format output so it is represented by a list instead of byte string
        out = out.decode('utf-8')
        out = ast.literal_eval(out)

        # Extract keyname and key value
        keys = {}
        for key in out:
            keys[key['keyName']] = key['value']

        return (keys)

    def create_storage_container(self, name, rg_name, storage_name):

        """ This method creates a storage container in an existing Azure storage. The method first gets keys from
        storage in order to use them for authenticating in the container (the first key to be found will be used)

        :param name: the name of the container that will be created
        :param rg_name: the name of the resource group that the storage is associated to
        :param storage_name: the name of the storage account

        """

        # Get key information from storage
        keys = self.get_storage_keys(storage_name, rg_name)
        # Get abritray key from list
        key = list(keys.values())[0]

        try:
            # Try to create storage account
            check_output("az storage container create -n %s --account-name %s --account-key %s"
                         % (name, storage_name, key), shell=True)
        except Exception as e:
            log.error("Unable to create storage container %s: %s" % (name, e))

    def list_storage_container(self, rg_name, storage_name, json=False):

        """ This method lists the storage containers found in an existing Azure storage

        :param rg_name: the name of the resource group that the storage containers are associated to
        :param storage_name: the name of the Azure storage
        :param json: set True for data to be retrieved in .json format (default = False)

        :return: a list of storage containers (string or json format)
        """

        # Get key information from storage
        keys = self.get_storage_keys(storage_name, rg_name)
        # Get abritray key from list
        key = list(keys.values())[0]

        if (json):
            out = check_output('az storage container list --account-name %s --account-key %s'
                               % (storage_name, key), shell=True)
        else:
            out = check_output('az storage container list --account-name %s --account-key %s -o table'
                               % (storage_name, key), shell=True)

        # Check data isn't empty
        assert not out.isspace(), "Unable to list Storage Account information"
        return out.decode('utf-8')

    def delete_storage_container(self, name, rg_name, storage_name):

        """ This method deletes a storage container in an existing Azure storage. The method first gets keys from
        storage in order to use them for authenticating in the container (the first key to be found will be used)

        :param name: the name of the storage container to be deleted
        :param rg_name: the name of the resource group that the storage container is associated to
        :param storage_name: the name of the Azure storage name


        """

        # Get key information from storage
        keys = self.get_storage_keys(storage_name, rg_name)
        # Get abritray key from list
        key = list(keys.values())[0]

        try:
            # Try to create storage account
            check_output("az storage container delete -n %s --account-name %s --account-key %s"
                         % (name, storage_name, key), shell=True)
        except Exception as e:
            log.error("Unable to delete storage container %s: %s" % (name, e))

    def upload_vhd_to_container(self, container_name, storage_name, rg_name, file_path):

        """ This method uploads a VHD file to an existing container. The method first check if the container
        exists, gets the storage key (the first key found will be used), then creates a blob named after the file
        (if there is an error, it will be named 'blob.vhd') - the blob will contain the VHD file and will be used
        for the upload

        :param container_name: the name of the container in which the file will be uploaded
        :param storage_name: the name of the storage account
        :param rg_name: the name of the resource group that the storage is associated to
        :param file_path: the path to the file that will be uploaded (it must be accessible by Kick)

        """

        # Check container exists
        assert container_name in self.list_storage_container(rg_name, storage_name), \
            "Container %s does not currently exist, please create first" % container_name

        # Get key information from storage
        keys = self.get_storage_keys(storage_name, rg_name)
        # Get abritray key from list
        key = list(keys.values())[0]

        # Extract blob name from path - will be file name
        m = re.search(r'^.*[\/\\](.*)', file_path)
        if not m:
            # Unable to extract name - just call it blob.vhd
            blob_name = "blob.vhd"
        else:
            blob_name = m.group(1).strip()

        try:
            # Try to upload file
            check_output("az storage blob upload  -n %s -c %s --account-name %s --account-key %s -f %s -t page"
                         % (blob_name, container_name, storage_name, key, file_path), shell=True)
        except Exception as e:
            log.error("Unable to upload file %s: %s" % (file_path, e))

    def delete_blob(self, container_name, storage_name, rg_name, blob_name):

        """ This method uploads a VHD file to an existing container. The method first check if the container
        exists, gets the storage key (the first key found will be used), then creates a blob named after the file
        (if there is an error, it will be named 'blob.vhd') - the blob will contain the VHD file and will be used
        for the upload

        :param container_name: the name of the container in which the file will be uploaded
        :param storage_name: the name of the storage account
        :param rg_name: the name of the resource group that the storage is associated to
        :param blob_name: the name of the blob to be deleted

        """

        # Get key information from storage
        keys = self.get_storage_keys(storage_name, rg_name)
        # Get abritray key from list
        key = list(keys.values())[0]

        try:
            # Try to delete blob
            check_output("az storage blob delete -n {} -c {} --account-name {} --account-key {}".format(
                blob_name, container_name, storage_name, key), shell=True)
        except Exception as e:
            log.error("Unable to delete blob %s: %s" % (blob_name, e))
