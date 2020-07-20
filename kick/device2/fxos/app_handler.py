import logging

from kick.device2.fxos.utils import create_dict, scope

logger = logging.getLogger(__name__)


class AppInstanceUtils:
    def __init__(self, handle, slot):
        """
        Constructor of App Instance
        :param handle: SSH connection handle
        :param slot: slot id; e.g. '1', '2'
        """
        self.handle = handle
        self.slot = str(slot)
        if self.slot == "":
            raise ValueError('Slot is mandatory and was sent as empty string')

    def show_app_instance(self):
        """
        Show Application Instance: show app-instance
        :return:
        """
        self.handle.execute("top")
        scope(self.handle, 'ssa/slot {}'.format(self.slot))
        out = self.handle.execute('show app-instance')
        if 'Error' in out:
            logger.info("Failed while trying to show app-instance with error: {}".format(out))
            raise Exception("Failed while trying to show app-instance")
        return out

    def show_app_instance_detail(self):
        """
        Show Application Instance details: show app-instance detail
        :param slot: slot id
        :return:
        """
        self.handle.execute("top")
        scope(self.handle, 'ssa/slot {}'.format(self.slot))
        out = self.handle.execute('show app-instance detail')
        if 'Error' in out and 'Error Msg' not in out:
            logger.info("Failed while trying to show app-instance detail with error: {}".format(out))
            raise Exception("Failed while trying to show app-instance detail")
        return out

    def get_app_instances_in_slot(self):
        """
        Get app-instance in slot as munch dictionary
        :return: Dictionary structure with apps
        """
        apps = []
        scope(self.handle, 'ssa/slot {}'.format(self.slot))
        for i in list(map(lambda x: create_dict(x), self.handle.execute('show app-instance detail').split('\r\n\r\n'))):
            if hasattr(i, 'App Name'):
                apps.append(i)
        return apps

    def get_online_app_instances_in_slot(self):
        """
        Get the list of online app-instance in slot
        :return: List of app identifiers
        """
        apps = []
        scope(self.handle, 'ssa/slot {}'.format(self.slot))
        for i in list(map(lambda x: create_dict(x), self.handle.execute('show app-instance detail').split('\r\n\r\n'))):
            if hasattr(i, 'App Name'):
                if hasattr(i, 'Oper State') and i['Oper State'] == 'Online':
                    apps.append(i['Identifier'])
        return apps

    def show_monitor_detail(self):
        self.handle.execute("top")
        scope(self.handle, 'ssa/slot {}'.format(self.slot))
        out = self.handle.execute('show monitor detail')
        if 'Error' in out:
            logger.info("Failed while trying to show monitor detail with error: {}".format(out))
            raise Exception("Failed while trying to show app-instance")
        resources = create_dict(out)
        resources['available_cores'] = resources.pop('CPU Cores Available')

        return resources
