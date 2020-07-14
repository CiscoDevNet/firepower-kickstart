import logging
import re

from kick.device2.fxos.resource import ResourceProfile
from kick.device2.fxos.utils import scope

logger = logging.getLogger(__name__)


class ResourceProfileUtils:
    def __init__(self, handle):
        """
        Constructor of App Instance
        :param handle: SSH connection handle
        """
        self.handle = handle

    def get_all(self):
        """
        Get all resource profiles
        :return:
        """
        scope(self.handle, 'ssa')
        profiles = []
        output = self.handle.execute('show resource-profile').split('\r\n')
        is_profile = False
        for i in output:
            if is_profile and re.match("^([\w\-]+)", i):
                match = re.match("^([\w\-]+)", i)
                profiles.append(match.group(1))
            if '---' in i:
                is_profile = True
        return profiles

    def delete_all(self):
        """
        Delete all resource profiles
        :return:
        """
        all_profiles = self.get_all()
        for profile in all_profiles:
            resource_profile = ResourceProfile(self.handle, profile)
            resource_profile.delete()

    def check_profile_present(self, name):
        """
        Check if resource profile exists
        :return:
        """
        all_profiles = self.get_all()
        for profile in all_profiles:
            if profile == name:
                return True
        return False
