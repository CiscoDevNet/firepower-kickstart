import logging

from kick.device2.fxos.utils import create_dict, scope

logger = logging.getLogger(__name__)


class ResourceProfile:
    def __init__(self, handle, name):
        """
        Constructor of Resource Profile
        :param handle: SSH connection handle
        :param name: resource profile name
        """
        self.handle = handle
        self.name = name

    def configure(self, cpu):
        """
        Configures resource profile with specified parameters
        :param cpu: cpu count
        """
        cpu = str(cpu)
        logger.info('Configuring Resource Profile {}'.format(self.name))
        scope(self.handle, 'ssa')
        self.handle.execute('enter resource-profile {}'.format(self.name))
        self.handle.execute('set cpu-core-count {}'.format(cpu))
        output = self.handle.execute('commit-buffer')
        if 'Error' in output:
            logger.info("Failed while trying to configure resource profile with error: {}".format(output))
            raise Exception("Failed while trying to configure resource profile")
        self.handle.execute('discard')

        output = create_dict(self.handle.execute('show detail'))

        assert output['Profile Name'] == self.name, \
            "Mismatch in Profile Name! Expected: {}, Saw: {}".format(self.name, output['Profile Name'])
        assert ('Physical CPU Count' in output and output['Physical CPU Count'] == cpu) or (
                'CPU Logical Core Count' in output and output['CPU Logical Core Count'] == cpu), \
            "Mismatch in CPU Count! Expected: {}, Saw: {}".format(cpu, output['Physical CPU Count'])
        logger.info('Successfully Configured Resource Profile {}'.format(self.name))

    def delete(self):
        """
        Deletes resource profile
        """
        logger.info('Deleting Resource Profile {}'.format(self.name))
        scope(self.handle, 'ssa')
        self.handle.execute('delete resource-profile {}'.format(self.name))
        output = self.handle.execute('commit')
        if 'Error' in output:
            logger.info("Failed while trying to delete resource profile with error: {}".format(output))
            raise Exception("Failed while trying to delete resource profile")
        self.handle.execute('discard')

        output = self.handle.execute('show resource-profile detail')
        assert 'Profile Name: {}\r'.format(self.name) not in output, \
            "Found Resource Profile When It Should've Been Deleted"
        logger.info('Successfully Deleted Resource Profile {}'.format(self.name))

    def get(self):
        """
        Get information about the resource profile
        :return: dictionary with the data
        """
        scope(self.handle, 'ssa')
        scope(self.handle, 'resource-profile {}'.format(self.name))
        resources = create_dict(self.handle.execute('show detail'))
        resources['name'] = resources.pop('Profile Name')
        resources['model'] = resources.pop('Security Model')
        resources['cpu_core_count'] = resources.pop('CPU Logical Core Count')
        resources['profile_type'] = resources.pop('Profile Type')
        resources['usage'] = resources.pop('Is In Use')

        return resources
