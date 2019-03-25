from unicon.eal.dialogs import Dialog


CONFIGURATION_DIALOG = Dialog([
   ['[>#$] ', 'sendline()', None, False, False],
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
   ['Updated network configuration', None, None, True, False]
])


TYPE_TO_STATE_MAP = {
    "WmLine": "fxos_state",
    "KpLine": "fxos_state",
    "SspLine": "mio_state",
    "ChassisLine": "mio_state"
}
