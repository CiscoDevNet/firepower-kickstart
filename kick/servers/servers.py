import re
import os
from urllib.parse import urljoin
import os.path
import requests
from bs4 import BeautifulSoup
from functools import reduce

import logging

logger = logging.getLogger(__name__)


def search_engfs_with_regex(site, branch, version, subdir='installers',
                            pattern='.*'):
    """
    find all files in a list that resides on the site engfs server, under
    branch/version/subdir, and matching pattern.

    :param site: such as 'ful' or a custom server, such as http://10.106.134.200/
    :param branch: such as 'Feature/SSL_OFFLOAD'
    :param version: such as '6.2.3-430.SSL_OFFLOAD'
    :param subdir: such as 'installers'
    :param pattern: this is the pattern to use in regex.
    :return: list of files matching the search
    """

    # url below will look like: https://firepower-engfs-sjc.cisco.com/\
    # netboot/ims/Development/6.3.0-80013/installers/, it doesn't have the
    # last part for file name, since we passed in '' as file_name.
    if site.startswith("http"):
        url = urljoin(site, os.path.join(os.path.join(branch, version, subdir)))
    else:
        url = _construct_devit_url(site, os.path.join(branch, version, subdir), '')
    logger.debug("searching in {}".format(url))

    # get content from url
    r = requests.get(url)
    data = r.text
    soup = BeautifulSoup(data, 'lxml')

    # find all valid images: we rely on the assumption that for a valid image,
    # its text content is the same string as its href, as well as its title
    images = []

    for link in soup.find_all('a'):
        if link.getText() == link.get('title') == link.get('href'):
            images.append(link.getText())

    logger.debug("list of all images for branch {} version {} subdir {}: {}"
                 "".format(branch, version, subdir, images))

    result = []
    p = re.compile(pattern)
    for image in images:
        if p.search(image):
            result.append(image)

    logger.debug("found matching images: {}".format(result))

    return result


def flattenlist(alist):
    """Remove empty lists/values and flatten the list

    :param alist: list or list of lists
    :return: flatten list
    """

    alist = filter(None, alist)
    return reduce(lambda x, y: x + y, alist, [])


def get_devices_dict(version, image=None, arch=None, feature=None):
    """Based on version and image, returns a dictionary containing
       the folder location and the patterns of the installation files for
       each device type

    :param version: build version, e.g. 6.2.3-623
    :param image: optional, 'Autotest' or 'Restore', required for M3, M4, S3 (FMC and Sensor)
    :param arch: optional, device architecture, required for S3 (FMC and Sensor) - e.g x86_64
    :param feature: optional, whether the build is on a feature branch (e.g. MARIADB)
    :return: a dictionary
    """

    if feature is None:
        feature = ''
    else:
        feature = ".{}".format(feature)

    devices = {
        'kenton': {'patterns': ['ftd-[\d\.-]+{}.pkg'.format(feature), 'ftd-boot-[\d.]+lfbff'],
                   'subdir': ['installers', 'installers/doNotRelease'],
                   },
        'saleen': {'patterns': ['ftd-[\d\.-]+{}.pkg'.format(feature), 'ftd-boot-[\d.]+cdisk'],
                   'subdir': ['installers', 'installers/doNotRelease'],
                   },
        'elektra': {'patterns': ['asasfr-sys-[\d.-]+.pkg', 'asasfr-5500x-boot-[\d.-]+img'],
                    'subdir': ['installers', 'installers/doNotRelease'],
                    },
        'm3': {'patterns': ['Sourcefire_Defense_Center_S3-{}{}-{}.iso'.format(version, feature, image),
                            'Sourcefire_Defense_Center-{}{}-{}.iso'.format(version, feature, image),
                            'Cisco_Firepower_Mgmt_Center-{}{}-{}.iso'.format(version, feature, image)],
               'subdir': ['iso', 'iso/doNotRelease'],
               },
        'm4': {'patterns': ['Sourcefire_Defense_Center_M4-{}{}-{}.iso'.format(version, feature, image),
                            'Cisco_Firepower_Mgmt_Center-{}{}-{}.iso'.format(version, feature, image),
                            'Sourcefire_Defense_Center-{}{}-{}.iso'.format(version, feature, image)],
               'subdir': ['iso', 'iso/doNotRelease'],
               },
        'm5': {'patterns': ['Sourcefire_Defense_Center-{}{}-{}.iso'.format(version, feature, image),
                            'Cisco_Firepower_Mgmt_Center-{}{}-{}.iso'.format(version, feature, image)],
               'subdir': ['iso', 'iso/doNotRelease'],
               },
        's3fmc': {'patterns': ['Sourcefire_Defense_Center_S3-{}{}-{}.iso'.format(version, feature, image),
                               'Cisco_Firepower_Mgmt_Center-{}{}-{}.iso'.format(version, feature, image)],
                  'subdir': ['iso', 'iso/doNotRelease'],
                  'boot_images': {'os/{}/boot'.format(arch): 'bzImage.*',
                                  'os/{}/ramdisks'.format(arch): 'usb-ramdisk*'}
                  },
        's3': {'patterns': ['Sourcefire_3D_Device_S3-{}{}-{}.iso'.format(version, feature, image),
                            'Cisco_Firepower_NGIPS_Appliance-{}{}-{}.iso'.format(version, feature, image)],
               'subdir': ['iso', 'iso/doNotRelease'],
               'boot_images': {'os/{}/boot'.format(arch): 'bzImage.*',
                               'os/{}/ramdisks'.format(arch): 'usb-ramdisk*'}
               },
        'kp': {'patterns': ['cisco-ftd-fp2k[\d.-]+[a-zA-Z]{3}', 'fxos-k8-fp2k-lfbff[\w.-]+[a-zA-Z]{3}',
                            'fxos-k8-lfbff[\w.-]+[a-zA-Z]{3}'],
               'subdir': ['installers', 'installers/doNotRelease'],
               },
        'ssp': {'patterns': ['cisco-ftd[\d.-]+[a-zA-Z]{3}.csp'],
                'subdir': ['installers', 'installers/doNotRelease'],
                }
    }
    return devices
