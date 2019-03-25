"""Copyright (c) 2017 Cisco Systems, Inc.
Name:
    asa_cluster.py
Usage:
    Submodule for Legacy ASA GTP feature.
Author:
    raywa
"""

import re
from .asa_config import AsaConfig

class AsaGtpConfig(AsaConfig):
    """ASA Config for GTP inherited from AsaConfig
    """
    def __init__(self, **kwargs):
        """Initializer of AsaGtpConfig
        """
        super().__init__(**kwargs)

    def get_inspection_stats(self, ctx=None):
        """Show GTP service policy inspection statistics
        Example output:
           gtp-spykerd(config)# show service-policy inspect gtp statistics
           GPRS GTP Statistics:
              version_not_support               0     msg_too_short             0
              unknown_msg                       0     unexpected_sig_msg        0
              unexpected_data_msg               0     ie_duplicated             0
              mandatory_ie_missing              0     mandatory_ie_incorrect    0
              optional_ie_incorrect             0     ie_unknown                7182
              ie_out_of_order                   0     ie_unexpected             61046
              total_forwarded               14364     total_dropped             3474
              signalling_msg_dropped         3474     data_msg_dropped          0
              signalling_msg_forwarded      14364     data_msg_forwarded        0
              total created_pdp              3592     total deleted_pdp         0
              total created_pdpmcb           3592     total deleted_pdpmcb      0
              total dup_sig_mcbinfo             0     total dup_data_mcbinfo    0
              total v1 handoffs              3590     total v2_to_v1 handoffs   0
              total v2 handoffs                 0     total v1_to_v2 handoffs   0
              pdp_non_existent               3474     total_pdp_in_use          3592

        :param ctx: context name for multi mode only
        :return: dict of stats parameters

        """
        return_value = {}
        if self.topo.mode == 'standalone':
            output = self.execute('show service-policy inspect gtp statistics', ctx)
            stats = output[re.search('GTP Statistics:', output).end():].strip()
            for stat in stats.split('\n'):
                iter_stat = iter(re.split(' {2,}', stat.strip()))
                for param in zip(iter_stat, iter_stat):
                    return_value[param[0]] = int(param[1])
        elif self.topo.mode == 'cluster':
            pass
        return return_value

    def get_service_policy_stats(self, ctx=None):
        """Show GTP service policy statistics
        Example output:
            gtp-spykerd(config)# show service-policy | include gtp
            Inspect: gtp gtpmap, packet 6098, lock fail 0, drop 5550, reset-drop 0,
            5-min-pkt-rate 0 pkts/sec, v6-fail-close 0 sctp-drop-override 0

        :param ctx: context name for multi mode only
        :return: dict of stats parameters

        """
        return_value = {}
        if self.topo.mode == 'standalone':
            output = self.execute('show service-policy | include gtp', ctx).strip().split(',')
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
