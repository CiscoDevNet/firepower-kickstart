import time

from unicon.eal.dialogs import Dialog


def clear_error(spawn):
   time.sleep(0.1)
   spawn.sendline('\x15')
   time.sleep(0.5)
   spawn.sendline('')
   spawn.sendline('')


CONFIGURATION_DIALOG = Dialog([
   ['Press <ENTER> to display the EULA: ', 'sendline()', None, True, False],
   ['--More--', 'send(\x20)', None, True, False],
   ["Please enter 'YES' or press <ENTER> to AGREE to the EULA: ", 'sendline()', None, True, False],
   [r'\x07$', clear_error, None, True, True],
   ['> ', 'sendline(expert)', None, True, False],
   ['[#$] ', None, None, False, False],
   ['(F|f)irepower-module\d+>', None, None, False, False],
   ['Would you like to configure this system', 'sendline(FMC)', None, True, False],
   ['This selection cannot be undone', 'sendline(y)', None, True, False],
   ['Enter a fully qualified hostname for this system', 'sendline()', None, True, False],
   ['Configure IPv4 via DHCP or static configuration', 'sendline()', None, True, False],
   ['Enter an IPv4 address for the management interface', 'sendline()', None, True, False],
   ['Enter an IPv4 netmask for the management interface', 'sendline()', None, True, False],
   ['Enter the IPv4 default gateway for the management interface', 'sendline()', None, True, False],
   ['Do you want to configure IPv6', 'sendline()', None, True, False],
   ['Configure IPv6 via DHCP, router, or manually', 'sendline()', None, True, False],
   ['Enter the IPv6 address for the management interface', 'sendline()', None, True, False],
   ['Enter the IPv6 address prefix for the management interface', 'sendline()', None, True, False],
   ['Enter the IPv6 gateway for the management interface', 'sendline()', None, True, False],
   ['Enter a comma-separated list of DNS servers', 'sendline()', None, True, False],
   ['Enter a comma-separated list of search domains', 'sendline()', None, True, False],
   ['Enter a comma-separated list of NTP servers', 'sendline()', None, True, False],
   ['Are these settings correct', 'sendline(y)', None, True, False],
   ['Updated network configuration', None, None, True, False],
   ['Successfully set NTP configuration', None, None, True, False]
])

TYPE_TO_STATE_MAP = {
    "WmLine": "fxos_state",
    "KpLine": "fxos_state",
    "SspLine": "mio_state",
    "ChassisLine": "mio_state"
}

# list of line classes which are qualified for getting the hostname dynamically at
# ssh connection
DEVICE_LIST = ["<class 'kick.device2.ftd5500x.actions.ftd5500x.Ftd5500xLine'>",
               "<class 'kick.device2.ssp.actions.ssp.SspLine'>",
               "<class 'kick.device2.fmc.actions.fmc.FmcLine'>" ]
