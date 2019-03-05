"""ASA Constants."""

from enum import Enum

class AsaSmStates(Enum):
    ENABLE_STATE = 'enable_state'
    DISABLE_STATE = 'disable_state'
    CONFIG_STATE = 'config_state'

class AsaConfigConstants:
    FIREWALL_MODE = dict(rfw='Router', tfw='Transparent')
    CONTEXT_MODE = dict(sfm='single', mfm='multiple')
    DELETE_NOCONFIRM = '/noconfirm'
    DISK0 = 'disk0'
    STATE = dict(disabled=False, disable=False, enabled=True, enable=True, false=False, true=True)
    STATE['False'] = False
    STATE['True'] = True

class ASAClusterStates(Enum):
    MASTER = 'MASTER'
    SLAVE = 'SLAVE'
    DISABLED = 'DISABLED'

class ASAHAStates(Enum):
    PRIMARY = 'Primary'
    SECONDARY = 'Secondary'
    ACTIVE = 'Active'
    STANDBY = 'Standby Ready'

class ASAHALinkNames(Enum):
    DEFAULT_FAILOVER_LINK = 'folink'
    DEFAULT_STATE_LINK = 'statelink'
