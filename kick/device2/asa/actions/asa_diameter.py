"""Copyright (c) 2017 Cisco Systems, Inc.
Name:
    asa_cluster.py
Usage:
    Submodule for Legacy ASA Diameter feature.
Author:
    raywa
"""

import re
from .asa_config import AsaConfig

class AsaDiameterConfig(AsaConfig):
    """ASA Config for Diameter inherited from AsaConfig
    """
    def __init__(self, **kwargs):
        """Initializer of AsaDiameterConfig
        """
        super().__init__(**kwargs)

    def get_service_policy_stats(self, ctx=None):
        """Show Diameter service policy statistics
        Example output:
            gtp-spykerd(config)# show service-policy | include diameter
            Inspect: diameter diametermap, packet 4073569, lock fail 0, drop 0, reset-drop 0,
            5-min-pkt-rate 0 pkts/sec, v6-fail-close 0 sctp-drop-override 0

        :param ctx: context name for multi mode only
        :return: dict of stats parameters

        """
        return_value = {}
        if self.topo.mode == 'standalone':
            output = self.execute('show service-policy | include diameter', ctx).strip().split(',')
            return_value['policy_map'] = output[0].split()[-1]
            for param in output[1:]:
                param = param.strip()
                while True:
                    # pylint: disable=anomalous-backslash-in-string
                    match = re.search(' (\d+)', param)
                    if match:
                        return_value[param[:match.start()].strip()] = int(match.group(1))
                        param = param[match.end():]
                    else:
                        break
        elif self.topo.mode == 'cluster':
            pass
            # not supported now
        return return_value
        