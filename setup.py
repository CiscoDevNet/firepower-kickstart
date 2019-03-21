from distutils.core import setup
from setuptools import find_packages

setup(name='firepower-kick',
      version='0.1',
      packages=find_packages(exclude=["*.tests", "*.unittests", "*.unittest", "*.sample_tests"]),
      install_requires=['pyVmomi', 'paramiko', 'unicon', 'boto3',
                        'munch', 'beautifulsoup4', 'Fabric3'],
      include_package_data=True,
      )
