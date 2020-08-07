import logging
import traceback
import sys
from collections import defaultdict
import time
from ats import aetest

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True
    pass

from kick.device2.fxos.app import AppInstance
from kick.device2.fxos.app_handler import AppInstanceUtils
from kick.device2.fxos.interfaces.interface_handler import InterfaceHandler
from kick.device2.fxos.interfaces.physical_interface import PhysicalInterface
from kick.device2.fxos.interfaces.portchannel_interface import PortChannelInterface
from kick.device2.fxos.interfaces.portchannel_subinterface import PortChannelSubInterface
from kick.device2.fxos.interfaces.subinterface import SubInterface
from kick.device2.fxos.logical_device import LogicalDevice
from kick.device2.fxos.logical_device_handler import LogicalDeviceUtils
from kick.device2.fxos.management_bootstrap import ManagementBootstrap, ManagementClusterBootstrap
from kick.device2.fxos.cluster_bootstrap import ClusterBootstrap
from kick.device2.fxos.resource import ResourceProfile
from kick.device2.fxos.resource_profile_handler import ResourceProfileUtils

logger = logging.getLogger(__name__)


def prepare_bootstrap_info(logical_device_info):
    try:
        registration_key = logical_device_info['bootstrap_keys_secret'].get("registration_key")
    except:
        registration_key = None
    try:
        password = logical_device_info['bootstrap_keys_secret'].get("password")
    except:
        password = None
    try:
        firepower_manager_ip = logical_device_info['bootstrap_keys'].get("firepower_manager_ip")
    except:
        firepower_manager_ip = None
    try:
        firewall_mode = logical_device_info['bootstrap_keys'].get("firewall_mode")
    except:
        firewall_mode = None
    try:
        fqdn = logical_device_info['bootstrap_keys'].get("fqdn")
    except:
        fqdn = None
    try:
        dns_servers = logical_device_info['bootstrap_keys'].get("dns_servers")
    except:
        dns_servers = None
    try:
        search_domains = logical_device_info['bootstrap_keys'].get("search_domains")
    except:
        search_domains = None
    try:
        permit_expert_mode = logical_device_info['bootstrap_keys'].get("permit_expert_mode")
    except:
        permit_expert_mode = None
    try:
        management_type = logical_device_info['bootstrap_keys'].get('management_type')
    except:
        management_type = None
    return registration_key, password, firepower_manager_ip, firewall_mode, fqdn, dns_servers, search_domains, permit_expert_mode, management_type


def prepare_management_bootstrap(handle, logical_device_info):
    registration_key, password, firepower_manager_ip, firewall_mode, fqdn, dns_servers, search_domains, permit_expert_mode, management_type = prepare_bootstrap_info(
        logical_device_info)
    try:
        ipv4_ip = logical_device_info['ipv4'].get("ip")
    except:
        ipv4_ip = None
    try:
        ipv4_netmask = logical_device_info['ipv4'].get("netmask")
    except:
        ipv4_netmask = None
    try:
        ipv4_gateway = logical_device_info['ipv4'].get("gateway")
    except:
        ipv4_gateway = None
    try:
        ipv6_ip = logical_device_info['ipv6'].get("ip")
    except:
        ipv6_ip = None
    try:
        ipv6_prefix = logical_device_info['ipv6'].get("prefix")
    except:
        ipv6_prefix = None
    try:
        ipv6_gateway = logical_device_info['ipv6'].get("gateway")
    except:
        ipv6_gateway = None
    return ManagementBootstrap(handle=handle, ipv4_address=ipv4_ip,
                               ipv4_netmask=ipv4_netmask,
                               ipv4_gateway=ipv4_gateway,
                               ipv6_address=ipv6_ip,
                               ipv6_prefix=ipv6_prefix,
                               ipv6_gateway=ipv6_gateway, registration_key=registration_key, password=password,
                               firepower_manager_ip=firepower_manager_ip, firewall_mode=firewall_mode, fqdn=fqdn,
                               dns_servers=dns_servers, search_domains=search_domains,
                               permit_expert_mode=permit_expert_mode, management_type=management_type)


def prepare_intra_cluster_management_bootstrap(handle, logical_device_info):
    registration_key, password, firepower_manager_ip, firewall_mode, fqdn, dns_servers, search_domains, permit_expert_mode, management_type = prepare_bootstrap_info(
        logical_device_info)

    return ManagementClusterBootstrap(handle=handle, ip_config=logical_device_info['ip_config'],
                                      registration_key=registration_key, password=password,
                                      firepower_manager_ip=firepower_manager_ip, firewall_mode=firewall_mode,
                                      fqdn=fqdn, dns_servers=dns_servers, search_domains=search_domains,
                                      permit_expert_mode=permit_expert_mode, management_type=management_type)


def prepare_cluster_bootstrap(handle, logical_cluster_info):
    try:
        chassis_id = logical_cluster_info.get("chassis_id")
    except:
        chassis_id = None
    try:
        ccl_network = logical_cluster_info.get("ccl_network")
    except:
        ccl_network = None
    try:
        cluster_key = logical_cluster_info.get("cluster_key")
    except:
        cluster_key = None
    try:
        cluster_name = logical_cluster_info.get("cluster_name")
    except:
        cluster_name = None
    try:
        site_id = logical_cluster_info.get("site_id")
    except:
        site_id = None
    return ClusterBootstrap(handle=handle, chassis_id=chassis_id, ccl_network=ccl_network, cluster_key=cluster_key,
                            cluster_name=cluster_name, site_id=site_id)


class PackagePrerequisites(aetest.Testcase):
    handle = None
    # the path to the location of the install file e.g. 'Development', 'Feature/ASA_INTEG'
    branch_path = None
    version = None
    build = None
    site = None
    fxos_file = None
    version_build = None
    server_ip = None

    @aetest.test
    def init_params(self):
        pass

    @aetest.test
    def delete_old_ftd_images(self, steps):
        try:
            with steps.start("Delete old FTD images"):
                self.handle.execute('top')
                self.handle.execute('scope ssa')
                result = self.handle.execute('show app')
                ftd_images = result.splitlines()
                if len(ftd_images) > 1:
                    for image in ftd_images:
                        items = image.split()
                        if items[0] == 'ftd' and items[1] != self.version + '.' + self.build:
                            delete_command = "delete app ftd {}".format(items[1])
                            try:
                                self.handle.execute(delete_command)
                                output = self.handle.execute('commit-buffer')
                                if 'Error' in output:
                                    raise Exception("Found error in output - moving to next app")
                            except Exception:
                                self.handle.execute('discard-buffer')
                                pass
                self.handle.execute('show app')
        except Exception as e:
            logger.info("Unable to delete old FTD images e= {} {} {}".format(e, traceback.format_exc(),
                                                                             sys.exc_info()))
            pass

    @aetest.test
    def delete_old_fxos_images(self, steps):
        try:
            with steps.start("Delete old FXOS images"):
                self.handle.execute('scope firmware')
                result = self.handle.execute('show package')
                fxos_images = result.splitlines()
                if len(fxos_images) > 1:
                    for image in fxos_images:
                        items = image.split()
                        if 'fxos' in items[0] and items[0] != self.fxos_file:
                            delete_command = "delete package {}".format(items[0])
                            try:
                                self.handle.execute(delete_command)
                            except Exception:
                                pass
                time.sleep(5)
                self.handle.execute('show package')
        except Exception as e:
            logger.info("Unable to delete old FXOS images e= {} {} {}".format(e, traceback.format_exc(),
                                                                              sys.exc_info()))
            pass

    @aetest.test
    def download_fxos(self, steps):
        try:
            if self.fxos_file is not None:
                with steps.start("Prepare fxos file on PXE"):
                    self.server_ip = get_fxos_file(self.site, self.fxos_file)
        except Exception as e:
            self.failed(
                "Unable to download FXOS file on PXE server e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])
        try:
            if self.fxos_file is not None:
                with steps.start("Download FXOS"):
                    fxos_url = 'scp://pxe@{}:{}/{}'.format(self.server_ip, pxe_dir['fxos_dir'], self.fxos_file)
                    self.handle.download_fxos(fxos_url=fxos_url, file_server_password=pxe_password)
        except Exception as e:
            self.failed("Unable to download FXOS file on chassis e= {} {} {}".format(e, traceback.format_exc(),
                                                                                     sys.exc_info()),
                        goto=["common_cleanup"])

    @aetest.test
    def prepare_files(self, steps):
        try:
            with steps.start("Prepare files on PXE"):
                self.server_ip, tftp_prefix, self.scp_prefix, self.files = prepare_installation_files(self.site, 'Ssp',
                                                                                                      self.branch_path,
                                                                                                      self.version_build,
                                                                                                      fxos_file=self.fxos_file)
        except Exception as e:
            self.failed(
                "Unable to download files on PXE server e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])

    @aetest.test
    def download_csp(self, steps):
        try:
            with steps.start("Download CSP"):
                csp_file = [file for file in self.files if file.endswith('.csp')][0]
                scp_csp_link = "scp://pxe@{}:/{}/{}".format(self.server_ip, self.scp_prefix, csp_file)
                self.handle.download_csp(csp_url=scp_csp_link, file_server_password=pxe_password)
        except Exception as e:
            self.failed("Unable to download CSP file on chassis e= {} {} {}".format(e, traceback.format_exc(),
                                                                                    sys.exc_info()),
                        goto=["common_cleanup"])


class ConfigurationClean(aetest.Testcase):
    handle = None
    configuration = None
    slots = [1, 2, 3]

    @aetest.test
    def init_params(self):
        pass

    @aetest.test
    def clean_logical_device(self):
        self.handle.execute('discard-buffer')
        try:
            logical_device_handler = LogicalDeviceUtils(self.handle)
            logical_device_handler.delete_all_ld()
        except Exception as e:
            self.failed(
                "Unable to clean App Instances e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])

    @aetest.test
    def clean_app_instance(self):
        try:
            for slot in self.slots:
                app_handler = AppInstanceUtils(self.handle, slot)
                apps = app_handler.get_app_instances_in_slot()
                for app in apps:
                    app_instance = AppInstance(handle=self.handle, app_name=app['App Name'], slot=slot,
                                               identifier=app['Identifier'])
                    app_instance.delete()
        except Exception as e:
            self.failed(
                "Unable to clean App Instances e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])

    @aetest.test
    def resource_profile(self):
        try:
            resource_handler = ResourceProfileUtils(self.handle)
            resource_handler.delete_all()
        except Exception as e:
            self.failed(
                "Unable to clean App Instances e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])


class InterfaceCleanUtils(aetest.Testcase):
    handle = None

    @aetest.test
    def init_params(self):
        pass

    @aetest.test
    def clean_portchannel(self):
        try:
            interface_handler = InterfaceHandler(self.handle)
            interface_handler.delete_all_port_channel()
        except Exception as e:
            self.failed(
                "Unable to delete all portchannel e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])

    @aetest.test
    def clean_interfaces(self):
        try:
            interface_handler = InterfaceHandler(self.handle)
            interface_handler.reset_all_physical_interfaces()
        except Exception as e:
            self.failed(
                "Unable to clean physical interface e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])


class ConfigureInterfacesUtils(aetest.Testcase):
    handle = None
    interfaces = None

    @aetest.test
    def init_params(self):
        pass

    def configure_sub_interface(self, hardware, subinterface_input):
        try:
            for interface in subinterface_input:
                subinterface_obj = SubInterface(handle=self.handle, hardware=hardware,
                                                sub_interface_id=interface.get("id"))
                try:
                    port_type = interface.get("subtype")
                except:
                    port_type = 'data'
                subinterface_obj.configure(vlan_id=interface.get("vlan_id"), port_type=port_type)
        except Exception as e:
            raise e

    def configure_port_channel_sub_interface(self, hardware, subinterface_input):
        try:
            for interface in subinterface_input:
                subinterface_obj = PortChannelSubInterface(handle=self.handle, hardware=hardware,
                                                           sub_interface_id=interface.get("id"))
                try:
                    port_type = interface.get("subtype")
                except:
                    port_type = 'data'
                subinterface_obj.configure(vlan_id=interface.get("vlan_id"), port_type=port_type)
        except Exception as e:
            raise e

    @aetest.test
    def configure_interfaces(self, steps):
        portchannel = []
        interface_handler = InterfaceHandler(self.handle)
        with steps.start('Create physical interfaces and subinterfaces') as step:
            try:
                for interface in self.interfaces:
                    if getattr(self.interfaces[interface], "hardware", None):
                        with step.start('Create physical interface {}'.format(self.interfaces[interface].hardware)):
                            intf_object = PhysicalInterface(self.handle, self.interfaces[interface].hardware)
                            intf_object.configure(port_type=self.interfaces[interface].subtype, enabled=True)

                            if getattr(self.interfaces[interface], "subinterfaces", None):
                                self.configure_sub_interface(self.interfaces[interface].hardware,
                                                             self.interfaces[interface].subinterfaces)
                    else:
                        portchannel.append(interface)
            except Exception as e:
                self.failed(
                    "Unable to determine interface type e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                    goto=["common_cleanup"])
        with steps.start('Create portchannel interfaces and portchannel subinterfaces') as step:
            try:
                for interface in portchannel:
                    name = "Port-channel{}".format(self.interfaces[interface].id)
                    with step.start('Create portchannel interface {}'.format(name)):
                        intf_object = PortChannelInterface(self.handle, name)
                        member_interfaces = None
                        if hasattr(self.interfaces[interface], 'member_ports'):
                            member_interfaces = []
                            for member in self.interfaces[interface].member_ports:
                                member_interfaces.append(
                                    interface_handler.instantiate_interface_based_on_name(name=member))
                        intf_object.configure(port_type=self.interfaces[interface].subtype,
                                              member_ports=member_interfaces, enabled=True)
                        if getattr(self.interfaces[interface], "subinterfaces", None):
                            self.configure_port_channel_sub_interface(name, self.interfaces[interface].subinterfaces)
            except Exception as e:
                self.failed(
                    "Unable to determine interface type e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                    goto=["common_cleanup"])


class ConfigureMultiInstanceUtils(aetest.Testcase):
    handle = None
    configuration = None
    apps_to_create = []
    app_list = []

    logical_devices = {}

    @aetest.test
    def init_params(self):
        pass

    @aetest.test
    def build_resource_profile(self):
        profiles = self.configuration.get('resource_profiles', [])
        for resource_profile in profiles:
            try:
                rp = ResourceProfile(handle=self.handle, name=profiles[resource_profile].get("name"))
                rp.configure(cpu=profiles[resource_profile].get("cpu_core_count"))
            except Exception as e:
                self.failed(
                    "Unable to create Resource Profile e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                    goto=["common_cleanup"])

    def add_unique_key_in_logical_device(self, key, logical_device):
        # only one of the apps in a cluster can contain some keys
        if key in logical_device:
            if key in self.logical_devices[logical_device['name']]:
                raise Exception("This logical device {} has already a {}".format(logical_device['name'], key))
            self.logical_devices[logical_device['name']][key] = logical_device[key]

    def add_key_if_values_match(self, key, logical_device):
        # some keys in a cluster can be in more than one app, but they need to have the same value
        if key in logical_device:
            if key in self.logical_devices[logical_device['name']] and self.logical_devices[logical_device['name']][
                key] != logical_device[key]:
                raise Exception(
                    "This logical device {} has already a {} with another value".format(logical_device['name'], key))
            self.logical_devices[logical_device['name']][key] = logical_device[key]

    def add_ip_for_slot(self, slot, logical_device):
        self.logical_devices[logical_device['name']]['ip_config'][slot] = {}
        if 'ipv4' in logical_device:
            self.logical_devices[logical_device['name']]['ip_config'][slot]['ipv4'] = logical_device['ipv4']
        if 'ipv6' in logical_device:
            self.logical_devices[logical_device['name']]['ip_config'][slot]['ipv6'] = logical_device['ipv6']

    def prepare_logical_device_data(self, logical_device, app_instance, slot):
        # creates a dictionary for logical devices having the logical device name as key
        if logical_device['name'] not in self.logical_devices:
            self.logical_devices[logical_device['name']] = logical_device
            self.logical_devices[logical_device['name']]['app'] = app_instance
            self.logical_devices[logical_device['name']]['ip_config'] = {}
            self.add_ip_for_slot(slot, logical_device)
        else:
            if app_instance.app_name != self.logical_devices[logical_device['name']]['app'].app_name:
                raise Exception("This logical device {} has associated this app name {} and you want to set {}".format(
                    logical_device['name'], self.logical_devices[logical_device['name']]['app'].app_name,
                    app_instance.app_name))
            self.add_key_if_values_match('logical_slot', logical_device)
            self.add_key_if_values_match('device_mode', logical_device)
            self.add_unique_key_in_logical_device('bootstrap_cluster', logical_device)
            self.add_unique_key_in_logical_device('external_port_links', logical_device)
            self.add_unique_key_in_logical_device('bootstrap_keys', logical_device)
            self.add_unique_key_in_logical_device('bootstrap_keys_secret', logical_device)
            if slot in self.logical_devices[logical_device['name']]['ip_config']:
                raise Exception("We already have an app on slot {}".format(slot))
            self.add_ip_for_slot(slot, logical_device)

    @aetest.test
    def build_app_instances(self, steps):
        instances = self.configuration['applications']
        for i in instances:
            if (len(self.apps_to_create) > 0 and instances[i].get(
                    "application_identifier") in self.apps_to_create) or len(self.apps_to_create) == 0:
                with steps.start('Create App Instance {}'.format(instances[i].get("application_identifier"))):
                    try:
                        app_instance = AppInstance(handle=self.handle, app_name=instances[i].get("application_name"),
                                                   slot=instances[i].get("slot"),
                                                   identifier=instances[i].get("application_identifier"))
                        hw_crypto_state = None
                        if 'hw-crypto' in instances[i]:
                            if 'admin-state' in instances[i]['hw-crypto']:
                                    hw_crypto_state = instances[i]['hw-crypto'].get("admin-state")
                            else:

                                self.failed("hw-crypto admin-state was not configured correct in testbed",goto=["common_cleanup"])
                        app_instance.create(deploy_type=instances[i].get("deploy_type"),
                                            version=instances[i].get("startup_version"),
                                            resource_profile=instances[i].get("resource_profile"),hw_crypto_state = hw_crypto_state)
                        self.app_list.append(app_instance)
                        self.prepare_logical_device_data(instances[i]['logical_device'], app_instance,
                                                         instances[i].get("slot"))
                    except Exception as e:
                        self.failed("Unable to create App Instance with name={} identifier={} e= {} {} {}".format(
                            instances[i].get("application_name"), instances[i].get("application_identifier"), e,
                            traceback.format_exc(),
                            sys.exc_info()),
                            goto=["common_cleanup"])

    @aetest.test
    def build_logical_devices(self, steps):
        interface_handler = InterfaceHandler(self.handle)
        for i in self.logical_devices:
            logical_device_info = self.logical_devices[i]
            with steps.start('Create Logical Device with name {}'.format(logical_device_info.get("name"))):
                try:
                    cluster_bootstrap = None
                    if 'bootstrap_cluster' in logical_device_info:
                        logical_cluster_info = logical_device_info.get("bootstrap_cluster")
                        cluster_bootstrap = prepare_cluster_bootstrap(self.handle, logical_cluster_info)
                    if len(logical_device_info['ip_config'].keys()) > 1:
                        mgmt_bootstrap = prepare_intra_cluster_management_bootstrap(self.handle, logical_device_info)
                    else:
                        mgmt_bootstrap = prepare_management_bootstrap(self.handle, logical_device_info)
                    interface_objects = []
                    if 'external_port_links' in logical_device_info:
                        for interface in logical_device_info.get("external_port_links"):
                            interface_obj = interface_handler.instantiate_interface_based_on_name(name=interface)
                            interface_objects.append(interface_obj)
                    if 'logical_slot' in logical_device_info:
                        slot = '\"' + logical_device_info.get("logical_slot") + '\"'
                    else:
                        slot = logical_device_info.get("app").slot
                    logical_device = LogicalDevice(handle=self.handle, name=logical_device_info.get("name"),
                                                   app=logical_device_info.get("app"),
                                                   slot=slot,
                                                   type=logical_device_info.get("device_mode"))
                    logical_device.create(interfaces=interface_objects, mgmt_bootstrap=mgmt_bootstrap,
                                          cluster_bootstrap=cluster_bootstrap)
                except Exception as e:
                    self.failed(
                        "Unable to create logical device e= {} {} {}".format(e, traceback.format_exc(),
                                                                             sys.exc_info()),
                        goto=["common_cleanup"])

    def handle_cluster_exception(self, app, problem_apps):
        try:
            logger.info(
                "Handling exception for cluster - the product requires to provide information for all 3 blades, but cluster can be formed with only 2 blades.")
            logger.info("Check if status for the app is 'Not Available'")
            app_details = app.get_app_instance_detail()
            if app_details['Oper State'] != "Not Available":
                logger.error("We are handling cluster exception only if the blade is missing.")
                return False
            logger.info("Status is 'Not Available'. Moving to next check.")
            logger.info("Checking if app is part of cluster.")
            device_mode = None
            instances = self.configuration['applications']
            for i in instances:
                if instances[i].get("application_identifier") == app.identifier and instances[i].get("slot") == app.slot:
                    device_mode = instances[i]["logical_device"]["device_mode"]
                    break
            if not device_mode or device_mode != 'clustered':
                logger.error("This device mode is {}. We are handling exception only for clustered.".format(device_mode))
                return False
            logger.info("App is part of a cluster. Moving to next check.")
            logger.info("Checking if the other apps on same cluster are online.")
            count = 0
            for problem_app in problem_apps:
                if problem_app.identifier == app.identifier:
                    count += 1
            if count > 1:
                logger.error("There are {} with same name {} in a bad state. Cannot form cluster.".format(count, app.identifier))
                return False
            logger.info("The other apps are online.")
        except Exception as e:
            logger.error("Failed while checking if there is an exception for the app. e={}".format(e))
            return False
        return True

    @aetest.test
    def wait_until_online(self):
        failed_apps = []
        to_check_apps = self.app_list
        step = 0
        while step < 180 and len(to_check_apps) > 0:
            logger.info('Checking if enable - {} try'.format(step))
            time.sleep(30)
            not_completed_apps = []
            for app in to_check_apps:
                try:
                    if not app.check_status():
                        not_completed_apps.append(app)
                except:
                    failed_apps.append(app)
            to_check_apps = not_completed_apps
            logger.info('Number of failed apps: {}'.format(len(failed_apps)))
            logger.info('Waiting for {} apps'.format(len(to_check_apps)))
            step += 1
        if len(failed_apps) > 0 or len(to_check_apps) > 0:
            catastrophic_failure = False
            if len(failed_apps) > 0:
                logger.error("We have failed apps. Checking if they are known exceptions:")
                summary = ''
                for app in failed_apps:
                    logger.error("\t Failed app {} on slot {}".format(app.identifier, app.slot))
                    problem_apps = []
                    problem_apps.extend(failed_apps)
                    problem_apps.extend(to_check_apps)
                    if not self.handle_cluster_exception(app, problem_apps):
                        catastrophic_failure = True
                        summary = "{}\n\t app {} on slot {}".format(summary, app.identifier, app.slot)
                if summary != '':
                    logger.error("We have failed apps: {}".format(summary))
            if len(to_check_apps) > 0:
                logger.error("We have apps which aren't Online yet: ")
                catastrophic_failure = True
                for app in to_check_apps:
                    logger.error("\t app {} on slot {}".format(app.identifier, app.slot))
            if catastrophic_failure:
                self.failed("Unable to start all logical devices", goto=["common_cleanup"])
            else:
                self.passx("Some apps were not started, but these are known exceptions")
