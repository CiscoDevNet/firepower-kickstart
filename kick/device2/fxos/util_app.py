import logging
import re

log = logging.getLogger('AppArgumentsParser')
log.setLevel(logging.DEBUG)


class AppArgumentsParser:

    def get_apps_list(self, input: str):
        return_list = []
        apps_list = input.split(",")
        for app_range in apps_list:
            if "-" in app_range:
                if re.match("(\d+)\-(\d+)", app_range):
                    match = re.match("(\d+)\-(\d+)", app_range)
                    for i in range(int(match.groups()[0]), int(match.groups()[1]) + 1):
                        return_list.append("ftdapp{}".format(i))
                else:
                    log.error("The range {} is not valid. We support only digits.".format(app_range))
                    raise Exception("The range you specified is not valid")
            else:
                if re.match("^\d+$", app_range):
                    return_list.append("ftdapp{}".format(app_range))
                else:
                    return_list.append(app_range)

        return return_list

    def parse_cpu_core_count_argument(self, cpu_core_count: str):
        log.info("Parse cpu_core_count argument")
        resource_profiles = {}
        count_per_slot = {}
        i = 1
        for slot_cpu_info in cpu_core_count.split("|"):
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
        return {'count_per_slot': count_per_slot, 'resource_profiles': resource_profiles}

    def build_app_template(self, chassis_software, app_list):
        instances = chassis_software['applications']
        for i in instances:
            if (len(app_list) > 0 and instances[i].get("application_identifier") in app_list) or len(app_list) == 0:
                # need to initialize logical_device
                if not instances[i].get('logical_device'):
                    chassis_software['applications'][i]['logical_device'] = {}
                # if device_mode is not specified under logical_device it will take the value under chassis_software
                if not chassis_software['applications'][i]['logical_device'].get("device_mode"):
                    chassis_software['applications'][i]['logical_device']['device_mode'] = chassis_software.get(
                        'device_mode')
        if chassis_software.get('application_generic') is None:
            return chassis_software
        instance_template = chassis_software['application_generic']
        for i in instances:
            if (len(app_list) > 0 and instances[i].get("application_identifier") in app_list) or len(app_list) == 0:
                slot_id = None
                if not instances[i].get("slot"):
                    chassis_software['applications'][i]['slot'] = instance_template.get('slot')
                    slot_id = chassis_software['applications'][i]['slot']

                id = None
                if re.match("\D+(\d+)$", instances[i].get("application_identifier")):
                    match = re.match("\D+(\d+)$", instances[i].get("application_identifier"))
                    id = match.groups()[0]

                if not instances[i].get("application_name"):
                    chassis_software['applications'][i]['application_name'] = instance_template.get('application_name')
                if not instances[i].get("deploy_type"):
                    chassis_software['applications'][i]['deploy_type'] = instance_template.get('deploy_type')
                if not instances[i].get("resource_profile"):
                    chassis_software['applications'][i]['resource_profile'] = instance_template.get('resource_profile')

                # LOGICAL DEVICE
                if not instances[i].get('logical_device'):
                    chassis_software['applications'][i]['logical_device'] = {}
                if not instances[i]['logical_device'].get("name"):
                    chassis_software['applications'][i]['logical_device']['name'] = self._convert_name_with_id(
                        instance_template['logical_device'].get('name'), id, slot_id)

                # EXTERNAL PORT LINKS
                if not instances[i]['logical_device'].get('external_port_links'):
                    interface_list = []
                    for interface in instance_template['logical_device'].get("external_port_links"):
                        interface_list.append(self._convert_name_with_id(interface, id, slot_id))
                    chassis_software['applications'][i]['logical_device']['external_port_links'] = interface_list

                # BOOTSTRAP KEYS
                if not instances[i]['logical_device'].get('bootstrap_keys'):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys'] = {}
                if not instances[i]['logical_device']['bootstrap_keys'].get("firewall_mode"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['firewall_mode'] = \
                        instance_template['logical_device']['bootstrap_keys'].get('firewall_mode')
                if not instances[i]['logical_device']['bootstrap_keys'].get("fqdn"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['fqdn'] = \
                        self._convert_name_with_id(instance_template['logical_device']['bootstrap_keys'].get('fqdn'),
                                                   id, slot_id)
                if not instances[i]['logical_device']['bootstrap_keys'].get("dns_servers"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['dns_servers'] = \
                        instance_template['logical_device']['bootstrap_keys'].get('dns_servers')
                if not instances[i]['logical_device']['bootstrap_keys'].get("search_domains"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['search_domains'] = \
                        instance_template['logical_device']['bootstrap_keys'].get('search_domains')
                if not instances[i]['logical_device']['bootstrap_keys'].get("permit_expert_mode"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['permit_expert_mode'] = \
                        instance_template['logical_device']['bootstrap_keys'].get('permit_expert_mode')
                if not instances[i]['logical_device']['bootstrap_keys'].get("firepower_manager_ip"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['firepower_manager_ip'] = \
                        instance_template['logical_device']['bootstrap_keys'].get('firepower_manager_ip')
                if not instances[i]['logical_device']['bootstrap_keys'].get("management_type"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['management_type'] = \
                        instance_template['logical_device']['bootstrap_keys'].get('management_type')

                # BOOTSTRAP KEYS SECRET
                if not instances[i]['logical_device'].get('bootstrap_keys_secret'):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys_secret'] = {}
                if not instances[i]['logical_device']['bootstrap_keys_secret'].get("password"):
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys_secret']['password'] = \
                        instance_template['logical_device']['bootstrap_keys_secret'].get('password')

                # IPv4
                if not instances[i]['logical_device'].get('ipv4'):
                    chassis_software['applications'][i]['logical_device']['ipv4'] = {}
                if not instances[i]['logical_device']['ipv4'].get("ip"):
                    chassis_software['applications'][i]['logical_device']['ipv4']['ip'] = \
                        self._compute_ipv4_address(instance_template['logical_device']['ipv4'].get('ip'), id)
                if not instances[i]['logical_device']['ipv4'].get("netmask"):
                    chassis_software['applications'][i]['logical_device']['ipv4']['netmask'] = \
                        instance_template['logical_device']['ipv4'].get('netmask')
                if not instances[i]['logical_device']['ipv4'].get("gateway"):
                    chassis_software['applications'][i]['logical_device']['ipv4']['gateway'] = \
                        instance_template['logical_device']['ipv4'].get('gateway')

                # IPv6
                if not instances[i]['logical_device'].get('ipv6'):
                    chassis_software['applications'][i]['logical_device']['ipv6'] = {}
                if not instances[i]['logical_device']['ipv6'].get("ip"):
                    chassis_software['applications'][i]['logical_device']['ipv6']['ip'] = \
                        self._compute_ipv6_address(instance_template['logical_device']['ipv6'].get('ip'), id)
                if not instances[i]['logical_device']['ipv6'].get("prefix"):
                    chassis_software['applications'][i]['logical_device']['ipv6']['prefix'] = \
                        instance_template['logical_device']['ipv6'].get('prefix')
                if not instances[i]['logical_device']['ipv6'].get("gateway"):
                    chassis_software['applications'][i]['logical_device']['ipv6']['gateway'] = \
                        instance_template['logical_device']['ipv6'].get('gateway')

                # Update data if deploy_type == native
                if chassis_software['applications'][i]['deploy_type'] == 'native':
                    chassis_software['applications'][i]['logical_device']['bootstrap_keys']['permit_expert_mode'] = None
                    chassis_software['applications'][i]['resource_profile'] = None

        return chassis_software

    def _convert_name_with_id(self, name, id, slot_id):
        if "{id}" in name:
            name = name.replace("{id}", id)
        if "{slot_id}" in name:
            name = name.replace("{slot_id}", str(slot_id))
        return name

    def _compute_ipv4_address(self, start_address, id):
        match = re.match("(\d+\.\d+\.\d+\.)(\d+)", start_address)
        address = int(match.groups()[1]) + int(id) - 1
        return "{}{}".format(match.groups()[0], address)

    def _compute_ipv6_address(self, start_address, id):
        match = re.match("([\w+\:]+\:)(\d+)$", start_address)
        address = int(match.groups()[1]) + int(id) - 1
        return "{}{}".format(match.groups()[0], address)
