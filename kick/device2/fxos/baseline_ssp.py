# python kick/device2/fxos/tests/baseline_ssp.py --testbed kick/device2/fxos/testbed_samples/
# ssp3ru_native.yaml --build 1119 --version 6.5.0 --branch Development --fxos_file fxos-k9.2.7.1.4.SPA

import logging
import sys
import traceback

from ats import aetest
from ats import topology

from kick.device2.fxos.app import AppInstance
from kick.device2.fxos.util_app import AppArgumentsParser
from kick.device2.ssp.actions import Ssp

KICK_EXTERNAL = False

try:
    from kick.file_servers.file_servers import *
except ImportError:
    KICK_EXTERNAL = True
    pass

from kick.device2.fxos.configuration_utils import ConfigurationClean, PackagePrerequisites, \
    ConfigureInterfacesUtils, ConfigureMultiInstanceUtils, InterfaceCleanUtils
from kick.device2.fxos.utils import create_dict

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

logging.getLogger('unicon').setLevel(logging.DEBUG)


def get_chassis_mio_console():
    global mio, MIO_CONSOLE
    if not MIO_CONSOLE:
        MIO_CONSOLE = mio.ssh_console(
            ip=SSH_CONSOLE_IP, port=SSH_CONSOLE_PORT, username=SSH_CONSOLE_USERNAME, password=SSH_CONSOLE_PASSWORD,
            timeout=120)
        # disable logout from the chassis
        MIO_CONSOLE.set_default_auth_timeouts()
    return MIO_CONSOLE


def get_args():
    return args


def get_build_no():
    return BUILD_NO


class CommonSetup(aetest.CommonSetup):
    groups = ['common', 'CommonSetup']

    def get_image_path(self, branch, version, build):
        BRANCHES = {
            #    Branch:   Top folder where builds for this branch are stored
            'RELEASE': 'Release',
            'TESTING': 'Testing',
            'DEVELOPMENT': 'Development',
            'MAIN': 'Development',
            'INTEG': 'Development',
            'INTEGRATION': 'Development',
            'DEVELOPMENT_SIT': 'Development',
            'DEVELOPMENT_ST': 'Development',
            'IMS_6_5_0': 'Development',
            'IMS_6_6_0': 'Development',
            'IMS_6_7_0': 'Development',
            'IMS_6_8_0': 'Development',
        }

        final_branch = branch
        final_build = build
        final_version = version
        feature_branch = False

        if final_branch.upper() not in BRANCHES.keys():
            log.debug("Branch '{}' is a Feature branch.".format(final_branch))
            feature_branch = True
            branch_value = 'Feature/{}'.format(branch)
        else:
            branch_value = BRANCHES[branch.upper()]

        version_build_text = "{}-{}{}".format(final_version, final_build, "." + final_branch if feature_branch else "")
        log.info("Using {} branch {}. Build folder: {}/{}.".format("feature " if feature_branch else "", final_branch,
                                                                   branch_value, version_build_text))

        return branch_value, version_build_text

    @aetest.subsection
    def main(self):
        import argparse

        parser = argparse.ArgumentParser(description="Baseline for QP devices.")

        parser.add_argument('--testbed', dest='testbed', required=True, help='path to the testbed file')
        parser.add_argument('--build', dest='build', required=True,
                            help='the build number; e.g. 1234, 10200')
        parser.add_argument('--version', dest='version', required=True, help='the version number; usage e.g. 6.2.3')
        parser.add_argument('--branch', dest='branch', required=True,
                            help='the branch name; only feature branches are case sensitive (e.g. GL_MCTX_PHASE0, SNORT3); the other branches are case insensitive')
        parser.add_argument('--report_build', dest='report_build',
                            help='the build number for the report; if missing it will take the value from --build; usage e.g. 1234, 10200')
        parser.add_argument('--report_version', dest='report_version',
                            help='the version number for the report; if missing it will take the value from --version; usage e.g. 6.2.3')
        parser.add_argument('--report_branch', dest='report_branch',
                            help='the branch name for the report; if missing it will take the value from --branch; feature branches are case sensitive; DEVELOPMENT, MAIN are not case sensitive; the value you provide here will be seen on the Kick UI in the reports section')
        parser.add_argument('--report_type', dest='report_type',
                            help='if specified it will update the result of the test in Kick reporting; e.g. BQT/BAT_2_0 (if you need a new report type (that doesn\'t yet exist) you need to contact Kick team)')
        parser.add_argument('--report_subtype', dest='report_subtype',
                            help='if specified it will update the result of the test in Kick reporting; e.g. BQT or BAT')
        parser.add_argument('--report_env_type', dest='report_env_type',
                            help='if specified it will update the result of the test in Kick reporting; e.g. FMC_QW_1150')
        parser.add_argument('--report_group_by', dest='report_group_by',
                            help='this is needed when you want to report multiple execution plans in the same cell')
        parser.add_argument('--fxos_file', dest='fxos_file', required=False, help='the fxos image to be used')
        parser.add_argument('--apps', dest='apps', required=False,
                            help='if specified it will create only the apps in the list; usage e.g. 1-3,6-9 or ftdapp7,ftdapp25')
        parser.add_argument('--cpu_core_count', dest='cpu_core_count', required=False,
                            help='if specified it will override the resource profile we have in testbed with new resource profiles;'
                                 'usage e.g. --cpu_core_count 6,8,12|6|6,10 or --cpu_core_count 6 or --cpu_core_count 6|12|6 '
                                 'each slot is separated by pipe |'
                                 'if we specify only one number it will be used for all the apps in the slot'
                                 'if we specify multiple numbers they will be used for the apps in order')

        global args
        args, unknown = parser.parse_known_args()
        if len(unknown) > 0:
            log.warning('Unknown arguments: {}'.format(unknown))

        global FXOS_FILE
        FXOS_FILE = None
        if args.fxos_file is not None:
            FXOS_FILE = args.fxos_file
        testbed_yaml = args.testbed
        tb = topology.loader.load(testbed_yaml)
        global SITE
        SITE = tb.custom.site
        global SSP_DEV
        SSP_DEV = tb.custom.device_name

        global BRANCH_PATH, VERSION_BUILD, VERSION, BUILD
        VERSION = args.version
        BUILD = args.build

        (BRANCH_PATH, VERSION_BUILD) = self.get_image_path(branch=args.branch, version=args.version, build=args.build)
        log.info("Using branch_path='{}' and version_build='{}'".format(BRANCH_PATH, VERSION_BUILD))

        global FTD_VERSION, BUILD_NO
        if re.match('^Feature\/', BRANCH_PATH):
            small_version_build = re.match('(.*\-.*)\.', VERSION_BUILD)
            FTD_VERSION = small_version_build.groups()[0]
            FTD_VERSION = re.sub('-', '.', FTD_VERSION)
            small_build = re.match('.*\-(.*)\.', VERSION_BUILD)
            BUILD_NO = small_build.groups()[0]
        else:
            FTD_VERSION = VERSION_BUILD
            FTD_VERSION = re.sub('-', '.', FTD_VERSION)
            BUILD_NO = VERSION_BUILD.split("-")[1]

        log.info('FTD_VERSION={}'.format(FTD_VERSION))
        log.info('BUILD_NO={}'.format(BUILD_NO))

        global HOSTNAME, SSH_CONSOLE_IP, SSH_CONSOLE_PORT, SSH_CONSOLE_USERNAME, SSH_CONSOLE_PASSWORD, SSH_CHASSIS_IP, \
            SSH_CHASSIS_PORT, SSH_CHASSIS_PORT, SSH_CHASSIS_USERNAME, SSH_CHASSIS_PASSWORD, NTP_SERVER, DNS_SERVERS, \
            SEARCH_DOMAINS, POWER_BAR_SERVER, POWER_BAR_PORT, CHASSIS_MGMT_IPV4_IP, CHASSIS_MGMT_IPV4_NETMASK, \
            CHASSIS_MGMT_IPV4_GATEWAY, CHASSIS_SOFTWARE, CHASSIS_INTERFACES, APPS, MIO_CONSOLE
        MIO_CONSOLE = None
        HOSTNAME = tb.devices[SSP_DEV].custom.hostname

        # although console is more intuitive, alt is still commonly used for console connection definition
        if hasattr(tb.devices[SSP_DEV].connections, 'alt'):
            SSH_CONSOLE_IP = str(tb.devices[SSP_DEV].connections.alt.ip)
            SSH_CONSOLE_PORT = str(tb.devices[SSP_DEV].connections.alt.port)
            if hasattr(tb.devices[SSP_DEV].connections.alt, 'user'):
                SSH_CONSOLE_USERNAME = str(tb.devices[SSP_DEV].connections.alt.user)
            elif hasattr(tb.devices[SSP_DEV].connections.alt, 'username'):
                SSH_CONSOLE_USERNAME = str(tb.devices[SSP_DEV].connections.alt.username)
            SSH_CONSOLE_PASSWORD = str(tb.devices[SSP_DEV].connections.alt.password)
        elif hasattr(tb.devices[SSP_DEV].connections, 'console'):
            SSH_CONSOLE_IP = str(tb.devices[SSP_DEV].connections.console.ip)
            SSH_CONSOLE_PORT = str(tb.devices[SSP_DEV].connections.console.port)
            if hasattr(tb.devices[SSP_DEV].connections.console, 'user'):
                SSH_CONSOLE_USERNAME = str(tb.devices[SSP_DEV].connections.console.user)
            elif hasattr(tb.devices[SSP_DEV].connections.console, 'username'):
                SSH_CONSOLE_USERNAME = str(tb.devices[SSP_DEV].connections.console.username)
            SSH_CONSOLE_PASSWORD = str(tb.devices[SSP_DEV].connections.console.password)

        # CHASSIS MGMT DETAILS
        SSH_CHASSIS_IP = str(tb.devices[SSP_DEV].connections.management.ip)
        SSH_CHASSIS_PORT = str(tb.devices[SSP_DEV].connections.management.port)
        SSH_CHASSIS_USERNAME = str(tb.devices[SSP_DEV].connections.management.user)
        SSH_CHASSIS_PASSWORD = str(tb.devices[SSP_DEV].connections.management.password)

        try:
            NTP_SERVER = tb.devices[SSP_DEV].custom.ntp_server
        except:
            NTP_SERVER = None
        try:
            DNS_SERVERS = tb.devices[SSP_DEV].custom.chassis_network.get("dns_servers")
        except:
            DNS_SERVERS = None
        try:
            SEARCH_DOMAINS = tb.devices[SSP_DEV].custom.chassis_network.get("search_domains")
        except:
            SEARCH_DOMAINS = None

        POWER_BAR_SERVER = tb.devices[SSP_DEV].custom.chassis_power.get("power_bar_server")
        POWER_BAR_PORT = tb.devices[SSP_DEV].custom.chassis_power.get("power_bar_port")

        CHASSIS_MGMT_IPV4_IP = str(tb.devices[SSP_DEV].interfaces.chassis_mgmt.ipv4.ip)
        CHASSIS_MGMT_IPV4_NETMASK = str(tb.devices[SSP_DEV].interfaces.chassis_mgmt.ipv4.netmask)
        CHASSIS_MGMT_IPV4_GATEWAY = str(tb.devices[SSP_DEV].interfaces.chassis_mgmt.ipv4_gateway)

        CHASSIS_SOFTWARE = tb.devices[SSP_DEV].custom.chassis_software
        # need to insert in TB the startup_version from CLI
        instances = CHASSIS_SOFTWARE['applications']
        for i in instances:
            CHASSIS_SOFTWARE['applications'][i]["startup_version"] = FTD_VERSION
        CHASSIS_INTERFACES = tb.devices[SSP_DEV].interfaces
        del CHASSIS_INTERFACES["chassis_mgmt"]

        APPS = []
        app_parser = AppArgumentsParser()

        if args.apps is not None:
            APPS = app_parser.get_apps_list(args.apps)
        else:
            for app in CHASSIS_SOFTWARE['applications']:
                APPS.append(CHASSIS_SOFTWARE['applications'][app].get("application_identifier"))
        log.info("Will create only these apps: {}".format(APPS))

        log.info("Modifying the chassis software to take default values")
        CHASSIS_SOFTWARE = app_parser.build_app_template(CHASSIS_SOFTWARE, APPS)

        if args.cpu_core_count is not None:
            log.info("--cpu_core_count is specified so we need to override the resource profile")
            resource_profiles = {}
            count_per_slot = {}
            i = 1
            for slot_cpu_info in args.cpu_core_count.split("|"):
                app_cpu_info = slot_cpu_info.split(",")
                for app_cpu in app_cpu_info:
                    if app_cpu != "0" and app_cpu != "":
                        resource_profiles[app_cpu] = {}
                        resource_profiles[app_cpu]['name'] = 'stauto_{}'.format(app_cpu)
                        resource_profiles[app_cpu]['cpu_core_count'] = app_cpu
                    else:
                        log.info("Cannot use {} for resource profile! Skipping...".format(app_cpu))
                count_per_slot[i] = app_cpu_info
                i = i + 1
            CHASSIS_SOFTWARE['resource_profiles'] = resource_profiles
            for app_id in APPS:
                for i in CHASSIS_SOFTWARE['applications']:
                    if CHASSIS_SOFTWARE['applications'][i]['application_identifier'] == app_id:
                        slot = CHASSIS_SOFTWARE['applications'][i]['slot']
                        if len(count_per_slot[slot]) > 1:
                            CHASSIS_SOFTWARE['applications'][i]['resource_profile'] = 'stauto_{}'.format(
                                count_per_slot[slot].pop(0))
                        else:
                            CHASSIS_SOFTWARE['applications'][i]['resource_profile'] = 'stauto_{}'.format(
                                count_per_slot[slot][0])
                        break

    @aetest.subsection
    def create_ssp_device(self):
        global mio
        mio = Ssp(hostname=HOSTNAME,
                  login_username=SSH_CHASSIS_USERNAME,
                  login_password=SSH_CHASSIS_PASSWORD,
                  sudo_password=SSH_CHASSIS_PASSWORD,
                  power_bar_server=POWER_BAR_SERVER,
                  power_bar_port=POWER_BAR_PORT,
                  deploy_type='container',
                  app_identifier='dummy_name')

    @aetest.subsection
    def connect_to_chassis_mio_ssh(self):
        global dev
        dev = mio.ssh_vty(ip=SSH_CHASSIS_IP, port=SSH_CHASSIS_PORT, username=SSH_CHASSIS_USERNAME,
                          password=SSH_CHASSIS_PASSWORD, timeout=300)
        dev.reconnect_feature = {'enabled': True, 'max_retries': 3}


class CleanInstances(ConfigurationClean):
    groups = ['CleanMultiInstance']

    @aetest.test
    def init_params(self):
        self.handle = dev
        self.configuration = CHASSIS_SOFTWARE


class CleanInterfaces(InterfaceCleanUtils):
    groups = ['CleanInterfaces', 'chassis']

    @aetest.test
    def init_params(self):
        self.handle = dev


class PreparePrerequisites(PackagePrerequisites):
    groups = ['PreparePrerequisites']

    @aetest.test
    def init_params(self):
        self.handle = dev
        self.branch_path = BRANCH_PATH
        self.version = VERSION
        self.build = BUILD
        self.site = SITE
        self.fxos_file = FXOS_FILE
        self.version_build = VERSION_BUILD


class BaselineFXOS(aetest.Testcase):
    groups = ['BaselineFXOS', 'chassis']
    chassis_line = None

    @aetest.test
    def init_params(self):
        self.fxos_file = FXOS_FILE

    @aetest.test
    def upgrade_fxos(self):
        self.chassis_line = get_chassis_mio_console()
        if self.fxos_file:
            try:
                self.chassis_line.upgrade_bundle_package(self.fxos_file)
            except Exception as e:
                self.failed(
                    "Unable to install FXOS e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                    goto=["common_cleanup"])


class ConfigureChassis(aetest.Testcase):
    groups = ['ConfigureChassis', 'chassis']
    chassis_line = None

    @aetest.test
    def configure_chassis(self, steps):
        self.chassis_line = get_chassis_mio_console()
        try:
            with steps.start("Change Chassis IP"):
                self.chassis_line.execute('top')
                self.chassis_line.execute('scope fabric a')
                self.chassis_line.execute('show detail')
                self.chassis_line.execute(
                    'set out-of-band ip {} netmask  {} gw {}'.format(CHASSIS_MGMT_IPV4_IP, CHASSIS_MGMT_IPV4_NETMASK,
                                                                     CHASSIS_MGMT_IPV4_GATEWAY))
                self.chassis_line.execute('commit-buffer')
                output = self.chassis_line.execute('show detail')
                if "IP Addr: ".format(CHASSIS_MGMT_IPV4_IP) not in output:
                    raise Exception("IPv4 was not set correctly")
                self.chassis_line.execute('up')
            if DNS_SERVERS is not None:
                with steps.start("Change DNS server"):
                    self.chassis_line.execute('scope system')
                    self.chassis_line.execute('scope services')
                    self.chassis_line.execute('create dns {}'.format(DNS_SERVERS))
                    self.chassis_line.execute('commit-buffer')
                    output = self.chassis_line.execute('show dns')
                    if "{}".format(DNS_SERVERS) not in output:
                        raise Exception("DNS Server was not set correctly")
            if SEARCH_DOMAINS is not None:
                with steps.start("Change domain name"):
                    self.chassis_line.execute('set domain-name {}'.format(SEARCH_DOMAINS))
                    self.chassis_line.execute('commit-buffer')
                    output = self.chassis_line.execute('show domain-name')
                    if "{}".format(SEARCH_DOMAINS) not in output:
                        raise Exception("Search Domain was not set correctly")
        except Exception as e:
            self.failed(
                "Unable to install FXOS e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])

    @aetest.test
    def configure_ntp_server(self, steps):
        if NTP_SERVER:
            with steps.start("Change NTP server - if necessary"):
                self.chassis_line.execute('top')
                self.chassis_line.execute('scope system')
                self.chassis_line.execute('scope services')
                output = create_dict(self.chassis_line.execute('show ntp-server detail'))
                if not hasattr(output, 'Name') or output['Name'] != NTP_SERVER:
                    log.info("Changing NTP server")
                    self.chassis_line.execute('create ntp-server {}'.format(NTP_SERVER))
                    output = self.chassis_line.execute('commit-buffer')
                    if 'Error' in output:
                        raise Exception("Failed to change NTP server")
                    self.chassis_line.execute('up')
                    self.chassis_line.execute('show ntp-server detail')


class ConfigureInterfaces(ConfigureInterfacesUtils):
    groups = ['ConfigureInterfaces', 'chassis']

    @aetest.test
    def init_params(self):
        self.handle = dev
        self.interfaces = CHASSIS_INTERFACES


class ConfigureInstances(ConfigureMultiInstanceUtils):
    groups = ['ConfigureMultiInstance']

    @aetest.test
    def init_params(self):
        self.handle = dev
        self.configuration = CHASSIS_SOFTWARE
        self.apps_to_create = APPS


class InitializeApps(aetest.Testcase):
    groups = ['InitializeApps']

    def initialize_app(self, ssp_app):
        app_line = ssp_app.ssh_vty(ip=SSH_CHASSIS_IP,
                                   port=SSH_CHASSIS_PORT,
                                   username=SSH_CHASSIS_USERNAME,
                                   password=SSH_CHASSIS_PASSWORD,
                                   timeout=300)
        app_line.go_to("fireos_state")

    @aetest.test
    def init_apps(self):
        retry_app = []
        instances = CHASSIS_SOFTWARE['applications']
        for i in instances:
            if instances[i].get("application_identifier") in APPS:
                slot_id = instances[i].get("slot")
                deploy_type = instances[i].get("deploy_type")
                ssp_app = Ssp(hostname=HOSTNAME,
                              login_username=SSH_CHASSIS_USERNAME,
                              login_password=SSH_CHASSIS_PASSWORD,
                              sudo_password=SSH_CHASSIS_PASSWORD,
                              power_bar_server=POWER_BAR_SERVER,
                              power_bar_port=POWER_BAR_PORT,
                              slot_id=slot_id,
                              deploy_type=deploy_type,
                              app_identifier=instances[i].get("application_identifier"))
                try:
                    self.initialize_app(ssp_app)
                except:
                    log.error("Failed to initialize app. Checking if the blade is missing.")
                    app_instance = AppInstance(handle=dev, app_name=instances[i].get("application_name"),
                                               slot=instances[i].get("slot"),
                                               identifier=instances[i].get("application_identifier"))
                    app_details = app_instance.get_app_instance_detail()
                    if app_details['Oper State'] == "Not Available":
                        log.error("The blade is missing on slot {}. Skipping this app.".format(slot_id))
                    else:
                        retry_app.append(ssp_app)

        if len(retry_app) > 0:
            sleep_time = 60
            log.info("Sleeping {} seconds before retrying".format(sleep_time))
            time.sleep(sleep_time)
            for app in retry_app:
                try:
                    self.initialize_app(app)
                except Exception as e:
                    self.failed(
                        "Unable to install app for second retry e= {} {} {}".format(e, traceback.format_exc(),
                                                                                    sys.exc_info()),
                        goto=["common_cleanup"])


class CheckTCAMEntryLimit(aetest.Testcase):
    groups = ['CheckTCAMEntryLimit']

    @aetest.test
    def check_TCAM(self, steps):
        try:
            with steps.start("Get fabric-interconnect output"):
                dev.execute('top')
                dev.execute('scope chassis')
                dev.execute('scope fabric-interconnect')
                output = dev.execute('show detail')
                output = output.replace("\r\n", "")
            with steps.start("Check 'Ingress VLAN Group Entry Count'"):
                match = re.match(".+Ingress VLAN Group Entry Count \(Current\/Max\)\: (\d+)\/(\d+)", output)
                log.info("Ingress VLAN Group Entry Count Current = {}".format(match.group(1)))
                log.info("Ingress VLAN Group Entry Count Max = {}".format(match.group(2)))
                if int(match.group(1)) > int(match.group(2)):
                    raise Exception("Error: Ingress VLAN Group Entry Count - current greater than max")
            with steps.start("Check 'Switch Forwarding Path Entry Count'"):
                match = re.match(".+Switch Forwarding Path Entry Count \(Current\/Max\)\: (\d+)\/(\d+)", output)
                log.info("Switch Forwarding Path Entry Count Current = {}".format(match.group(1)))
                log.info("Switch Forwarding Path Entry Count Maxim = {}".format(match.group(2)))
                if int(match.group(1)) > int(match.group(2)):
                    raise Exception("Error: Switch Forwarding Path Entry Count - current greater than max")
        except Exception as e:
            self.failed(
                "Failed while getting TCAM info e= {} {} {}".format(e, traceback.format_exc(), sys.exc_info()),
                goto=["common_cleanup"])


class CommonCleanup(aetest.CommonCleanup):
    groups = ['common', 'CommonCleanup']

    @aetest.subsection
    def cleanup(self):
        dev.disconnect()


if __name__ == '__main__':
    aetest.main()
