import setuptools

with open("README.md", "r") as fh:
      long_description = fh.read()

setuptools.setup(
      name='firepower-kickstart',
      version='0.1.0',
      author="Cisco Systems Inc.",
      author_email="firepower-kickstart-support-ext@cisco.com",
      description="Python modules to install FTD images on hardware platforms.",
      long_description=long_description,
      long_description_content_type="text/markdown",
      url="https://github.com/CiscoDevNet/firepower-kickstart",
      packages=setuptools.find_packages(exclude=["*.tests", "*.unittests", "*.unittest", "*.sample_tests"]),
      install_requires=['pyVmomi', 'paramiko', 'unicon', 'boto3', 'munch', 'beautifulsoup4', 'Fabric3'],
      include_package_data=True,
      classifiers=[
            "Programming Language :: Python :: 3 :: Only",
            "Programming Language :: Python :: Implementation :: CPython",
            "License :: OSI Approved :: Apache Software License",
            "Operating System :: POSIX :: Linux",
      ],
)
